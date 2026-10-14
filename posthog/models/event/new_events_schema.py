from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from django.conf import settings

from posthog.models.instance_setting import get_instance_setting

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers


# TODO: Remove the per-query rollout option after the events cluster migration is complete.
_query_host: ContextVar[list[str | None] | None] = ContextVar("new_events_cluster_host", default=None)


def get_new_events_cluster_host() -> str | None:
    snapshot = _query_host.get()
    if snapshot:
        return snapshot[0]
    value = get_instance_setting("CLICKHOUSE_NATIVE_EVENTS_HOST")
    host = value if isinstance(value, str) and value else None
    if snapshot is not None:
        snapshot.append(host)
    return host


@contextmanager
def new_events_cluster_host_scope() -> Iterator[None]:
    # Pin cache lookup and execution to one host even if settings change mid-request.
    if _query_host.get() is not None:
        yield
        return
    token = _query_host.set([])
    try:
        yield
    finally:
        _query_host.reset(token)


def use_new_events_cluster(team_id: int | None, modifiers: "HogQLQueryModifiers | None") -> bool:
    from posthog.hogql.errors import ExposedHogQLError  # noqa: PLC0415

    if modifiers is None or not modifiers.useNewEventsCluster:
        return False
    if not get_new_events_cluster_host():
        raise ExposedHogQLError("The native events cluster host is not configured.")
    allowed = get_instance_setting("CLICKHOUSE_NATIVE_EVENTS_TEAMS")
    if not isinstance(allowed, list) or any(type(value) is not int for value in allowed) or team_id not in allowed:
        raise ExposedHogQLError("This project is not enabled for native events cluster queries.")
    return True


def use_new_events_schema(team_id: int | None = None, modifiers: "HogQLQueryModifiers | None" = None) -> bool:
    """Whether HogQL reads should target the native-JSON events tables.

    A query's `useNewEventsSchema` modifier decides when it is set, so one query can be run against either table.
    Otherwise the instance setting flips it globally at runtime, and the *_TEAMS instance setting enables it
    for individual teams first (both cached for up to 60s per worker). Code running inside a query
    should prefer HogQLContext.uses_new_events_schema(), which resolves this once so a mid-query
    flip can't mix schemas.
    """
    if modifiers is not None and modifiers.useNewEventsSchema is not None:
        return modifiers.useNewEventsSchema
    if settings.TEST and settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        return True
    if get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA"):
        return True
    return team_id is not None and team_id in _allowlisted_team_ids()


def events_read_table(use_new_events_schema: bool) -> str:
    """The distributed events table raw (non-HogQL) SQL should read from.

    Callers must resolve the gate once per query (via HogQLContext.uses_new_events_schema() when a
    context exists) and use that same value for both the table name and any property SQL fragments,
    so one query never mixes schemas.
    """
    # Deferred: event.sql pulls ClickHouse DDL machinery; this module is imported at django.setup().
    from posthog.models.event.sql import DISTRIBUTED_EVENTS_JSON_TABLE  # noqa: PLC0415

    return DISTRIBUTED_EVENTS_JSON_TABLE if use_new_events_schema else "events"


def _allowlisted_team_ids() -> set[int]:
    raw = str(get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS") or "")
    return {int(part) for part in raw.split(",") if part.strip()}
