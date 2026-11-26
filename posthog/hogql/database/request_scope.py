import threading
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from typing import TYPE_CHECKING, Any, Optional

from posthog.hogql.database.sources_cache import modifiers_fingerprint
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.hogql.database.database import Database

    from posthog.models.team.team import Team

    from products.access_control.backend.facade.user_access_control import UserAccessControl


@frozen
class SharedDatabaseKey:
    """Every create_for input that shapes the catalog. Timings and the trigger label only observe the build."""

    team_id: int
    user_kind: str
    user_id: Optional[int]
    has_user_access_control: bool
    access_decision: Optional[str]
    warehouse_access_control_enforced: bool
    modifiers_fingerprint: str
    connection_id: Optional[str]
    bypass_warehouse_access_control: bool
    build_postgres_foreign_keys: bool
    use_cached_sources: bool
    allowed_system_tables: Optional[frozenset[str]]
    schema_table_names: Optional[frozenset[str]]
    include_flag_evaluations_table: Optional[bool]


class SharedDatabases:
    """Databases built once and handed to every query in one scope, such as one dashboard query batch.

    Lives only as long as its owner, so a warehouse or saved-query change is seen by the next request.
    A Database is built to be read by concurrent query threads (its deferred builds take their own locks). Queries
    that register a table at resolution time write to its root, so a stored catalog's root is copy-on-write.
    Beyond that, one thread builds each key while the others wait.

    `enabled` is asked once, at the first build, so a caller on an event loop can pass a check that reads the database.
    Each stored catalog can be large, so past max_databases distinct keys a build is handed out but not kept.
    A catalog holds the access decision it was built with, so it is rebuilt after max_age_seconds: a revoked
    grant reaches the rest of a long batch within that window instead of at the stream's end."""

    def __init__(
        self, max_databases: int = 4, max_age_seconds: float = 30.0, enabled: Callable[[], bool] = lambda: True
    ) -> None:
        self._is_enabled = enabled
        self._enabled: Optional[bool] = None
        self._max_databases = max_databases
        self._max_age_seconds = max_age_seconds
        self._lock = threading.Lock()
        self._databases: dict[SharedDatabaseKey, tuple[Database, float]] = {}
        self._build_locks: dict[SharedDatabaseKey, threading.Lock] = {}

    def _fresh(self, key: SharedDatabaseKey) -> Optional["Database"]:
        entry = self._databases.get(key)
        if entry is None or monotonic() - entry[1] > self._max_age_seconds:
            return None
        return entry[0]

    def get_or_build(self, key: SharedDatabaseKey, build: Callable[[], "Database"]) -> "Database":
        if self._enabled is None:
            self._enabled = self._is_enabled()
        if not self._enabled:
            return build()
        with self._lock:
            database = self._fresh(key)
            if database is not None:
                return database
            if key not in self._build_locks and len(self._build_locks) >= self._max_databases:
                build_lock = None
            else:
                build_lock = self._build_locks.setdefault(key, threading.Lock())
        if build_lock is None:
            return build()
        with build_lock:
            with self._lock:
                database = self._fresh(key)
            if database is not None:
                return database
            database = build()
            database.tables.copy_children_on_write()
            with self._lock:
                self._databases[key] = (database, monotonic())
            return database

    def clear(self) -> None:
        with self._lock:
            self._databases.clear()
            self._build_locks.clear()


_shared_databases: ContextVar[Optional[SharedDatabases]] = ContextVar("hogql_shared_databases", default=None)


@contextmanager
def sharing_databases(databases: SharedDatabases) -> Iterator[None]:
    token = _shared_databases.set(databases)
    try:
        yield
    finally:
        _shared_databases.reset(token)


@contextmanager
def building_alone() -> Iterator[None]:
    """Build databases outside any sharing scope, for a caller that changes the catalog it gets."""
    token = _shared_databases.set(None)
    try:
        yield
    finally:
        _shared_databases.reset(token)


def current_shared_databases() -> Optional[SharedDatabases]:
    return _shared_databases.get()


def shared_database_key(
    *,
    team: Optional["Team"],
    user: Any,
    user_access_control: Optional["UserAccessControl"],
    warehouse_access_control_enforced: bool,
    modifiers: Optional["HogQLQueryModifiers"],
    connection_id: Optional[str],
    bypass_warehouse_access_control: bool,
    build_postgres_foreign_keys: bool,
    use_cached_sources: bool,
    allowed_system_tables: Optional[Collection[str]],
    schema_table_names: Optional[set[str]],
    include_flag_evaluations_table: Optional[bool],
) -> Optional[SharedDatabaseKey]:
    """The key to share this build under, or None when it must be built on its own."""
    from posthog.models.user import User  # noqa: PLC0415

    if team is None:
        return None
    if user is not None and not isinstance(user, User):
        return None
    if user_access_control is not None:
        # Runners each preload their own instance. Instances for the same user and team resolve the same
        # access, so they share. Any other instance is someone else's scope and builds alone.
        uac_user = getattr(user_access_control, "_user", None)
        uac_team = getattr(user_access_control, "_team", None)
        if user is None or uac_user is None or uac_user.pk != user.pk or uac_team is None or uac_team.pk != team.pk:
            return None
    return SharedDatabaseKey(
        team_id=team.pk,
        user_kind="user" if user is not None else "none",
        user_id=user.pk if user is not None else None,
        has_user_access_control=user_access_control is not None,
        access_decision=user_access_control.read_access_fingerprint if user_access_control is not None else None,
        warehouse_access_control_enforced=warehouse_access_control_enforced,
        modifiers_fingerprint=modifiers_fingerprint(create_default_modifiers_for_team(team, modifiers)),
        connection_id=connection_id,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
        build_postgres_foreign_keys=build_postgres_foreign_keys,
        use_cached_sources=use_cached_sources,
        allowed_system_tables=frozenset(allowed_system_tables) if allowed_system_tables is not None else None,
        schema_table_names=frozenset(schema_table_names) if schema_table_names is not None else None,
        include_flag_evaluations_table=include_flag_evaluations_table,
    )
