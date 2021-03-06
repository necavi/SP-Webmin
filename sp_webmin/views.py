import re
import json
import requests

from flask import session, redirect, url_for, render_template, request
from flask.ext.openid import OpenID, COMMON_PROVIDERS
from flask.ext.login import LoginManager, login_user, logout_user

from werkzeug.contrib.cache import SimpleCache

from . import app, db
from .config import load_config, write_config
from .models import User, Permission, PermissionObject, Server, AnonymousUser
from .utilities import permission_required, permissions

oid = OpenID(app)
_steam_id_re = re.compile("steamcommunity.com/openid/id/(.*?)$")
login_manager = LoginManager(app)


steam_url = "http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={}&steamids={}"
login_manager.anonymous_user = AnonymousUser


def int_try_parse(value):
    try:
        return int(value), True
    except ValueError:
        return value, False


@app.route("/register")
@oid.loginhandler
def register_start():
    return oid.try_login(COMMON_PROVIDERS["steam"])


@app.route("/log_out", methods=["POST"])
def logout():
    logout_user()
    session.pop("steamid")
    return redirect(url_for("index"))


@oid.after_login
def create_or_login(resp):
    match = _steam_id_re.search(resp.identity_url)
    session["steamid"] = match.group(1)
    login_user(User.get(session["steamid"]))
    return redirect(oid.get_next_url())


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


@app.route("/")
@permission_required("web.pages.index")
def index():
    return render_template("index.html")


@app.route("/player_list")
@permission_required("web.pages.player_list")
def player_list():
    return render_template("player_list.html", objects=PermissionObject.query.all())


@app.route("/player_detail/<identifier>")
@permission_required("web.pages.player_detail")
def player_detail(identifier):
    obj = PermissionObject.get(identifier)
    return render_template("player_detail.html", obj=obj, servers=Server.list_servers(), type=type)


@app.route("/remove_object_permission", methods=["POST"])
@permission_required("web.permission.remove")
def remove_object_permission():
    obj = PermissionObject.get(request.form["identifier"])
    rem_perm = None
    for perm in obj.permissions:
        if perm.node == request.form["node"] and perm.server_id == int(request.form["server_id"]):
            rem_perm = perm
            break
    if rem_perm is not None:
        db.session.delete(rem_perm)
        db.session.commit()
    return redirect(url_for("player_detail", identifier=request.form["identifier"]))


@app.route("/add_object_permission", methods=["POST"])
@permission_required("web.permission.add")
def add_object_permission():
    obj = PermissionObject.get(request.form["identifier"])
    if obj is not None:
        perm = Permission(object_id=obj.identifier, server_id=request.form["server"], perm=request.form["node"])
        obj.permissions.append(perm)
        db.session.commit()
    return redirect(url_for("player_detail", identifier=request.form["identifier"]))


@app.route("/add_server", methods=["POST"])
@permission_required("web.server.add")
def add_server():
    name = request.form["name"]
    try:
        server = Server(name=name)
        db.session.add(server)
        db.session.commit()
    except:
        server = Server.query.filter_by(name=name).first()
    return json.dumps({
        "row": render_template("server_row.html", server_id=server.id, server_name=server.name)
    })


@app.route("/add_object", methods=["POST"])
@permission_required("web.object.add")
def add_object():
    identifier = request.form["identifier"]
    try:
        obj = PermissionObject(identifier, request.form["type"])
        db.session.add(obj)
        db.session.commit()
    except:
        obj = PermissionObject.query.filter_by(identifier=identifier).first()
    return json.dumps({
        "row": render_template("player_list_row.html", obj=obj)
    })


@app.route("/settings")
@permission_required("web.pages.settings")
def settings():
    return render_template("settings.html", config=load_config())


@app.route("/update_settings", methods=["POST"])
@permission_required("web.settings.update")
def update_settings():
    config = {key.upper().replace(" ", "_"): value for key, value in request.form.items()}
    config["STEAM_API_KEY"] = app.config["STEAM_API_KEY"]
    config["SQLALCHEMY_DATABASE_URI"] = app.config["SQLALCHEMY_DATABASE_URI"]
    write_config(config)
    app.config.update(config)
    return redirect(url_for("settings"))


steam_id_cache = SimpleCache()


def _check_steam_id(steam_id):
    if not steam_id.isdigit() or 15 > len(steam_id) > 20:
        return False, None
    player = steam_id_cache.get(steam_id)
    if player is None:
        url = steam_url.format(app.config["STEAM_API_KEY"], steam_id)
        steam_user = requests.get(url).json()
        players = steam_user["response"]["players"]
        if players:
            player = {"name": players[0]["personaname"]}
            steam_id_cache.set(steam_id, player)
        else:
            steam_id_cache.set(steam_id, False)
            return False, None
    if not player:
        return False, None
    return True, player


@app.route("/check_steam_id")
def check_steam_id():
    result, player = _check_steam_id(request.args.get("steamID", ""))
    if result:
        return json.dumps({
            "result": True,
            "player": player
        })
    else:
        return json.dumps({
            "result": False
        })


@app.route("/profile")
def my_profile():
    return render_template("error.html")


@app.route("/permissions")
def view_permissions():
    return render_template("permissions.html", permissions=permissions)
