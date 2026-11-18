from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from django.conf import settings

import posthoganalytics

from posthog.cloud_utils import is_cloud
from posthog.models.instance_setting import get_instance_setting

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.models.team import Team


# TODO: Remove the route helpers in this block after the events cluster migration is complete.
EVENTS_ROUTE_MODIFIER_KEYS = ("useNewEventsSchema",)
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
    nodes[-1]["modifiers"] = {**(nodes[-1]["modifiers"] or {}), "useNewEventsSchema": modifiers.useNewEventsSchema}
    return nodes[0]


def events_route_cache_modifiers(modifiers: dict[str, Any], *, reads_events: bool) -> dict[str, Any]:
    """The resolved modifiers as they key the cache.

    A legacy-table query must keep the cache key it had before the native route existed, so the route values it
    resolves to are left out. A query that reads no events table is never keyed by one.
    """
    modifiers = dict(modifiers)
    if modifiers.get("useNewEventsSchema") is False or not reads_events:
        modifiers.pop("useNewEventsSchema", None)
    return modifiers


def get_events_route() -> "HogQLQueryModifiers | None":
    """The events table of the query run in progress, or None outside a query run."""
    return _query_route.get()


@contextmanager
def events_route_scope(modifiers: "HogQLQueryModifiers") -> Iterator[None]:
    # Lookups inside a run, such as an all-time range's earliest event, must read the query's events table.
    from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415

    token = _query_route.set(HogQLQueryModifiers(useNewEventsSchema=modifiers.useNewEventsSchema))
    try:
        yield
    finally:
        _query_route.reset(token)


# A staff person's browser sends this cookie to read events_json on every request, impersonated sessions included.
NEW_EVENTS_SCHEMA_COOKIE = "ph_new_events_schema"
# One browser tab sends this header, "1" for events_json and "0" for the legacy table, and it wins over the cookie,
# so two tabs of one browser can show the two tables side by side.
NEW_EVENTS_SCHEMA_HEADER = "X-PostHog-New-Events-Schema"
_person_switch: ContextVar[bool | None] = ContextVar("new_events_schema_person_switch", default=None)


@contextmanager
def new_events_schema_for_request(enabled: bool = True) -> Iterator[None]:
    """Every events read inside the block targets the chosen table, unless its query's modifier says otherwise."""
    token = _person_switch.set(enabled)
    try:
        yield
    finally:
        _person_switch.reset(token)


# Both flags match by the project group. Staff set the share of projects that read events_json, and the projects
# to keep on the legacy table, in the rollout flag's release conditions, which can filter on the group property id.
EVENTS_TABLE_ROLLOUT_FLAG = "new-events-table-rollout"
# The browser also evaluates this flag, to show the setting, and it hashes a different project key. Open it to
# every project or to projects listed by id, never to a percentage, or the browser and the API disagree.
EVENTS_TABLE_SELF_SERVE_FLAG = "new-events-table-self-serve"


def _flag_enabled_for_project(flag: str, team_id: int) -> bool:
    # The flag is evaluated in this process and keyed on the project id, so the query path makes no network call.
    if not is_cloud():
        return False
    return bool(
        posthoganalytics.feature_enabled(
            flag,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def project_moved_to_new_events_table(team_id: int | None) -> bool:
    """Whether staff or the rollout moved the project to events_json. Every reader of the events table follows it.

    Callers that pass no project, such as usage reports, follow CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA alone.
    """
    if get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA"):
        return True
    if team_id is None:
        return False
    return team_id in _allowlisted_team_ids() or _flag_enabled_for_project(EVENTS_TABLE_ROLLOUT_FLAG, team_id)


def project_opted_in_to_new_events_table(team: "Team") -> bool:
    """Whether the project chose events_json early, in project settings.

    The choice is the useNewEventsSchema key of the project's stored modifiers, so it reaches HogQL queries and not
    readers that write their own SQL. Only true counts: a project cannot choose the legacy table. It counts only
    while the new-events-table-self-serve feature flag is on for the project.
    """
    stored = team.modifiers if isinstance(team.modifiers, dict) else {}
    return stored.get("useNewEventsSchema") is True and _flag_enabled_for_project(EVENTS_TABLE_SELF_SERVE_FLAG, team.pk)


def events_table_override(modifiers: "HogQLQueryModifiers | None") -> bool | None:
    """The table chosen for one query or one staff browser, or None when neither chose one."""
    if modifiers is not None and modifiers.useNewEventsSchema is not None:
        return modifiers.useNewEventsSchema
    route = get_events_route()
    if route is not None and route.useNewEventsSchema is not None:
        return route.useNewEventsSchema
    return _person_switch.get()


def use_new_events_schema(team_id: int | None = None, modifiers: "HogQLQueryModifiers | None" = None) -> bool:
    """Whether an events read uses the new events table (events_json) instead of the old one.

    Four things are checked in order. The first one that is set decides, and the rest are ignored.

    1. The query's own useNewEventsSchema modifier.
    2. If this read happens while another query is running, that query's table.
    3. A staff person's tab header or browser cookie (new_events_schema_for_request).
    4. The project.

    The first three are overrides for one query or one staff browser. Each can choose either table.

    PostHog moves a project to the new table when any of these is true. None of them outranks another, and none of
    them can choose the old table:

    - The instance setting CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA is on. It moves every project.
    - The instance setting CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS lists the project.
    - The new-events-table-rollout feature flag includes the project.

    To hold one project on the old table, exclude it in the flag and keep it off the list. Once
    CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA is on, no project can be held back. A changed setting or flag takes up
    to a couple of minutes to reach every worker.

    A project can also move itself early (project_opted_in_to_new_events_table). create_default_modifiers_for_team
    turns that into the query's modifier when none of the three overrides is set, so it moves the project's HogQL
    queries and nothing else.

    Inside a query, use HogQLContext.uses_new_events_schema(). It decides once, so a query cannot mix the two
    tables.
    """
    override = events_table_override(modifiers)
    if override is not None:
        return override
    if settings.TEST and settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        return True
    return project_moved_to_new_events_table(team_id)


def events_read_table(use_new_events_schema: bool) -> str:
    """The distributed events table raw (non-HogQL) SQL should read from.

    Callers must resolve the gate once per query (via HogQLContext.uses_new_events_schema() when a
    context exists) and use that same value for both the table name and any property SQL fragments,
    so one query never mixes schemas.
    """
    # Deferred: event.sql pulls ClickHouse DDL machinery; this module is imported at django.setup().
    from posthog.models.event.sql import DISTRIBUTED_EVENTS_JSON_TABLE  # noqa: PLC0415

    return DISTRIBUTED_EVENTS_JSON_TABLE if use_new_events_schema else "events"


# The native table stores a dotted key `a.b` under the path `a%2Eb` (EVENTS_JSON_INSERT_SETTINGS), and ClickHouse
# prints the dot again only for a query that sets the first setting. The second keeps a `/` inside an object or
# array value unescaped, as the legacy text column returns it. The ClickHouse printer sets both on every HogQL
# query that reads the native table, so raw SQL that embeds or re-runs a printed query must send them itself.
EVENTS_JSON_READ_SETTINGS: dict[str, int] = {
    "json_type_escape_dots_in_keys": 1,
    "output_format_json_escape_forward_slashes": 0,
}


def events_read_settings(use_new_events_schema: bool) -> dict[str, int]:
    """The ClickHouse settings raw (non-HogQL) SQL must send when it reads the native events table.

    Resolve the gate once per query, as `events_read_table` asks, so the settings match the table the SQL was
    printed against.
    """
    return dict(EVENTS_JSON_READ_SETTINGS) if use_new_events_schema else {}


def _allowlisted_team_ids() -> set[int]:
    raw = str(get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS") or "")
    return {int(part) for part in raw.split(",") if part.strip()}
