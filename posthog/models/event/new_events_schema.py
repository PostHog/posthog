from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from django.conf import settings

from posthog.models.instance_setting import get_instance_setting

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers


# TODO: Remove the per-query rollout option, and the route helpers in this block, after the events cluster
# migration is complete.
EVENTS_ROUTE_MODIFIER_KEYS = ("useNewEventsSchema", "useNewEventsCluster")
_query_host: ContextVar[list[str | None] | None] = ContextVar("new_events_cluster_host", default=None)
_query_route: ContextVar["HogQLQueryModifiers | None"] = ContextVar("new_events_query_route", default=None)


def _copy_source_chain(query: dict[str, Any]) -> list[dict[str, Any]]:
    """Copies of the query and every source it wraps, outermost first. Other nested values stay shared."""
    nodes = [dict(query)]
    while isinstance(nodes[-1].get("source"), dict):
        nodes[-1]["source"] = dict(nodes[-1]["source"])
        nodes.append(nodes[-1]["source"])
    return nodes


def strip_events_route_modifiers(query: dict[str, Any], *, drop_empty: bool = False) -> dict[str, Any]:
    """The serialized query without the requested events route.

    The resolved route keys the cache, so requested values that resolve to the same route must not split the
    cache key. With drop_empty, a modifiers field left empty is removed.
    """
    nodes = _copy_source_chain(query)
    for node in nodes:
        modifiers = node.get("modifiers")
        if isinstance(modifiers, dict):
            node["modifiers"] = {
                key: value for key, value in modifiers.items() if key not in EVENTS_ROUTE_MODIFIER_KEYS
            }
            if drop_empty and not node["modifiers"]:
                node.pop("modifiers")
    return nodes[0]


def with_pinned_events_route(query: dict[str, Any], modifiers: "HogQLQueryModifiers") -> dict[str, Any]:
    """The serialized query with the resolved events route in place of the requested one.

    A worker rebuilds the runner from this payload. The resolved route goes into the innermost source, which
    every worker reads, so the worker reads the same table and writes the cache key the request reads.
    """
    if "modifiers" not in _copy_source_chain(query)[-1]:
        return query
    nodes = _copy_source_chain(strip_events_route_modifiers(query))
    route: dict[str, Any] = {"useNewEventsSchema": modifiers.useNewEventsSchema}
    if modifiers.useNewEventsCluster is not None:
        route["useNewEventsCluster"] = modifiers.useNewEventsCluster
    nodes[-1]["modifiers"] = {**(nodes[-1]["modifiers"] or {}), **route}
    return nodes[0]


def events_route_cache_modifiers(modifiers: dict[str, Any], *, reads_events: bool) -> dict[str, Any]:
    """The resolved modifiers as they key the cache.

    A legacy-table query must keep the cache key it had before the native route existed, so the route values it
    resolves to are left out. A query that reads no events table is never keyed by one.
    """
    modifiers = dict(modifiers)
    if modifiers.get("useNewEventsSchema") is False or not reads_events:
        modifiers.pop("useNewEventsSchema", None)
    if not modifiers.get("useNewEventsCluster"):
        modifiers.pop("useNewEventsCluster", None)
    return modifiers


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


def get_events_route() -> "HogQLQueryModifiers | None":
    """The events cluster and table of the query run in progress, or None outside a query run."""
    return _query_route.get()


@contextmanager
def events_route_scope(modifiers: "HogQLQueryModifiers") -> Iterator[None]:
    # Lookups inside a run, such as an all-time range's earliest event, must read the query's cluster and table.
    from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415

    token = _query_route.set(
        HogQLQueryModifiers(
            useNewEventsCluster=modifiers.useNewEventsCluster, useNewEventsSchema=modifiers.useNewEventsSchema
        )
    )
    try:
        yield
    finally:
        _query_route.reset(token)


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
