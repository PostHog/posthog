"""The `StorageBackend` that keeps the rows in the credentials service and reads them over HTTP.

The routes are in `services/credentials-service` ("Integrations API" in its README). The service
returns no secret from a plain read, so a team read loads the secrets of its rows with
`POST /resolve`, and an in-process cache holds those results for a short time.

`change_external_id`, `refresh_access_token`, `count_by_external_ids`, `update_where` and the
repository cache operations have no route yet. They raise `NotImplementedError`, and
`test_backends.py` skips their cases for this backend.
"""

import json
import time
import uuid
import builtins
import functools
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import field
from datetime import datetime
from typing import Any, Literal, NoReturn
from urllib.parse import quote

from django.conf import settings

import jwt
import requests
from cachetools import TTLCache
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from posthog.credentials_service.callers import CredentialsCaller
from posthog.dataclasses import frozen
from posthog.integrations.backend.protocol import (
    KindScope,
    NewIntegration,
    RowFilter,
    RowScope,
    SourceRows,
    TokenRefresh,
)
from posthog.integrations.contracts import (
    SOURCE_MARKER_CONFIG_KEY,
    CrossTeamFilter,
    FrozenIntegrationRecord,
    IntegrationConflict,
    IntegrationNotFound,
    IntegrationPatch,
    IntegrationRecord,
    RepositoryCache,
    UnsupportedAuthType,
    UpdatedRows,
)
from posthog.integrations.secret_reads import UndecryptedIntegrationSecretError
from posthog.jwt import PosthogJwtAudience
from posthog.models.integration.auth_types import effective_auth_type
from posthog.models.integration.model import Integration
from posthog.security.outbound_proxy import internal_requests

INTEGRATIONS_PATH = "/v1/integrations"
# Integrations tokens use an asymmetric algorithm, so the service holds only the public key.
TOKEN_ALGORITHM = "EdDSA"
# The service rejects a token that lives longer than 60 seconds.
TOKEN_LIFETIME_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 5
REQUEST_ATTEMPTS = 2
# The largest page and the largest ref list that one request can ask for.
PAGE_SIZE = 1000
MAX_REFS_PER_REQUEST = 200
# A write reads the row, checks the scope, and sends the version it read in `If-Match`. A
# concurrent write changes the version, so the backend reads the row again.
WRITE_ATTEMPTS = 3
RESOLVE_CACHE_TTL_SECONDS = 60
RESOLVE_CACHE_MAX_ROWS = 10_000

ServiceOp = Literal[
    "read",
    "write",
    "delete",
    "resolve",
    "list_across_teams",
    "read_by_external_id",
    "write_by_external_id",
    "delete_by_external_id",
]

# Keyed by the step of an SDK operation that one token covers. A token with no owner may hold only
# cross-team ops, so a step that reads rows of every team and a step that resolves the secrets of one
# team get separate tokens.
_OPS: dict[str, tuple[ServiceOp, ...]] = {
    # `resolve` returns a row with its secrets. `read` loads a row whose secret the service cannot decrypt.
    "get": ("resolve", "read"),
    "get_many": ("resolve", "read"),
    "resolve": ("resolve", "read"),
    "find": ("read",),
    "list": ("read",),
    "exists": ("read",),
    "count": ("read",),
    "list_across_teams": ("list_across_teams",),
    "read_by_external_id": ("read_by_external_id",),
    "create": ("write",),
    "upsert": ("write",),
    # A write reads the row first, to check the scope and to send its version in `If-Match`.
    "update": ("read", "write"),
    "delete": ("read", "delete"),
    "update_by_external_id": ("write_by_external_id",),
    "delete_by_external_id": ("delete_by_external_id",),
}


_CROSS_TEAM_OPS = frozenset(
    {"list_across_teams", "read_by_external_id", "write_by_external_id", "delete_by_external_id"}
)


def _ops_for(operation: str) -> tuple[ServiceOp, ...]:
    """The service ops that the token of one step of an SDK operation holds. Each token allows only these."""
    return _OPS[operation]


class IntegrationServiceError(Exception):
    """The credentials service refused a request, and no SDK exception fits the reason.

    `code` is the error code of the service, for example `forbidden_op` or `validation`. These
    errors come from configuration or from a bug in the client, not from the row.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@functools.cache
def _load_signing_key(path: str) -> Ed25519PrivateKey:
    """Reads the Ed25519 private key of this deployment from a mounted file, once per process."""
    try:
        with open(path, "rb") as key_file:
            key = load_pem_private_key(key_file.read(), password=None)
    except (OSError, ValueError, TypeError) as error:
        raise IntegrationServiceError(
            "unconfigured",
            f"CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH must name a readable PEM Ed25519 private key file ({type(error).__name__})",
        ) from error
    if not isinstance(key, Ed25519PrivateKey):
        raise IntegrationServiceError(
            "unconfigured", "CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH must hold an Ed25519 private key"
        )
    return key


class IntegrationServiceUnavailable(IntegrationServiceError):
    """The credentials service did not answer, failed, or could not reach its key service. Retry later."""


class _VersionMismatch(IntegrationConflict):
    """The row changed after the backend read it. A write reads the row again."""


def _raise_for_error(response: requests.Response) -> NoReturn:
    code, message = "unknown", f"status {response.status_code}"
    try:
        error = response.json()["error"]
        code, message = str(error["code"]), str(error.get("message") or message)
    except (ValueError, KeyError, TypeError):
        # A rejected token gets a bare 401, with no JSON body.
        if response.status_code == 401:
            code = "unauthorized"
    if code in ("not_found", "forbidden_kind"):
        # A row of a kind that the token does not name is out of the scope of the accessor.
        raise IntegrationNotFound(message)
    if code == "version_mismatch":
        raise _VersionMismatch(message)
    if code == "conflict":
        raise IntegrationConflict(message)
    if code == "unsupported_auth_type":
        raise UnsupportedAuthType(message)
    if code == "unreadable_secret":
        raise UndecryptedIntegrationSecretError()
    if code == "kms_unavailable" or response.status_code >= 500:
        raise IntegrationServiceUnavailable(code, message)
    raise IntegrationServiceError(code, message)


class _SecretsUnavailable(Mapping[str, Any]):
    """The secrets of a record that the backend cannot give. Every read raises."""

    def _error(self) -> Exception:
        return NotImplementedError()

    def __getitem__(self, key: str) -> Any:
        raise self._error()

    def __iter__(self) -> Iterator[str]:
        raise self._error()

    def __len__(self) -> int:
        raise self._error()

    # Records compare their fields. A comparison must not read the secrets.
    def __eq__(self, other: object) -> bool:
        return type(other) is type(self)

    def __hash__(self) -> int:
        return hash(type(self))


class _UnreadableSecrets(_SecretsUnavailable):
    """The service cannot decrypt the secrets of the row. Like `Integration.access_token`, a read raises."""

    def _error(self) -> Exception:
        return UndecryptedIntegrationSecretError()


class _WithheldSecrets(_SecretsUnavailable):
    """`list_across_teams` returns no secrets."""

    def _error(self) -> Exception:
        return IntegrationServiceError(
            "secrets_withheld", "list_across_teams returns rows without secrets. Read the row with get."
        )


@frozen
class _Resolved:
    """One row and its secrets, as `POST /resolve` returned them."""

    record: Mapping[str, Any]
    # None when the service cannot decrypt the secrets.
    credentials: Mapping[str, Any] | None = field(repr=False)
    # When the access token of the row expires, in seconds since the epoch.
    expires_at: float | None


class _ResolveCache:
    """The `resolve` results of each (team, ref), for a short time. Never past `expires_at`."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._entries: TTLCache[tuple[int, str], _Resolved] = TTLCache(
            maxsize=RESOLVE_CACHE_MAX_ROWS, ttl=RESOLVE_CACHE_TTL_SECONDS, timer=clock
        )
        self._lock = threading.Lock()
        # Counts invalidations, so a resolve that started before one does not store what it read.
        self._generation = 0

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def get(self, team_id: int, ref: str) -> _Resolved | None:
        with self._lock:
            resolved = self._entries.get((team_id, ref))
        if resolved is None or (resolved.expires_at is not None and resolved.expires_at <= self._clock()):
            return None
        return resolved

    def put(self, team_id: int, ref: str, resolved: _Resolved, generation: int) -> None:
        if resolved.expires_at is not None and resolved.expires_at <= self._clock():
            return
        with self._lock:
            if generation == self._generation:
                self._entries[(team_id, ref)] = resolved

    def invalidate(self, team_id: int, ref: str) -> None:
        with self._lock:
            self._generation += 1
            self._entries.pop((team_id, ref), None)


def _unsupported(operation: str) -> NotImplementedError:
    return NotImplementedError(f"The credentials service has no route for {operation} yet")


def _lookup_id(value: object) -> int | None:
    # Django converts an id with `int()` and finds no row when that fails.
    try:
        legacy_id = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None
    return legacy_id if legacy_id >= 0 else None


def _chunks(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _timestamp(value: object) -> float | None:
    return datetime.fromisoformat(value).timestamp() if isinstance(value, str) else None


def _display_name(kind: str, external_id: str | None, config: Mapping[str, object]) -> str:
    # The service has its own display name rule. An unsaved model instance gives the same name as
    # `DjangoBackend`, with no query.
    return Integration(kind=kind, integration_id=external_id, config=dict(config)).display_name


def _to_record(body: Mapping[str, Any], secrets: Mapping[str, Any]) -> FrozenIntegrationRecord:
    legacy_id = body.get("legacy_id")
    if type(legacy_id) is not int:
        # The SDK reads rows by int id. A row that the service created has only a UUID.
        raise IntegrationServiceError("no_legacy_id", f"Integration {body.get('reference')} has no int id")
    kind, external_id, config = body["kind"], body.get("integration_id"), dict(body.get("config") or {})
    return FrozenIntegrationRecord(
        id=legacy_id,
        reference=str(body["reference"]),
        team_id=int(body["team_id"]),
        kind=kind,
        integration_id=external_id,
        config=config,
        sensitive_config=secrets,
        errors=body.get("errors") or "",
        created_at=datetime.fromisoformat(body["created_at"]),
        created_by_id=body.get("created_by_id"),
        auth_type=str(body["auth_type"]),
        display_name=_display_name(kind, external_id, config),
    )


def _sort_key(body: Mapping[str, Any]) -> tuple[datetime, int]:
    return datetime.fromisoformat(body["created_at"]), body.get("legacy_id") or 0


def _in_scope(scope: RowScope, body: Mapping[str, Any]) -> bool:
    is_source_row = bool(body.get("is_source_row"))
    if scope.source_rows == SourceRows.EXCLUDE and is_source_row:
        return False
    if scope.source_rows == SourceRows.ONLY and not is_source_row:
        return False
    if scope.kinds is None:
        return True
    for kind in scope.kinds:
        if kind.kind == body.get("kind"):
            return kind.auth_types is None or body.get("auth_type") in {
                auth_type.value for auth_type in kind.auth_types
            }
    return False


@frozen
class _KindGroup:
    """Kinds that share one set of auth types. None reaches every kind, or every auth type."""

    kinds: builtins.list[str] | None
    auth_types: builtins.list[str] | None


def _kind_groups(scope: RowScope) -> builtins.list[_KindGroup]:
    """The kind groups of the scope. The service filters on kinds and on auth types, each on its own."""
    if scope.kinds is None:
        return [_KindGroup(kinds=None, auth_types=None)]
    groups: dict[frozenset[str] | None, builtins.list[str]] = {}
    for kind in scope.kinds:
        auth_types = None if kind.auth_types is None else frozenset(auth_type.value for auth_type in kind.auth_types)
        # An empty set of auth types reaches no row.
        if auth_types != frozenset():
            groups.setdefault(auth_types, []).append(kind.kind)
    return [
        _KindGroup(kinds=sorted(kinds), auth_types=None if auth_types is None else sorted(auth_types))
        for auth_types, kinds in groups.items()
    ]


def _scope_kinds(scope: RowScope) -> builtins.list[str] | None:
    return None if scope.kinds is None else sorted({kind.kind for kind in scope.kinds})


class ServiceBackend:
    """The rows in the credentials service. Safe to share between threads."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        caller: CredentialsCaller = CredentialsCaller.INTEGRATIONS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._session = session or internal_requests
        self._caller = caller
        # Only the cache reads `clock`. Tokens always use the real time.
        self._cache = _ResolveCache(clock)

    # Transport

    def _token(
        self,
        operation: str,
        *,
        team_id: int | None,
        kinds: Iterable[str] | None = None,
        refs: Iterable[str] | None = None,
        user_id: int | None = None,
    ) -> Callable[[], str]:
        ops = builtins.list(_ops_for(operation))
        # Each token has one owner. Only a cross-team token has none.
        if (team_id is None) != _CROSS_TEAM_OPS.issuperset(ops):
            raise ValueError(f"Operation {operation!r} and team_id={team_id!r} do not match")
        kind_claim = None if kinds is None else sorted(set(kinds))
        ref_claim = None if refs is None else sorted(set(refs))

        def mint() -> str:
            if not settings.CREDENTIALS_SERVICE_URL or not settings.CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH:
                raise IntegrationServiceError(
                    "unconfigured",
                    "Set CREDENTIALS_SERVICE_URL and CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH",
                )
            signing_key = _load_signing_key(settings.CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH)
            issued_at = int(time.time())
            claims: dict[str, Any] = {
                "aud": PosthogJwtAudience.CREDENTIALS_SERVICE_INTEGRATIONS.value,
                "iat": issued_at,
                "exp": issued_at + TOKEN_LIFETIME_SECONDS,
                # The service accepts each jti once.
                "jti": uuid.uuid4().hex,
                "ops": ops,
                "caller": str(self._caller),
            }
            if team_id is not None:
                claims["owner"] = {"type": "team", "id": team_id}
            if kind_claim is not None:
                claims["kinds"] = kind_claim
            if ref_claim is not None:
                claims["refs"] = ref_claim
            if user_id is not None:
                claims["user_id"] = user_id
            return jwt.encode(claims, signing_key, algorithm=TOKEN_ALGORITHM)

        return mint

    def _request(
        self,
        method: str,
        path: str,
        token: Callable[[], str],
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        not_found_ok_on_retry: bool = False,
    ) -> requests.Response | None:
        url = f"{settings.CREDENTIALS_SERVICE_URL.rstrip('/')}{INTEGRATIONS_PATH}{path}"
        for attempt in range(1, REQUEST_ATTEMPTS + 1):
            # A new token for each attempt: the service may have used the jti of the first one.
            request_headers = {"Authorization": f"Bearer {token()}", **(headers or {})}
            try:
                response = self._session.request(
                    method, url, params=params, json=body, headers=request_headers, timeout=REQUEST_TIMEOUT_SECONDS
                )
            except requests.ConnectionError as error:
                if attempt < REQUEST_ATTEMPTS:
                    continue
                raise IntegrationServiceUnavailable(
                    "unreachable", f"{method} {path}: {type(error).__name__}"
                ) from error
            except requests.RequestException as error:
                raise IntegrationServiceUnavailable(
                    "unreachable", f"{method} {path}: {type(error).__name__}"
                ) from error
            if response.status_code < 400:
                return response
            # The first attempt may have deleted the row before the connection dropped.
            if not_found_ok_on_retry and attempt > 1 and response.status_code == 404:
                return None
            _raise_for_error(response)
        raise AssertionError("unreachable")

    def _json(self, method: str, path: str, token: Callable[[], str], **kwargs: Any) -> Any:
        response = self._request(method, path, token, **kwargs)
        try:
            return response.json() if response is not None else None
        except ValueError as error:
            raise IntegrationServiceUnavailable("bad_response", f"{method} {path} did not answer JSON") from error

    # Secrets

    def _resolve(
        self, operation: str, team_id: int, refs: Iterable[str], *, use_cache: bool = True
    ) -> dict[str, _Resolved]:
        """The rows of the team with these refs, and their secrets. A ref with no row is missing."""
        found: dict[str, _Resolved] = {}
        wanted: builtins.list[str] = []
        for ref in dict.fromkeys(refs):
            cached = self._cache.get(team_id, ref) if use_cache else None
            if cached is not None:
                found[ref] = cached
            else:
                wanted.append(ref)
        for chunk in _chunks(wanted, MAX_REFS_PER_REQUEST):
            generation = self._cache.generation()
            token = self._token(operation, team_id=team_id, refs=chunk)
            answer = self._json("POST", "/resolve", token, body={"refs": builtins.list(chunk)})
            resolved = {
                ref: _Resolved(
                    record=item["record"], credentials=item["credentials"], expires_at=_timestamp(item["expires_at"])
                )
                for ref, item in (answer.get("records") or {}).items()
            }
            unreadable = builtins.list(answer.get("errors") or {})
            if unreadable:
                # The resolve answer holds no record for these refs.
                rows = self._json("POST", "/batch-get", token, body={"refs": unreadable})
                for ref, record in (rows.get("records") or {}).items():
                    resolved[ref] = _Resolved(record=record, credentials=None, expires_at=None)
            for ref, item in resolved.items():
                self._cache.put(team_id, ref, item, generation)
            found.update(resolved)
        return found

    @staticmethod
    def _secrets(resolved: _Resolved) -> Mapping[str, Any]:
        return _UnreadableSecrets() if resolved.credentials is None else dict(resolved.credentials)

    def _with_secrets(self, rows: Iterable[Mapping[str, Any]]) -> builtins.list[IntegrationRecord]:
        rows = builtins.list(rows)
        refs_by_team: dict[int, builtins.list[str]] = {}
        for row in rows:
            refs_by_team.setdefault(int(row["team_id"]), []).append(str(row["reference"]))
        resolved = {
            (team_id, ref): item
            for team_id, refs in refs_by_team.items()
            for ref, item in self._resolve("resolve", team_id, refs).items()
        }
        # A cached resolve older than the listed row holds old secrets. Read those rows again, and build
        # each record from the resolve answer, so its metadata and secrets come from one version.
        stale_by_team: dict[int, builtins.list[str]] = {}
        for row in rows:
            key = (int(row["team_id"]), str(row["reference"]))
            if key in resolved and resolved[key].record.get("version") != row.get("version"):
                stale_by_team.setdefault(key[0], []).append(key[1])
        for team_id, refs in stale_by_team.items():
            fresh = self._resolve("resolve", team_id, refs, use_cache=False)
            for ref in refs:
                resolved.pop((team_id, ref), None)
            resolved.update({(team_id, ref): item for ref, item in fresh.items()})
        records: builtins.list[IntegrationRecord] = []
        for row in rows:
            item = resolved.get((int(row["team_id"]), str(row["reference"])))
            # A row that another process deleted after the list.
            if item is not None:
                records.append(_to_record(item.record, self._secrets(item)))
        return records

    # Reads

    def _list_pages(
        self,
        operation: str,
        team_id: int,
        scope: RowScope,
        group: _KindGroup,
        row_filter: RowFilter,
        *,
        newest_first: bool,
        limit: int | None,
    ) -> Iterator[Mapping[str, Any]]:
        params: dict[str, Any] = {
            "source_rows": scope.source_rows.value,
            "newest_first": "true" if newest_first else "false",
            "limit": min(limit or PAGE_SIZE, PAGE_SIZE),
        }
        if group.kinds is not None:
            params["kind"] = group.kinds
        if group.auth_types is not None:
            params["auth_type"] = group.auth_types
        if row_filter.external_id is not None:
            params["external_id"] = row_filter.external_id
        for key, value in row_filter.where.items():
            # The service reads each value as JSON, so the comparison keeps the JSON type.
            params[f"where.{key}"] = json.dumps(value)
        returned = 0
        while True:
            page = self._json("GET", "", self._token(operation, team_id=team_id, kinds=group.kinds), params=params)
            for row in page["results"]:
                yield row
                returned += 1
                if limit is not None and returned >= limit:
                    return
            if not page.get("next"):
                return
            params["after"] = page["next"]

    def _across_teams_pages(self, scope: RowScope, body: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
        """Every row of every team that matches `body`, for each (kinds, auth types) group of the scope."""
        for group in _kind_groups(scope):
            if group.kinds is None:
                raise IntegrationServiceError("validation", "A read across teams needs an accessor with a kind")
            page_body: dict[str, Any] = {
                **body,
                "kinds": group.kinds,
                "auth_types": group.auth_types,
                "source_rows": scope.source_rows.value,
                "limit": PAGE_SIZE,
            }
            while True:
                token = self._token("list_across_teams", team_id=None, kinds=group.kinds)
                page = self._json("POST", "/list-across-teams", token, body=page_body)
                yield from page["results"]
                if not page.get("next"):
                    break
                page_body["after"] = page["next"]

    @staticmethod
    def _external_id_path(kind: str, external_id: str) -> str:
        return f"/by-external-id/{quote(kind, safe='')}/{quote(external_id, safe='')}"

    def _by_external_id_pages(self, scope: RowScope, external_id: str) -> Iterator[Mapping[str, Any]]:
        """The rows of every team with this external id that are in the scope. Web only."""
        if scope.kinds is None:
            raise IntegrationServiceError("validation", "A read by external id needs an accessor with a kind")
        for kind in sorted({kind.kind for kind in scope.kinds}):
            params: dict[str, Any] = {"source_rows": scope.source_rows.value, "limit": PAGE_SIZE}
            while True:
                token = self._token("read_by_external_id", team_id=None, kinds=[kind])
                page = self._json("GET", self._external_id_path(kind, external_id), token, params=params)
                # The route has no auth type filter.
                yield from (row for row in page["results"] if _in_scope(scope, row))
                if not page.get("next"):
                    break
                params["after"] = page["next"]

    def _select(
        self,
        operation: str,
        scope: RowScope,
        row_filter: RowFilter,
        *,
        newest_first: bool = False,
        limit: int | None = None,
    ) -> builtins.list[Mapping[str, Any]]:
        """The rows that match, ordered by `created_at` and then id, with no secrets."""
        rows: builtins.list[Mapping[str, Any]] = []
        if row_filter.team_id is None and row_filter.team_ids is None:
            if row_filter.external_id is not None and not row_filter.where:
                rows.extend(self._by_external_id_pages(scope, row_filter.external_id))
            else:
                body = {"external_id": row_filter.external_id, "where": dict(row_filter.where)}
                rows.extend(self._across_teams_pages(scope, body))
        else:
            team_ids = [row_filter.team_id] if row_filter.team_id is not None else row_filter.team_ids or ()
            for team_id in dict.fromkeys(team_ids):
                for group in _kind_groups(scope):
                    rows.extend(
                        self._list_pages(
                            operation,
                            team_id,
                            scope,
                            group,
                            row_filter,
                            newest_first=newest_first,
                            limit=limit,
                        )
                    )
        rows.sort(key=_sort_key, reverse=newest_first)
        return rows if limit is None else rows[:limit]

    def get(self, scope: RowScope, *, team_id: int, id: int) -> IntegrationRecord:
        legacy_id = _lookup_id(id)
        resolved = None if legacy_id is None else self._resolve("get", team_id, [str(legacy_id)]).get(str(legacy_id))
        if resolved is None or not _in_scope(scope, resolved.record):
            raise IntegrationNotFound(f"No integration {id!r} in {scope!r} for team {team_id}")
        return _to_record(resolved.record, self._secrets(resolved))

    def get_many(self, scope: RowScope, *, team_id: int, ids: Sequence[int]) -> dict[int, IntegrationRecord]:
        # Like Django, an id that `int()` cannot convert raises.
        refs = [str(legacy_id) for legacy_id in (int(id) for id in ids) if legacy_id >= 0]
        records = (
            _to_record(item.record, self._secrets(item))
            for item in self._resolve("get_many", team_id, refs).values()
            if _in_scope(scope, item.record)
        )
        return {record.id: record for record in records}

    def find(self, scope: RowScope, row_filter: RowFilter) -> IntegrationRecord | None:
        records = self._with_secrets(self._select("find", scope, row_filter, limit=1))
        return records[0] if records else None

    def list(
        self, scope: RowScope, row_filter: RowFilter, *, newest_first: bool = False
    ) -> builtins.list[IntegrationRecord]:
        return self._with_secrets(self._select("list", scope, row_filter, newest_first=newest_first))

    def exists(self, scope: RowScope, row_filter: RowFilter) -> bool:
        return bool(self._select("exists", scope, row_filter, limit=1))

    def count(self, scope: RowScope, row_filter: RowFilter) -> int:
        return len(self._select("count", scope, row_filter))

    def get_by_external_id(self, scope: RowScope, *, external_id: str, id: int) -> IntegrationRecord:
        legacy_id = _lookup_id(id)
        rows = (
            []
            if legacy_id is None
            else [row for row in self._by_external_id_pages(scope, external_id) if row.get("legacy_id") == legacy_id]
        )
        records = self._with_secrets(rows)
        if not records:
            raise IntegrationNotFound(f"No integration {id!r} with external id {external_id!r} in {scope!r}")
        return records[0]

    def list_across_teams(
        self, scope: RowScope, cross_team_filter: CrossTeamFilter
    ) -> builtins.list[IntegrationRecord]:
        f = cross_team_filter
        body = {
            "team_ids": None if f.team_ids is None else builtins.list(f.team_ids),
            "exclude_team_ids": builtins.list(f.exclude_team_ids),
            "created_by_ids": None if f.created_by_ids is None else builtins.list(f.created_by_ids),
            "external_id": f.external_id,
            "where": dict(f.where),
            "where_in": {key: builtins.list(values) for key, values in f.where_in.items()},
            "where_iexact": dict(f.where_iexact),
            "has_config_key": f.has_config_key,
        }
        # The service pages by `created_at`, but the SDK orders by id and pages with `after_id`. So
        # the backend reads every page and orders the rows itself.
        rows = [_to_record(row, _WithheldSecrets()) for row in self._across_teams_pages(scope, body)]
        rows.sort(key=lambda record: record.id, reverse=f.newest_first)
        if f.after_id is not None:
            rows = [row for row in rows if (row.id < f.after_id if f.newest_first else row.id > f.after_id)]
        return builtins.list(rows if f.limit is None else rows[: f.limit])

    # Writes

    @staticmethod
    def _new_body(new: NewIntegration) -> dict[str, Any]:
        return {
            "kind": new.kind,
            "integration_id": new.external_id,
            "auth_type": effective_auth_type(new.kind, new.config),
            "config": dict(new.config),
            "sensitive_config": dict(new.sensitive_config),
            "created_by_id": new.created_by_id,
            "is_source_row": SOURCE_MARKER_CONFIG_KEY in new.config,
        }

    @staticmethod
    def _patch_body(patch: IntegrationPatch) -> dict[str, Any]:
        return {
            "config_patch": dict(patch.config_patch),
            "config_remove": builtins.list(patch.config_remove),
            "sensitive_config_patch": dict(patch.sensitive_config_patch),
            "sensitive_config_remove": builtins.list(patch.sensitive_config_remove),
            "errors": patch.errors,
        }

    def create(self, new: NewIntegration) -> IntegrationRecord:
        token = self._token("create", team_id=new.team_id, kinds=[new.kind], user_id=new.created_by_id)
        # The same key on the retry, so a create that reached the service before the connection dropped
        # returns the same row and does not raise a conflict.
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        row = self._json("POST", "", token, body=self._new_body(new), headers=headers)
        self._cache.invalidate(new.team_id, str(row["reference"]))
        return _to_record(row, dict(new.sensitive_config))

    def upsert(self, scope: RowScope, new: NewIntegration) -> tuple[IntegrationRecord, bool]:
        token = self._token("upsert", team_id=new.team_id, kinds=[new.kind], user_id=new.created_by_id)
        answer = self._json("PUT", "/upsert", token, body=self._new_body(new))
        row = answer["record"]
        self._cache.invalidate(new.team_id, str(row["reference"]))
        return _to_record(row, dict(new.sensitive_config)), bool(answer["created"])

    def _patch_row(self, scope: RowScope, team_id: int, id: int, body: Mapping[str, Any]) -> tuple[str, bool]:
        """Apply a patch body to one row of the scope. Returns the ref of the row and True when the row changed."""
        legacy_id = _lookup_id(id)
        if legacy_id is None:
            raise IntegrationNotFound(f"No integration {id!r} in {scope!r} for team {team_id}")
        ref = str(legacy_id)
        token = self._token("update", team_id=team_id, kinds=_scope_kinds(scope), refs=[ref])
        try:
            for attempt in range(1, WRITE_ATTEMPTS + 1):
                row = self._json("GET", f"/{ref}", token)
                if not _in_scope(scope, row):
                    raise IntegrationNotFound(f"No integration {id!r} in {scope!r} for team {team_id}")
                try:
                    patched = self._json(
                        "PATCH", f"/{ref}", token, body=body, headers={"If-Match": f'"{row["version"]}"'}
                    )
                except _VersionMismatch:
                    if attempt == WRITE_ATTEMPTS:
                        raise
                    continue
                return ref, patched["version"] != row["version"]
        finally:
            self._cache.invalidate(team_id, ref)
        raise AssertionError("unreachable")

    def update(self, scope: RowScope, *, team_id: int, id: int, patch: IntegrationPatch) -> IntegrationRecord:
        ref, _changed = self._patch_row(scope, team_id, id, self._patch_body(patch))
        resolved = self._resolve("resolve", team_id, [ref], use_cache=False).get(ref)
        if resolved is None:
            raise IntegrationNotFound(f"Integration {id!r} of team {team_id} was deleted after the update")
        return _to_record(resolved.record, self._secrets(resolved))

    def delete(self, scope: RowScope, *, team_id: int, id: int) -> None:
        legacy_id = _lookup_id(id)
        if legacy_id is None:
            raise IntegrationNotFound(f"No integration {id!r} in {scope!r} for team {team_id}")
        ref = str(legacy_id)
        token = self._token("delete", team_id=team_id, kinds=_scope_kinds(scope), refs=[ref])
        try:
            for attempt in range(1, WRITE_ATTEMPTS + 1):
                row = self._json("GET", f"/{ref}", token)
                if not _in_scope(scope, row):
                    raise IntegrationNotFound(f"No integration {id!r} in {scope!r} for team {team_id}")
                try:
                    self._request(
                        "DELETE",
                        f"/{ref}",
                        token,
                        headers={"If-Match": f'"{row["version"]}"'},
                        not_found_ok_on_retry=True,
                    )
                    return
                except _VersionMismatch:
                    if attempt == WRITE_ATTEMPTS:
                        raise
        finally:
            self._cache.invalidate(team_id, ref)

    def change_external_id(self, scope: RowScope, *, team_id: int, id: int, external_id: str) -> IntegrationRecord:
        raise _unsupported("change_external_id")

    def _rows_by_external_id(
        self, scope: RowScope, external_id: str
    ) -> dict[str, tuple[builtins.list[Mapping[str, Any]], bool]]:
        """For each kind, the rows of the scope with this external id, and True when they are all its rows.

        The routes by external id write every row of a kind and have no auth type filter. When the scope
        names only some auth types of a kind, the backend writes the rows of the scope one by one.
        """
        if scope.kinds is None:
            raise IntegrationServiceError("validation", "A write by external id needs an accessor with a kind")
        unscoped = RowScope(
            kinds=tuple(KindScope(kind=kind) for kind in sorted({k.kind for k in scope.kinds})),
            source_rows=scope.source_rows,
        )
        rows_by_kind: dict[str, builtins.list[Mapping[str, Any]]] = {}
        for row in self._by_external_id_pages(unscoped, external_id):
            rows_by_kind.setdefault(str(row["kind"]), []).append(row)
        return {
            kind: ([row for row in rows if _in_scope(scope, row)], all(_in_scope(scope, row) for row in rows))
            for kind, rows in rows_by_kind.items()
        }

    def update_by_external_id(self, scope: RowScope, *, external_id: str, patch: IntegrationPatch) -> int:
        body = self._patch_body(patch)
        changed = 0
        for kind, (rows, whole_kind) in self._rows_by_external_id(scope, external_id).items():
            try:
                if whole_kind:
                    token = self._token("update_by_external_id", team_id=None, kinds=[kind])
                    params = {"source_rows": scope.source_rows.value}
                    answer = self._json(
                        "PATCH", self._external_id_path(kind, external_id), token, params=params, body=body
                    )
                    changed += int(answer["updated"])
                else:
                    changed += sum(
                        self._patch_row(scope, int(row["team_id"]), row["legacy_id"], body)[1] for row in rows
                    )
            finally:
                for row in rows:
                    self._cache.invalidate(int(row["team_id"]), str(row["reference"]))
        return changed

    def delete_by_external_id(self, scope: RowScope, *, external_id: str) -> int:
        deleted = 0
        for kind, (rows, whole_kind) in self._rows_by_external_id(scope, external_id).items():
            try:
                if whole_kind:
                    token = self._token("delete_by_external_id", team_id=None, kinds=[kind])
                    params = {"source_rows": scope.source_rows.value}
                    # A repeat after a dropped connection deletes nothing and answers 0.
                    answer = self._json("DELETE", self._external_id_path(kind, external_id), token, params=params)
                    deleted += int(answer["deleted"])
                else:
                    for row in rows:
                        self.delete(scope, team_id=int(row["team_id"]), id=row["legacy_id"])
                        deleted += 1
            finally:
                for row in rows:
                    self._cache.invalidate(int(row["team_id"]), str(row["reference"]))
        return deleted

    def refresh_access_token(
        self, scope: RowScope, *, team_id: int, id: int, stale_access_token: str | None
    ) -> TokenRefresh:
        raise _unsupported("refresh_access_token")

    def count_by_external_ids(self, scope: RowScope, *, external_ids: Sequence[str]) -> dict[str, int]:
        raise _unsupported("count_by_external_ids")

    def update_where(self, scope: RowScope, row_filter: RowFilter, patch: IntegrationPatch) -> UpdatedRows:
        raise _unsupported("update_where")

    def get_repository_cache(self, scope: RowScope, *, team_id: int, id: int) -> RepositoryCache:
        raise _unsupported("get_repository_cache")

    def set_repository_cache(
        self,
        scope: RowScope,
        *,
        team_id: int,
        id: int,
        repositories: builtins.list[dict[str, object]] | None,
        updated_at: datetime,
    ) -> None:
        raise _unsupported("set_repository_cache")

    def expire_repository_cache_by_external_id(self, scope: RowScope, *, external_id: str) -> int:
        raise _unsupported("expire_repository_cache_by_external_id")
