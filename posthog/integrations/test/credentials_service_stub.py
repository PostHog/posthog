"""An in-process stand-in for the `/v1/integrations` routes of the credentials service, over a `FakeBackend`.

`ServiceBackend(session=CredentialsServiceStub(...))` sends its requests here. The stub checks each
token like the service does and answers in the shapes of the service, so the shared backend tests
run the HTTP client end to end without a server.
"""

import json
import uuid
import hashlib
import datetime as dt
import tempfile
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlsplit

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from posthog.integrations.backend.fake_backend import FakeBackend
from posthog.integrations.backend.protocol import KindScope, NewIntegration, RowFilter, RowScope, SourceRows
from posthog.integrations.contracts import (
    SOURCE_MARKER_CONFIG_KEY,
    CrossTeamFilter,
    FrozenIntegrationRecord,
    IntegrationConflict,
    IntegrationNotFound,
    IntegrationPatch,
)
from posthog.integrations.enums import AuthType
from posthog.jwt import PosthogJwtAudience

AUDIENCE = PosthogJwtAudience.CREDENTIALS_SERVICE_INTEGRATIONS.value
ALLOWED_CLAIMS = frozenset({"aud", "exp", "iat", "jti", "owner", "ops", "kinds", "refs", "user_id", "caller"})
CROSS_TEAM_OPS = frozenset(
    {"list_across_teams", "read_by_external_id", "write_by_external_id", "delete_by_external_id"}
)
NEVER_EXPOSED = frozenset({"refresh_token", "client_secret"})
EVERY_ROW = RowScope(kinds=None, source_rows=SourceRows.INCLUDE)

STATUS = {
    "validation": 400,
    "unauthorized": 401,
    "forbidden_op": 403,
    "forbidden_kind": 403,
    "forbidden_ref": 403,
    "not_found": 404,
    "conflict": 409,
    "version_mismatch": 412,
    "unsupported_auth_type": 422,
    "unreadable_secret": 422,
    "kms_unavailable": 503,
}


def write_signing_key(directory: str) -> tuple[str, Ed25519PublicKey]:
    """Writes a new Ed25519 private key as a PEM file in `directory`. Returns its path and the public key."""
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    with tempfile.NamedTemporaryFile("wb", dir=directory, suffix=".pem", delete=False) as key_file:
        key_file.write(pem)
    return key_file.name, private_key.public_key()


class StubError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def response(status: int, body: object = None, headers: Mapping[str, str] | None = None) -> requests.Response:
    answer = requests.Response()
    answer.status_code = status
    answer._content = b"" if body is None else json.dumps(body).encode()
    answer.headers["Content-Type"] = "application/json"
    answer.headers.update(headers or {})
    return answer


def _page(rows: list[dict[str, Any]], limit: int, after: str | None) -> dict[str, Any]:
    start = int(after) if after else 0
    end = start + limit
    return {"results": rows[start:end], "next": str(end) if end < len(rows) else None}


def _ordered(rows: list[FrozenIntegrationRecord], newest_first: bool = False) -> list[FrozenIntegrationRecord]:
    return sorted(rows, key=lambda row: (row.created_at, row.id), reverse=newest_first)


class CredentialsServiceStub:
    """A `requests.Session` look-alike. Every answer comes from `fake`."""

    def __init__(self, fake: FakeBackend, public_key: Ed25519PublicKey) -> None:
        self.fake = fake
        self._public_key = public_key
        self._versions: dict[int, int] = {}
        self._jtis: set[str] = set()
        self._idempotency: dict[tuple[int, str], tuple[str, int]] = {}
        # (method, path, claims, headers) of each request that passed the token check.
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, str]]] = []
        # Raised, in order, instead of answering the next requests.
        self.failures: list[Exception] = []
        # Another writer changes the row this many times, just before a PATCH or DELETE checks `If-Match`.
        self.concurrent_writes = 0

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> requests.Response:
        if self.failures:
            raise self.failures.pop(0)
        prepared = requests.Request(method, url, params=params).prepare()
        parts = urlsplit(prepared.url or "")
        query = parse_qs(parts.query, keep_blank_values=True)
        path = parts.path.removeprefix("/v1/integrations")
        try:
            return self._route(method, path, query, json, dict(headers or {}))
        except StubError as error:
            if error.code == "unauthorized":
                return response(401)
            body = {"error": {"code": error.code, "message": error.code, "details": {}}}
            return response(STATUS[error.code], body)

    # Auth

    def _authorize(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        op: str,
        *,
        kinds: list[str] | None = None,
        refs: list[str] | None = None,
    ) -> dict[str, Any]:
        token = headers.get("Authorization", "").removeprefix("Bearer ")
        try:
            claims = jwt.decode(
                token,
                self._public_key,
                audience=AUDIENCE,
                algorithms=["EdDSA"],
                options={"require": ["exp", "iat"]},
            )
        except jwt.PyJWTError:
            raise StubError("unauthorized")
        if not set(claims) <= ALLOWED_CLAIMS or claims["exp"] - claims["iat"] > 60 or claims["jti"] in self._jtis:
            raise StubError("unauthorized")
        self._jtis.add(claims["jti"])
        if op not in claims["ops"]:
            raise StubError("forbidden_op")
        if "owner" not in claims and not set(claims["ops"]) <= CROSS_TEAM_OPS:
            raise StubError("unauthorized")
        if op not in CROSS_TEAM_OPS and "owner" not in claims:
            raise StubError("forbidden_op")
        if "kinds" in claims and kinds is not None and not set(kinds) <= set(claims["kinds"]):
            raise StubError("forbidden_kind")
        if refs and ("refs" not in claims or not set(refs) <= set(claims["refs"])):
            raise StubError("forbidden_ref")
        if "refs" in claims and not refs:
            raise StubError("forbidden_ref")
        self.calls.append((method, path, claims, headers))
        return claims

    @staticmethod
    def _owner(claims: dict[str, Any]) -> int:
        return claims["owner"]["id"]

    @staticmethod
    def _check_kind(claims: dict[str, Any], row: FrozenIntegrationRecord) -> None:
        if "kinds" in claims and row.kind not in claims["kinds"]:
            raise StubError("forbidden_kind")

    # Rows

    def _json(self, row: FrozenIntegrationRecord) -> dict[str, Any]:
        return {
            "id": str(uuid.UUID(int=row.id)),
            "legacy_id": row.id,
            "reference": row.reference,
            "team_id": row.team_id,
            "kind": row.kind,
            "integration_id": row.integration_id,
            "config": dict(row.config),
            "errors": row.errors,
            "created_at": row.created_at.isoformat(),
            "created_by_id": row.created_by_id,
            "auth_type": row.auth_type,
            "display_name": row.display_name,
            "is_source_row": SOURCE_MARKER_CONFIG_KEY in row.config,
            "version": self._versions.get(row.id, 1),
        }

    def _row(self, team_id: int, ref: str) -> FrozenIntegrationRecord:
        if not ref.isdigit():
            raise StubError("validation")
        try:
            return cast(FrozenIntegrationRecord, self.fake.get(EVERY_ROW, team_id=team_id, id=int(ref)))
        except IntegrationNotFound:
            raise StubError("not_found")

    def _bump(self, row_id: int) -> None:
        self._versions[row_id] = self._versions.get(row_id, 1) + 1

    def _check_version(self, row: FrozenIntegrationRecord, headers: dict[str, str]) -> None:
        if self.concurrent_writes > 0:
            self.concurrent_writes -= 1
            self._bump(row.id)
        if_match = headers.get("If-Match")
        if if_match is not None and int(if_match.strip('"')) != self._versions.get(row.id, 1):
            raise StubError("version_mismatch")

    @staticmethod
    def _scope(kinds: list[str] | None, auth_types: list[str] | None, source_rows: str) -> RowScope:
        if kinds is None:
            if auth_types:
                raise StubError("validation")
            return RowScope(kinds=None, source_rows=SourceRows(source_rows))
        types = None if auth_types is None else frozenset(AuthType(auth_type) for auth_type in auth_types)
        return RowScope(
            kinds=tuple(KindScope(kind=kind, auth_types=types) for kind in kinds), source_rows=SourceRows(source_rows)
        )

    @staticmethod
    def _patch(body: Mapping[str, Any]) -> IntegrationPatch:
        return IntegrationPatch(
            config_patch=body.get("config_patch") or {},
            config_remove=tuple(body.get("config_remove") or ()),
            sensitive_config_patch=body.get("sensitive_config_patch") or {},
            sensitive_config_remove=tuple(body.get("sensitive_config_remove") or ()),
            errors=body.get("errors"),
        )

    def _apply(self, row: FrozenIntegrationRecord, patch: IntegrationPatch) -> FrozenIntegrationRecord:
        after = self.fake.update(EVERY_ROW, team_id=row.team_id, id=row.id, patch=patch)
        if (after.config, after.errors, after.sensitive_config) != (row.config, row.errors, row.sensitive_config):
            self._bump(row.id)
        return cast(FrozenIntegrationRecord, after)

    def _new(self, owner: int, body: Mapping[str, Any]) -> NewIntegration:
        if body.get("auth_type") not in {"oauth", "token", "credentials"}:
            raise StubError("unsupported_auth_type")
        return NewIntegration(
            team_id=owner,
            kind=body["kind"],
            external_id=body.get("integration_id"),
            config=body.get("config") or {},
            sensitive_config=body.get("sensitive_config") or {},
            created_by_id=body.get("created_by_id"),
        )

    def _by_external_id(self, kind: str, external_id: str, source_rows: str, team_ids: list[int] | None = None):
        row_filter = RowFilter(external_id=external_id, team_ids=None if team_ids is None else tuple(team_ids))
        return _ordered(self.fake.list(self._scope([kind], None, source_rows), row_filter))  # type: ignore[arg-type]

    # Routes

    def _route(
        self, method: str, path: str, query: dict[str, list[str]], body: Any, headers: dict[str, str]
    ) -> requests.Response:
        segments = [unquote(segment) for segment in path.strip("/").split("/")] if path.strip("/") else []
        if segments[:1] == ["by-external-id"]:
            return self._external_id_route(method, segments[1], segments[2], query, body, headers)
        if method == "GET" and not segments:
            return self._list(query, headers)
        if method == "POST" and segments == ["resolve"]:
            return self._resolve(body, headers)
        if method == "POST" and segments == ["batch-get"]:
            return self._batch_get(body, headers)
        if method == "POST" and segments == ["list-across-teams"]:
            return self._list_across_teams(body, headers)
        if method == "POST" and not segments:
            return self._create(body, headers)
        if method == "PUT" and segments == ["upsert"]:
            return self._upsert(body, headers)
        if len(segments) == 1 and method in ("GET", "PATCH", "DELETE"):
            return self._one(method, segments[0], body, headers)
        raise StubError("not_found")

    def _list(self, query: dict[str, list[str]], headers: dict[str, str]) -> requests.Response:
        kinds = query.get("kind")
        claims = self._authorize("GET", "", headers, "read", kinds=kinds)
        source_rows = query.get("source_rows", ["exclude"])[0]
        where = {
            key.removeprefix("where."): json.loads(values[0])
            for key, values in query.items()
            if key.startswith("where.")
        }
        external_id = query.get("external_id", [None])[0]
        newest_first = query.get("newest_first", ["false"])[0] == "true"
        scope = self._scope(kinds or claims.get("kinds"), query.get("auth_type"), source_rows)
        rows = self.fake.list(scope, RowFilter(team_id=self._owner(claims), external_id=external_id, where=where))
        page_rows = [self._json(row) for row in _ordered(rows, newest_first)]  # type: ignore[arg-type]
        return response(200, _page(page_rows, int(query.get("limit", ["100"])[0]), query.get("after", [None])[0]))

    def _resolve(self, body: Any, headers: dict[str, str]) -> requests.Response:
        refs = body["refs"]
        claims = self._authorize("POST", "/resolve", headers, "resolve", refs=refs)
        result: dict[str, Any] = {"records": {}, "missing": [], "errors": {}}
        for ref in dict.fromkeys(refs):
            try:
                row = self._row(self._owner(claims), ref)
            except StubError:
                result["missing"].append(ref)
                continue
            self._check_kind(claims, row)
            secrets: object = row.sensitive_config
            if not isinstance(secrets, Mapping):
                result["errors"][ref] = {"code": "unreadable_secret", "message": "unreadable", "details": {}}
                continue
            refreshed_at, expires_in = row.config.get("refreshed_at"), row.config.get("expires_in")
            expires_at = (
                dt.datetime.fromtimestamp(refreshed_at + expires_in, tz=dt.UTC).isoformat()
                if isinstance(refreshed_at, int | float) and isinstance(expires_in, int | float)
                else None
            )
            result["records"][ref] = {
                "record": self._json(row),
                "credentials": {key: value for key, value in secrets.items() if key not in NEVER_EXPOSED},
                "expires_at": expires_at,
            }
        return response(200, result)

    def _batch_get(self, body: Any, headers: dict[str, str]) -> requests.Response:
        refs = body["refs"]
        claims = self._authorize("POST", "/batch-get", headers, "read", refs=refs)
        result: dict[str, Any] = {"records": {}, "missing": []}
        for ref in dict.fromkeys(refs):
            try:
                row = self._row(self._owner(claims), ref)
            except StubError:
                result["missing"].append(ref)
                continue
            self._check_kind(claims, row)
            result["records"][ref] = self._json(row)
        return response(200, result)

    def _list_across_teams(self, body: Any, headers: dict[str, str]) -> requests.Response:
        self._authorize("POST", "/list-across-teams", headers, "list_across_teams", kinds=body["kinds"])
        cross_team_filter = CrossTeamFilter(
            team_ids=body.get("team_ids"),
            exclude_team_ids=tuple(body.get("exclude_team_ids") or ()),
            created_by_ids=body.get("created_by_ids"),
            external_id=body.get("external_id"),
            where=body.get("where") or {},
            where_in=body.get("where_in") or {},
            where_iexact=body.get("where_iexact") or {},
            has_config_key=body.get("has_config_key"),
        )
        scope = self._scope(body["kinds"], body.get("auth_types"), body.get("source_rows") or "exclude")
        rows = self.fake.list_across_teams(scope, cross_team_filter)
        # The service orders by `created_at`, not by id.
        page_rows = [self._json(row) for row in _ordered(rows, body.get("newest_first", False))]  # type: ignore[arg-type]
        return response(200, _page(page_rows, body.get("limit") or 1000, body.get("after")))

    def _create(self, body: Any, headers: dict[str, str]) -> requests.Response:
        claims = self._authorize("POST", "", headers, "write", kinds=[body["kind"]])
        owner = self._owner(claims)
        key = headers.get("Idempotency-Key")
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if key is not None and (owner, key) in self._idempotency:
            earlier_digest, row_id = self._idempotency[(owner, key)]
            if earlier_digest != digest:
                raise StubError("conflict")
            return response(201, self._json(self._row(owner, str(row_id))), {"Idempotent-Replayed": "true"})
        try:
            row = self.fake.create(self._new(owner, body))
        except IntegrationConflict:
            raise StubError("conflict")
        if key is not None:
            self._idempotency[(owner, key)] = (digest, row.id)
        return response(201, self._json(row))  # type: ignore[arg-type]

    def _upsert(self, body: Any, headers: dict[str, str]) -> requests.Response:
        claims = self._authorize("PUT", "/upsert", headers, "write", kinds=[body["kind"]])
        new = self._new(self._owner(claims), body)
        existing = None
        if new.external_id is not None:
            existing = self.fake.find(
                RowScope(kinds=(KindScope(kind=new.kind),), source_rows=SourceRows.INCLUDE),
                RowFilter(team_id=new.team_id, external_id=new.external_id),
            )
        if existing is not None and (
            existing.auth_type != body["auth_type"]
            or (SOURCE_MARKER_CONFIG_KEY in existing.config) != bool(body.get("is_source_row"))
        ):
            raise StubError("conflict")
        row, created = self.fake.upsert(EVERY_ROW, new)
        if not created:
            self._bump(row.id)
        return response(201 if created else 200, {"record": self._json(row), "created": created})  # type: ignore[arg-type]

    def _one(self, method: str, ref: str, body: Any, headers: dict[str, str]) -> requests.Response:
        op = {"GET": "read", "PATCH": "write", "DELETE": "delete"}[method]
        claims = self._authorize(method, f"/{ref}", headers, op, refs=[ref])
        row = self._row(self._owner(claims), ref)
        self._check_kind(claims, row)
        if method == "GET":
            return response(200, self._json(row), {"ETag": f'"{self._versions.get(row.id, 1)}"'})
        self._check_version(row, headers)
        if method == "DELETE":
            self.fake.delete(EVERY_ROW, team_id=row.team_id, id=row.id)
            return response(204)
        return response(200, self._json(self._apply(row, self._patch(body))))

    def _external_id_route(
        self,
        method: str,
        kind: str,
        external_id: str,
        query: dict[str, list[str]],
        body: Any,
        headers: dict[str, str],
    ) -> requests.Response:
        op = {"GET": "read_by_external_id", "PATCH": "write_by_external_id", "DELETE": "delete_by_external_id"}[method]
        claims = self._authorize(method, f"/by-external-id/{kind}/{external_id}", headers, op, kinds=[kind])
        if "refs" in claims:
            raise StubError("forbidden_ref")
        source_rows = query.get("source_rows", ["exclude"])[0]
        team_ids = [int(team_id) for team_id in query["team_id"]] if "team_id" in query else None
        rows = self._by_external_id(kind, external_id, source_rows, team_ids)
        if method == "GET":
            page_rows = [self._json(row) for row in rows]
            return response(200, _page(page_rows, int(query.get("limit", ["1000"])[0]), query.get("after", [None])[0]))
        if method == "PATCH":
            patch = self._patch(body)
            updated = 0
            for row in rows:
                before = self._versions.get(row.id, 1)
                self._apply(row, patch)
                updated += self._versions.get(row.id, 1) != before
            return response(200, {"matched": len(rows), "updated": updated})
        for row in rows:
            self.fake.delete(EVERY_ROW, team_id=row.team_id, id=row.id)
        return response(200, {"deleted": len(rows)})
