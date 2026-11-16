import time
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
_person_switch: ContextVar[bool] = ContextVar("new_events_schema_person_switch", default=False)


@contextmanager
def new_events_schema_for_request() -> Iterator[None]:
    """Every events read inside the block targets events_json, unless its query's modifier says otherwise."""
    token = _person_switch.set(True)
    try:
        yield
    finally:
        _person_switch.reset(token)


def _allowlisted_team_ids() -> set[int]:
    raw = str(get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS") or "")
    return {int(part) for part in raw.split(",") if part.strip()}


# Staff set the share of projects that read events_json, and the projects to keep on the legacy table, in this
# flag's release conditions. The conditions can filter on the person property project_id.
EVENTS_TABLE_ROLLOUT_FLAG = "new-events-table-rollout"
# While this flag is off for a project, the project cannot choose its events table and a stored choice is ignored,
# so turning the flag off puts every project back on the staff switches and the rollout.
EVENTS_TABLE_SELF_SERVE_FLAG = "new-events-table-self-serve"

_PROJECT_CHOICES_TTL_SECONDS = 60
_project_choices: tuple[float, dict[int, bool]] | None = None


def _flag_enabled_for_project(flag: str, team_id: int) -> bool:
    # The flag is evaluated in this process and keyed on the project id, so the query path makes no network call.
    if not is_cloud():
        return False
    return bool(
        posthoganalytics.feature_enabled(
            flag,
            str(team_id),
            person_properties={"project_id": str(team_id)},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    )


def clear_project_events_table_choices() -> None:
    global _project_choices
    _project_choices = None


def _project_events_table_choices() -> dict[int, bool]:
    # One cached map for every project, as get_instance_setting caches one value per key. A lookup per project
    # would add a database read to the first query of each project on each worker.
    global _project_choices
    if _project_choices is not None and time.monotonic() - _project_choices[0] < _PROJECT_CHOICES_TTL_SECONDS:
        return _project_choices[1]

    # Deferred: this module is imported at django.setup(), before the models load.
    from posthog.models.team.team_events_table_config import TeamEventsTableConfig  # noqa: PLC0415

    choices: dict[int, bool] = dict(
        TeamEventsTableConfig.objects.filter(use_new_events_table__isnull=False).values_list(
            "team_id", "use_new_events_table"
        )
    )
    _project_choices = (time.monotonic(), choices)
    return choices


def project_can_choose_events_table(team_id: int) -> bool:
    return _flag_enabled_for_project(EVENTS_TABLE_SELF_SERVE_FLAG, team_id)


def project_events_table_choice(team_id: int) -> bool | None:
    """The table the project chose for itself: True for events_json, False for events, None for no choice."""
    if not project_can_choose_events_table(team_id):
        return None
    return _project_events_table_choices().get(team_id)


def set_project_events_table_choice(team: "Team", use_new_events_table: bool | None) -> None:
    """Store the project's choice. Other workers read it once their cached choices expire, within a minute."""
    # Deferred: this module is imported at django.setup(), before the models load.
    from posthog.models.team.extensions import get_or_create_team_extension  # noqa: PLC0415
    from posthog.models.team.team_events_table_config import TeamEventsTableConfig  # noqa: PLC0415

    config = get_or_create_team_extension(team, TeamEventsTableConfig)
    config.use_new_events_table = use_new_events_table
    config.save(update_fields=["use_new_events_table"])
    clear_project_events_table_choices()


def project_reads_new_events_table(team_id: int | None) -> bool:
    """Whether the project reads events_json when no query modifier or staff cookie says otherwise.

    The first of these that has an answer decides: the project's own choice, CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA
    for every project, CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA_TEAMS for a listed project, then the rollout flag.
    Callers that pass no project, such as usage reports, follow CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA alone.
    """
    if team_id is not None:
        choice = project_events_table_choice(team_id)
        if choice is not None:
            return choice
    if get_instance_setting("CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA"):
        return True
    if team_id is None:
        return False
    return team_id in _allowlisted_team_ids() or _flag_enabled_for_project(EVENTS_TABLE_ROLLOUT_FLAG, team_id)


def use_new_events_schema(team_id: int | None = None, modifiers: "HogQLQueryModifiers | None" = None) -> bool:
    """Whether events reads target the native JSON events table (events_json) instead of the legacy events table.

    Three switches, each wider than the one before it: the query's useNewEventsSchema modifier, for one query;
    a staff person's cookie, for every request from that browser (see new_events_schema_for_request); and the
    project's table, for a project everywhere, background jobs included (see project_reads_new_events_table).
    The instance settings and the projects' own choices are cached for up to 60s per worker. Nested reads
    inherit the running query's choice unless their own modifier overrides it.
    Code running inside a query should prefer HogQLContext.uses_new_events_schema(), which
    resolves this once so a mid-query flip can't mix schemas.
    """
    if modifiers is not None and modifiers.useNewEventsSchema is not None:
        return modifiers.useNewEventsSchema
    route = get_events_route()
    if route is not None and route.useNewEventsSchema is not None:
        return route.useNewEventsSchema
    if _person_switch.get():
        return True
    if settings.TEST and settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
        return True
    return project_reads_new_events_table(team_id)


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
