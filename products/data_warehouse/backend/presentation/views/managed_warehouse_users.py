"""Adapter for the org-scoped managed warehouse DB user management API (duckgres).

Duckgres is the sole source of truth for DB user state: PostHog never stores a managed
warehouse username or password (the org's root `DuckgresServer` credentials are the one
exception, persisted at provision time so posthog can present a ready-to-use connection).
Every function here proxies live to the control plane via `managed_warehouse._request`, which
also gates on the org-scoped `data-warehouse-scene` feature flag.

Root-user protection: the control plane barely validates usernames and has no concept of a
"protected" user, so posthog refuses to let this API touch the org's root user (by name, or by
matching the persisted `DuckgresServer.username`) — mutating it here would desync posthog's
cached root connection from what duckgres actually has.
"""

import re
import secrets
from typing import TypedDict
from urllib.parse import quote
from uuid import UUID

from rest_framework import status
from rest_framework.response import Response

from posthog.ducklake.models import DuckgresServer

from products.data_warehouse.backend.presentation.views.managed_warehouse import PresentedConnection, _request

# duckgres requires a client-supplied password on create (see controlplane/admin/api.go
# createUser) and never echoes a password back (OrgUser.Password is `json:"-"`), so posthog
# generates one, shows it exactly once, and never persists it.
GENERATED_PASSWORD_BYTES = 32

RESERVED_USERNAMES = {"root", "postgres", "admin"}
# Lowercase letters, numbers, and underscores; must start with a letter. Mirrors duckgres's own
# (near-nonexistent) validation — posthog is the one enforcing a sane shape here.
USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


class PresentedUser(TypedDict):
    username: str
    disabled: bool
    created_at: str | None
    updated_at: str | None


def validate_username(username: str | None) -> str | None:
    """Return a human-readable error if `username` isn't a valid new DB username, else None."""
    if not username:
        return "Username is required"
    if username.lower() in RESERVED_USERNAMES:
        return f'"{username}" is a reserved name. Choose a different username'
    if not USERNAME_PATTERN.match(username):
        return "Username must be 3-63 characters: lowercase letters, numbers, and underscores, starting with a letter"
    return None


def _present_user(raw: dict) -> PresentedUser:
    """Strip internal knobs (passthrough, max_vcpus) from a duckgres OrgUser payload."""
    return PresentedUser(
        username=raw.get("username", ""),
        disabled=bool(raw.get("disabled", False)),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
    )


def _root_username(organization_id: UUID | str) -> str | None:
    """The org's root DuckgresServer username, if the warehouse has been provisioned."""
    server = DuckgresServer.objects.filter(organization_id=organization_id).only("username").first()
    return server.username if server else None


def _is_protected_username(organization_id: UUID | str, username: str) -> bool:
    """Whether `username` is the org's root database user (by name, or the literal "root")."""
    if username.lower() == "root":
        return True
    root_username = _root_username(organization_id)
    return root_username is not None and username == root_username


def _root_protection_error(message: str) -> Response:
    return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)


def _connection_for_org(organization_id: UUID | str, username: str) -> PresentedConnection | None:
    """The org's managed warehouse connection details (host/port/database), for `username`.

    Reuses the `DuckgresServer` row persisted at provision time rather than recomputing the
    host, since only that row (not this call) knows the org's chosen warehouse name. Returns
    None if the warehouse hasn't been provisioned yet.
    """
    server = DuckgresServer.objects.filter(organization_id=organization_id).only("host", "port", "database").first()
    if server is None:
        return None
    return PresentedConnection(host=server.host, port=server.port, database=server.database, username=username)


def _user_path(username: str) -> str:
    return f"/users/{quote(username, safe='')}"


def list_users(organization_id: UUID | str) -> Response:
    """List this org's DB users, via the org-scoped endpoint (never the global user list)."""
    resp = _request("GET", organization_id, "")
    if resp.status_code == status.HTTP_200_OK and isinstance(resp.data, dict):
        users = resp.data.get("users") or []
        presented = sorted((_present_user(u) for u in users), key=lambda u: u["username"])
        return Response(presented, status=status.HTTP_200_OK)
    return resp


def create_user(organization_id: UUID | str, username: str | None) -> Response:
    username_error = validate_username(username)
    if username_error or username is None:
        return Response({"error": username_error or "Username is required"}, status=status.HTTP_400_BAD_REQUEST)

    if _is_protected_username(organization_id, username):
        return _root_protection_error(f'"{username}" is reserved for the root database user. Choose another name')

    password = secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)
    resp = _request(
        "POST",
        organization_id,
        "users",
        json_body={
            "username": username,
            "password": password,
            "org_id": str(organization_id),
            "passthrough": False,
            "max_vcpus": 0,
        },
    )
    if resp.status_code != status.HTTP_201_CREATED or not isinstance(resp.data, dict):
        return resp

    # duckgres never echoes the password back (OrgUser.Password is `json:"-"`), so the response
    # is built from what posthog generated, not from the control plane's body.
    return Response(
        {
            "username": username,
            "password": password,
            "connection": _connection_for_org(organization_id, username),
        },
        status=status.HTTP_201_CREATED,
    )


def delete_user(organization_id: UUID | str, username: str) -> Response:
    if _is_protected_username(organization_id, username):
        return _root_protection_error(
            "Can't delete the root database user here. Use the reset password option in "
            "warehouse settings if you need to rotate its credentials."
        )
    return _request("DELETE", organization_id, _user_path(username))


def reset_user_password(organization_id: UUID | str, username: str) -> Response:
    if _is_protected_username(organization_id, username):
        return _root_protection_error(
            "Can't reset the root database user's password here. Use the reset password option "
            "in warehouse settings instead."
        )
    password = secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)
    resp = _request("PUT", organization_id, _user_path(username), json_body={"password": password})
    if resp.status_code != status.HTTP_200_OK or not isinstance(resp.data, dict):
        return resp
    return Response({"username": username, "password": password}, status=status.HTTP_200_OK)


def disable_user(organization_id: UUID | str, username: str) -> Response:
    if _is_protected_username(organization_id, username):
        return _root_protection_error(
            "Can't disable the root database user here. Use the reset password option in "
            "warehouse settings if you need to rotate its credentials."
        )
    return _request("POST", organization_id, _user_path(username) + "/disable")


def enable_user(organization_id: UUID | str, username: str) -> Response:
    return _request("POST", organization_id, _user_path(username) + "/enable")
