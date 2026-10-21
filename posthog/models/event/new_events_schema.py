from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from django.conf import settings

import structlog

from posthog.models.instance_setting import get_instance_setting

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

logger = structlog.get_logger(__name__)


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


EVENTS_ROUTE_MODIFIER_KEYS = ("useNewEventsSchema", "useNewEventsCluster")


def strip_events_route(query: dict[str, Any], *, drop_empty: bool = False) -> list[dict[str, Any]]:
    """Remove the events route modifiers from a serialized query and every source it wraps.

    Returns the nodes that carry a modifiers field, outermost first. With drop_empty, a modifiers
    field left empty is removed, and its node is not returned.
    """
    nodes: list[dict[str, Any]] = []
    node: Any = query
    while isinstance(node, dict):
        if "modifiers" in node:
            modifiers = node["modifiers"]
            if isinstance(modifiers, dict):
                for key in EVENTS_ROUTE_MODIFIER_KEYS:
                    modifiers.pop(key, None)
            if drop_empty and modifiers == {}:
                node.pop("modifiers")
            else:
                nodes.append(node)
        node = node.get("source")
    return nodes


def events_route_is_explicit(team_modifiers: object, modifiers: "HogQLQueryModifiers | None") -> bool:
    """Whether the query or its project chose the events route, instead of leaving it to the rollout settings.

    A project's stored modifiers can choose the events table, but never the cluster.
    """
    if modifiers is not None and any(getattr(modifiers, key) is not None for key in EVENTS_ROUTE_MODIFIER_KEYS):
        return True
    return isinstance(team_modifiers, dict) and team_modifiers.get("useNewEventsSchema") is not None


def get_new_events_cluster_host_or_none() -> str | None:
    """The native events host, or None when it is not set or its setting cannot be read."""
    try:
        return get_new_events_cluster_host()
    except Exception:
        logger.exception("Failed to resolve the native events cluster host")
        return None


_query_route: ContextVar["HogQLQueryModifiers | None"] = ContextVar("new_events_query_route", default=None)


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
    if reason := native_events_cluster_ineligibility(team_id):
        raise ExposedHogQLError(reason)
    return True


def native_events_async_enabled() -> bool:
    return get_instance_setting("CLICKHOUSE_NATIVE_EVENTS_ASYNC") is True


def native_events_cluster_ineligibility(team_id: int | None) -> str | None:
    if not get_new_events_cluster_host():
        return "The native events cluster host is not configured."
    allowed = get_instance_setting("CLICKHOUSE_NATIVE_EVENTS_TEAMS")
    if not isinstance(allowed, list) or any(type(value) is not int for value in allowed) or team_id not in allowed:
        return "This project is not enabled for native events cluster queries."
    return None


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
