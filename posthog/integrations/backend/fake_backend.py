"""An in-memory `StorageBackend` for tests. It returns `FrozenIntegrationRecord`s.

`posthog/integrations/test/test_backends.py` runs the same accessor tests against this backend and
`DjangoBackend`, so the two keep the same behaviour. A change to one backend needs the same change
to the other.
"""

import copy
import builtins
import itertools
import threading
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from django.utils import timezone

from posthog.integrations.backend.patching import changed_fields
from posthog.integrations.backend.protocol import NewIntegration, RowFilter, RowScope, SourceRows, TokenRefresh
from posthog.integrations.contracts import (
    SOURCE_MARKER_CONFIG_KEY,
    ConfigValue,
    CrossTeamFilter,
    FrozenIntegrationRecord,
    IntegrationConflict,
    IntegrationNotFound,
    IntegrationPatch,
    IntegrationRecord,
    RepositoryCache,
    UpdatedRows,
)
from posthog.integrations.observability import TokenRefreshResult
from posthog.integrations.references import IntegrationReference
from posthog.models.integration.auth_types import effective_auth_type
from posthog.models.integration.model import Integration
from posthog.models.integration.oauth import OauthIntegration

# Returns the patch that stores the new tokens of a row. The fake calls no provider.
TokenRefresher = Callable[[IntegrationRecord], IntegrationPatch]


def no_token_refresher(record: IntegrationRecord) -> IntegrationPatch:
    raise NotImplementedError("Pass token_refresher to FakeBackend to refresh access tokens")


def _same_value(stored: object, value: ConfigValue) -> bool:
    # The same comparison as a `jsonb` equality in Postgres: a bool is never a number, and an int
    # equals a float of the same value.
    if isinstance(stored, bool) or isinstance(value, bool):
        return isinstance(stored, bool) and isinstance(value, bool) and stored == value
    if isinstance(stored, int | float) and isinstance(value, int | float):
        return stored == value
    return type(stored) is type(value) and stored == value


_MISSING = object()


def _config_value(config: Mapping[str, object], path: str) -> object:
    value: object = config
    for key in path.split("."):
        if not isinstance(value, Mapping) or key not in value:
            return _MISSING
        value = value[key]
    return value


def _matches_cross_team(cross_team_filter: CrossTeamFilter, record: FrozenIntegrationRecord) -> bool:
    f = cross_team_filter
    if f.team_ids is not None and record.team_id not in f.team_ids:
        return False
    if record.team_id in f.exclude_team_ids:
        return False
    if f.created_by_ids is not None and record.created_by_id not in f.created_by_ids:
        return False
    if f.external_id is not None and record.integration_id != f.external_id:
        return False
    if f.after_id is not None and (record.id >= f.after_id if f.newest_first else record.id <= f.after_id):
        return False
    if f.has_config_key is not None and f.has_config_key not in record.config:
        return False
    config = record.config
    if not all(key in config and _same_value(config[key], value) for key, value in f.where.items()):
        return False
    if not all(
        key in config and any(_same_value(config[key], value) for value in values) for key, values in f.where_in.items()
    ):
        return False
    # Postgres compares `UPPER(text)` for `iexact`.
    return all(
        isinstance(stored := _config_value(config, path), str) and stored.upper() == text.upper()
        for path, text in f.where_iexact.items()
    )


def _lookup_id(value: object) -> int | None:
    # Django converts an id with `int()` and finds no row when that fails.
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


def _as_stored_secrets(value: object) -> object:
    # `EncryptedJSONField` stores every value but None as an encrypted string, so it reads back as a string.
    if isinstance(value, Mapping):
        return {key: _as_stored_secrets(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_stored_secrets(item) for item in value]
    return None if value is None else str(value)


def _display_name(kind: str, external_id: str | None, config: Mapping[str, object]) -> str:
    # An unsaved model instance runs the same display name rules as `DjangoBackend`, with no query.
    return Integration(kind=kind, integration_id=external_id, config=dict(config)).display_name


class FakeBackend:
    """The rows in a dict. Safe to share between threads."""

    def __init__(self, *, token_refresher: TokenRefresher = no_token_refresher) -> None:
        self._rows: dict[int, FrozenIntegrationRecord] = {}
        self._ids = itertools.count(1)
        self._lock = threading.RLock()
        self._token_refresher = token_refresher
        self._last_created_at: datetime | None = None
        # The repository cache columns of a row, apart from the record, like the deferred columns of the model.
        self._repository_caches: dict[int, RepositoryCache] = {}

    def seed(
        self,
        *,
        team_id: int,
        kind: str,
        external_id: str | None,
        config: Mapping[str, object] | None = None,
        sensitive_config: Mapping[str, object] | None = None,
        errors: str = "",
        created_by_id: int | None = None,
    ) -> FrozenIntegrationRecord:
        """Store a row as it is, with no SDK rule applied. For test setup, like a raw model create."""
        with self._lock:
            record_id = next(self._ids)
            config = copy.deepcopy(dict(config or {}))
            record = FrozenIntegrationRecord(
                id=record_id,
                reference=str(IntegrationReference.from_legacy_id(record_id)),
                team_id=team_id,
                kind=kind,
                integration_id=external_id,
                config=config,
                sensitive_config=_as_stored_secrets(sensitive_config or {}),  # type: ignore[arg-type]
                errors=errors,
                created_at=self._next_created_at(),
                created_by_id=created_by_id,
                auth_type=effective_auth_type(kind, config),
                display_name=_display_name(kind, external_id, config),
            )
            self._rows[record_id] = record
            return self._copy(record)

    def _next_created_at(self) -> datetime:
        # Strictly increasing, so the order of the rows does not depend on the clock resolution.
        now = timezone.now()
        if self._last_created_at is not None and now <= self._last_created_at:
            now = self._last_created_at + timedelta(microseconds=1)
        self._last_created_at = now
        return now

    @staticmethod
    def _copy(record: FrozenIntegrationRecord) -> FrozenIntegrationRecord:
        # A caller that changes a returned dict must not change the stored row. Like Django, a secret
        # field that cannot be decrypted is a raw string, not a dict.
        secrets = record.sensitive_config
        return replace(
            record,
            config=copy.deepcopy(dict(record.config)),
            sensitive_config=copy.deepcopy(dict(secrets) if isinstance(secrets, Mapping) else secrets),
        )

    @staticmethod
    def _in_scope(scope: RowScope, record: FrozenIntegrationRecord) -> bool:
        is_source_row = SOURCE_MARKER_CONFIG_KEY in record.config
        if scope.source_rows == SourceRows.EXCLUDE and is_source_row:
            return False
        if scope.source_rows == SourceRows.ONLY and not is_source_row:
            return False
        if scope.kinds is None:
            return True
        for kind in scope.kinds:
            if kind.kind == record.kind:
                return kind.auth_types is None or record.auth_type in {auth_type.value for auth_type in kind.auth_types}
        return False

    @staticmethod
    def _matches(row_filter: RowFilter, record: FrozenIntegrationRecord) -> bool:
        if row_filter.team_id is not None and record.team_id != row_filter.team_id:
            return False
        if row_filter.team_ids is not None and record.team_id not in row_filter.team_ids:
            return False
        if row_filter.external_id is not None and record.integration_id != row_filter.external_id:
            return False
        return all(
            key in record.config and _same_value(record.config[key], value) for key, value in row_filter.where.items()
        )

    def _scoped(self, scope: RowScope) -> Iterator[FrozenIntegrationRecord]:
        return (record for record in self._rows.values() if self._in_scope(scope, record))

    def _selected(self, scope: RowScope, row_filter: RowFilter) -> builtins.list[FrozenIntegrationRecord]:
        with self._lock:
            rows = [record for record in self._scoped(scope) if self._matches(row_filter, record)]
        return sorted(rows, key=lambda record: (record.created_at, record.id))

    def _stored(self, id: object) -> FrozenIntegrationRecord | None:
        key = _lookup_id(id)
        return None if key is None else self._rows.get(key)

    def _row(self, scope: RowScope, team_id: int, id: int) -> FrozenIntegrationRecord:
        record = self._stored(id)
        if record is None or record.team_id != team_id or not self._in_scope(scope, record):
            raise IntegrationNotFound(f"No integration {id!r} in {scope!r} for team {team_id}")
        return record

    def _store(self, record: FrozenIntegrationRecord, changed: Mapping[str, object]) -> FrozenIntegrationRecord:
        if "sensitive_config" in changed:
            changed = {**changed, "sensitive_config": _as_stored_secrets(changed["sensitive_config"])}
        updated = replace(record, **changed)  # type: ignore[arg-type]
        if "config" in changed:
            updated = replace(
                updated,
                auth_type=effective_auth_type(updated.kind, updated.config),
                display_name=_display_name(updated.kind, updated.integration_id, updated.config),
            )
        self._rows[record.id] = updated
        return updated

    def get(self, scope: RowScope, *, team_id: int, id: int) -> IntegrationRecord:
        with self._lock:
            return self._copy(self._row(scope, team_id, id))

    def get_many(self, scope: RowScope, *, team_id: int, ids: Sequence[int]) -> dict[int, IntegrationRecord]:
        # Like Django, an id that `int()` cannot convert raises.
        wanted = {int(id) for id in ids}
        return {
            record.id: record for record in self._selected(scope, RowFilter(team_id=team_id)) if record.id in wanted
        }

    def find(self, scope: RowScope, row_filter: RowFilter) -> IntegrationRecord | None:
        rows = self._selected(scope, row_filter)
        return self._copy(rows[0]) if rows else None

    def list(
        self, scope: RowScope, row_filter: RowFilter, *, newest_first: bool = False
    ) -> builtins.list[IntegrationRecord]:
        rows = self._selected(scope, row_filter)
        return [self._copy(record) for record in (reversed(rows) if newest_first else rows)]

    def exists(self, scope: RowScope, row_filter: RowFilter) -> bool:
        return bool(self._selected(scope, row_filter))

    def count(self, scope: RowScope, row_filter: RowFilter) -> int:
        return len(self._selected(scope, row_filter))

    def count_by_external_ids(self, scope: RowScope, *, external_ids: Sequence[str]) -> dict[str, int]:
        wanted = set(external_ids)
        with self._lock:
            counts = Counter(record.integration_id for record in self._scoped(scope) if record.integration_id in wanted)
        return {external_id: count for external_id, count in counts.items() if external_id is not None}

    def get_by_external_id(self, scope: RowScope, *, external_id: str, id: int) -> IntegrationRecord:
        with self._lock:
            record = self._stored(id)
            if record is None or record.integration_id != external_id or not self._in_scope(scope, record):
                raise IntegrationNotFound(f"No integration {id!r} with external id {external_id!r} in {scope!r}")
            return self._copy(record)

    def list_across_teams(
        self, scope: RowScope, cross_team_filter: CrossTeamFilter
    ) -> builtins.list[IntegrationRecord]:
        with self._lock:
            rows = [record for record in self._scoped(scope) if _matches_cross_team(cross_team_filter, record)]
        rows.sort(key=lambda record: record.id, reverse=cross_team_filter.newest_first)
        if cross_team_filter.limit is not None:
            rows = rows[: cross_team_filter.limit]
        return [self._copy(record) for record in rows]

    def _with_key(self, new: NewIntegration) -> FrozenIntegrationRecord | None:
        # Postgres treats NULLs as distinct in a unique key, so rows without an external id never clash.
        if new.external_id is None:
            return None
        for record in self._rows.values():
            if (record.team_id, record.kind, record.integration_id) == (new.team_id, new.kind, new.external_id):
                return record
        return None

    def create(self, new: NewIntegration) -> IntegrationRecord:
        with self._lock:
            if self._with_key(new) is not None:
                raise IntegrationConflict(
                    f"Team {new.team_id} already has a {new.kind!r} integration with external id {new.external_id!r}"
                )
            return self.seed(
                team_id=new.team_id,
                kind=new.kind,
                external_id=new.external_id,
                config=new.config,
                sensitive_config=new.sensitive_config,
                created_by_id=new.created_by_id,
            )

    def upsert(self, scope: RowScope, new: NewIntegration) -> tuple[IntegrationRecord, bool]:
        with self._lock:
            existing = self._with_key(new)
            if existing is None:
                return self.create(new), True
            if not self._in_scope(scope, existing):
                raise IntegrationConflict(
                    f"Integration {existing.id} with external id {new.external_id!r} is not in {scope!r}"
                )
            changed: dict[str, object] = {
                "config": copy.deepcopy(dict(new.config)),
                "sensitive_config": _as_stored_secrets(new.sensitive_config),
                "errors": "",
            }
            if new.created_by_id is not None:
                changed["created_by_id"] = new.created_by_id
            return self._copy(self._store(existing, changed)), False

    def _patched(self, record: FrozenIntegrationRecord, patch: IntegrationPatch) -> FrozenIntegrationRecord | None:
        changed = changed_fields(
            config=record.config, sensitive_config=record.sensitive_config, errors=record.errors, patch=patch
        )
        return self._store(record, copy.deepcopy(changed)) if changed else None

    def update(self, scope: RowScope, *, team_id: int, id: int, patch: IntegrationPatch) -> IntegrationRecord:
        with self._lock:
            record = self._row(scope, team_id, id)
            return self._copy(self._patched(record, patch) or record)

    def delete(self, scope: RowScope, *, team_id: int, id: int) -> None:
        with self._lock:
            record_id = self._row(scope, team_id, id).id
            del self._rows[record_id]
            self._repository_caches.pop(record_id, None)

    def change_external_id(self, scope: RowScope, *, team_id: int, id: int, external_id: str) -> IntegrationRecord:
        with self._lock:
            record = self._row(scope, team_id, id)
            if record.integration_id == external_id:
                return self._copy(record)
            if any(
                (other.team_id, other.kind, other.integration_id) == (record.team_id, record.kind, external_id)
                for other in self._rows.values()
            ):
                raise IntegrationConflict(
                    f"Team {team_id} already has a {record.kind!r} integration with external id {external_id!r}"
                )
            moved = replace(
                record,
                integration_id=external_id,
                display_name=_display_name(record.kind, external_id, record.config),
            )
            self._rows[record.id] = moved
            return self._copy(moved)

    def _by_external_id(self, scope: RowScope, external_id: str) -> Iterable[FrozenIntegrationRecord]:
        return self._selected(scope, RowFilter(external_id=external_id))

    def update_by_external_id(self, scope: RowScope, *, external_id: str, patch: IntegrationPatch) -> int:
        with self._lock:
            return sum(
                1 for record in self._by_external_id(scope, external_id) if self._patched(record, patch) is not None
            )

    def delete_by_external_id(self, scope: RowScope, *, external_id: str) -> int:
        with self._lock:
            rows = builtins.list(self._by_external_id(scope, external_id))
            for record in rows:
                del self._rows[record.id]
                self._repository_caches.pop(record.id, None)
            return len(rows)

    def refresh_access_token(
        self, scope: RowScope, *, team_id: int, id: int, stale_access_token: str | None
    ) -> TokenRefresh:
        # The lock covers the provider call, like the row lock of `DjangoBackend`.
        with self._lock:
            record = self._row(scope, team_id, id)
            stale = stale_access_token is not None and (record.access_token or "") == stale_access_token
            expired = OauthIntegration(record).access_token_expired()
            if not (stale or expired):
                return TokenRefresh(record=self._copy(record), result="fresh")
            refreshed = self._patched(record, self._token_refresher(self._copy(record))) or record
            result: TokenRefreshResult = "error" if refreshed.errors else "refreshed" if expired else "stale_token"
            return TokenRefresh(record=self._copy(refreshed), result=result)

    def update_where(self, scope: RowScope, row_filter: RowFilter, patch: IntegrationPatch) -> UpdatedRows:
        with self._lock:
            records: builtins.list[IntegrationRecord] = []
            changed: set[int] = set()
            for record in self._selected(scope, row_filter):
                patched = self._patched(record, patch)
                if patched is not None:
                    changed.add(record.id)
                records.append(self._copy(patched or record))
            return UpdatedRows(records=tuple(records), changed_ids=frozenset(changed))

    def get_repository_cache(self, scope: RowScope, *, team_id: int, id: int) -> RepositoryCache:
        with self._lock:
            record_id = self._row(scope, team_id, id).id
            return copy.deepcopy(
                self._repository_caches.get(record_id, RepositoryCache(repositories=[], updated_at=None))
            )

    def set_repository_cache(
        self,
        scope: RowScope,
        *,
        team_id: int,
        id: int,
        repositories: builtins.list[dict[str, object]] | None,
        updated_at: datetime,
    ) -> None:
        with self._lock:
            record_id = self._row(scope, team_id, id).id
            stored = self._repository_caches.get(record_id, RepositoryCache(repositories=[], updated_at=None))
            self._repository_caches[record_id] = RepositoryCache(
                repositories=stored.repositories if repositories is None else copy.deepcopy(repositories),
                updated_at=updated_at,
            )

    def expire_repository_cache_by_external_id(self, scope: RowScope, *, external_id: str) -> int:
        with self._lock:
            rows = builtins.list(self._by_external_id(scope, external_id))
            for record in rows:
                stored = self._repository_caches.get(record.id, RepositoryCache(repositories=[], updated_at=None))
                self._repository_caches[record.id] = replace(stored, updated_at=None)
            return len(rows)
