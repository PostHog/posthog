import uuid
import random
import builtins
from datetime import datetime, timedelta
from typing import Optional, cast

from django.conf import settings
from django.core.cache import cache

from posthog.schema import EventsQuery, HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.limit import get_events_list_rate_limiter
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import generate_short_id, relative_date_parse

from products.actions.backend.models.action import Action

# Columns the events list/retrieve endpoints read. The order is the contract for zipping HogQL
# result rows back into the dict shape `ClickhouseEventSerializer` expects. Deliberately NOT "*":
# that triggers the runner's session-recording lookup and element expansion, which this endpoint's
# serializer does its own version of.
EVENT_LIST_SELECT_COLUMNS = ["uuid", "event", "properties", "timestamp", "distinct_id", "elements_chain"]

# Progressive time windows in seconds: 1min, 5min, 15min, 1hr, 6hr, 24hr.
EVENT_LIST_TIME_WINDOWS = [60, 300, 900, 3600, 21600, 86400]
EVENT_LIST_CACHE_TTL = 86400  # 24 hours
EVENT_LIST_CACHE_KEY_PREFIX = "event_list_good_period"


def _get_limit_size_category(limit: int) -> str:
    """Group limits into size categories to bound cache-key cardinality."""
    if limit < 1000:
        return "s"
    elif limit < 10000:
        return "m"
    return "l"


def _get_event_list_cache_key(team_id: int, has_event_filter: bool, has_distinct_id: bool, limit: int) -> str:
    """Cache key for the progressive-window optimization.

    The cache stores ``{"window": int, "result_count": int}`` so a cached window is only reused
    when its result_count clears the current request's half-limit threshold — otherwise a window
    that succeeded for a small limit would be wrongly reused for a larger one. Size categories
    (s/m/l) instead of exact limits bound the key cardinality to ~3 per team/filter combination.
    """
    event_flag = "1" if has_event_filter else "0"
    distinct_id_flag = "1" if has_distinct_id else "0"
    return f"{EVENT_LIST_CACHE_KEY_PREFIX}:{team_id}:{event_flag}:{distinct_id_flag}:{_get_limit_size_category(limit)}"


def _execute_events_list_query(runner: EventsQueryRunner, database: Database) -> tuple[builtins.list[dict], bool]:
    """Execute the events-list HogQL query and return ``(page_rows, has_more)``.

    Split out from `LegacyEventsListQuery.run_page` so the progressive-window probing can be tested
    against the real window/date logic while stubbing only the ClickHouse round-trip. The pre-built
    `database` is handed to the executor so it isn't rebuilt per probe.
    """
    runner.paginator.execute_hogql_query(
        runner.to_query(),
        query_type="events_list",
        team=runner.team,
        workload=Workload.OFFLINE,
        settings=HogQLGlobalSettings(max_threads=settings.CLICKHOUSE_EVENT_LIST_MAX_THREADS),
        modifiers=runner.modifiers,
        timings=runner.timings,
        user=runner.user,
        context=HogQLContext(team=runner.team, database=database, enable_select_queries=True),
    )
    rows = [dict(zip(EVENT_LIST_SELECT_COLUMNS, row)) for row in runner.paginator.results]
    return rows, runner.paginator.has_more()


def get_one_event(team: Team, pk: str) -> Optional[dict]:
    """Fetch a single event by uuid for the events retrieve endpoint, or None if it doesn't exist."""
    query = ast.SelectQuery(
        select=[ast.Field(chain=[column]) for column in EVENT_LIST_SELECT_COLUMNS],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["uuid"]),
            right=ast.Constant(value=uuid.UUID(pk)),
        ),
    )
    result = execute_hogql_query(query, team=team, query_type="event_detail")
    if not result.results:
        return None
    return dict(zip(EVENT_LIST_SELECT_COLUMNS, result.results[0]))


class LegacyEventsListQuery:
    """Backing query for the deprecated events list REST API (`posthog/api/event.py`).

    Translates the endpoint's loose query params into a typed HogQL `EventsQuery` and runs it
    through `EventsQueryRunner`, owning the progressive-window probing and its result-count cache.
    The HogQL schema (database + modifiers) is built once here and reused across every window probe.

    New code should build an `EventsQuery` (or use the `/query` endpoint) directly, not this.
    """

    def __init__(self, team: Team, user: Optional[User]) -> None:
        self.team = team
        self.user = user
        self.modifiers: HogQLQueryModifiers = create_default_modifiers_for_team(team)
        self.database = Database.create_for(team=team, user=user, modifiers=self.modifiers)

    def run(
        self,
        *,
        limit: int,
        offset: int,
        order: str,
        before: Optional[str],
        after: Optional[str],
        event: Optional[str],
        person_id: Optional[str],
        distinct_id: Optional[str],
        properties: "builtins.list[dict] | dict | None",
        action_id: Optional[str],
    ) -> tuple[builtins.list[dict], bool]:
        """Return one page of events as ``(rows, has_more)``.

        Probes progressively larger time windows (see `EVENT_LIST_TIME_WINDOWS`) so a recent-events
        request doesn't scan all history, stopping at the first window that returns at least half a
        page and caching it; falls back to the request's full range otherwise. Runs under the events
        rate limiter, on the OFFLINE workload.
        """
        cache_key = _get_event_list_cache_key(self.team.pk, bool(event), bool(distinct_id), limit)
        cached_data = cache.get(cache_key)

        request_window_seconds: Optional[int] = None
        if before and after:
            try:
                tzinfo = self.team.timezone_info
                request_window_seconds = int(
                    (relative_date_parse(before, tzinfo) - relative_date_parse(after, tzinfo)).total_seconds()
                )
            except (ValueError, TypeError):
                pass

        # Only probe windows shorter than the request's own range.
        windows_to_try = [
            w for w in EVENT_LIST_TIME_WINDOWS if request_window_seconds is None or w < request_window_seconds
        ]
        half_limit = max(limit // 2, 1)

        # Reuse a cached window only if it returned enough results for this request's threshold.
        cached_window = None
        if cached_data and isinstance(cached_data, dict):
            if cached_data.get("result_count", 0) >= half_limit:
                cached_window = cached_data.get("window")
        elif cached_data and isinstance(cached_data, int):
            cached_window = cached_data  # legacy cache format: bare window integer
        if cached_window and cached_window in windows_to_try:
            windows_to_try.remove(cached_window)
            windows_to_try.insert(0, cached_window)

        page_kwargs: dict = {
            "limit": limit,
            "offset": offset,
            "order": order,
            "before": before,
            "after": after,
            "event": event,
            "person_id": person_id,
            "distinct_id": distinct_id,
            "properties": properties,
            "action_id": action_id,
        }

        with get_events_list_rate_limiter().run(team_id=self.team.pk, task_id=generate_short_id()):
            rows: builtins.list[dict] = []
            has_more = False
            successful_window: Optional[int] = None
            applied_window: Optional[int] = None

            for window in windows_to_try:
                rows, has_more, applied_window = self.run_page(**page_kwargs, time_window_seconds=window)
                if applied_window is None:  # window not applicable (e.g. ASC order) — don't keep probing
                    break
                if len(rows) >= half_limit:
                    successful_window = window
                    break

            if successful_window:
                new_cache_data = {"window": successful_window, "result_count": len(rows)}
                if new_cache_data != cached_data:
                    cache.set(cache_key, new_cache_data, EVENT_LIST_CACHE_TTL)
            elif applied_window is not None or not windows_to_try:
                # Windows were applied but came up short, or there were none — run the full range.
                rows, has_more, applied_window = self.run_page(**page_kwargs)

        return rows, has_more

    def run_page(
        self,
        *,
        limit: int,
        offset: int,
        order: str,
        before: Optional[str],
        after: Optional[str],
        event: Optional[str],
        person_id: Optional[str],
        distinct_id: Optional[str],
        properties: "builtins.list[dict] | dict | None",
        action_id: Optional[str],
        time_window_seconds: Optional[int] = None,
    ) -> tuple[builtins.list[dict], bool, Optional[int]]:
        """Run a single window probe.

        Returns the page rows (already trimmed to `limit`), whether more rows exist, and the time
        window that was applied (`None` when the request's own date range was used).
        """
        tzinfo = self.team.timezone_info

        # Resolve the [after_dt, before_dt) bounds. `before` defaults to just past now (so events
        # ingested a moment ago aren't excluded); `after` stays open unless requested.
        # PATCH_EVENT_LIST_MAX_OFFSET clamps this deprecated endpoint's ClickHouse cost as a graduated
        # rollout (0 = off, 1 = migration, 2 = enabled; see settings/data_stores.py): at 2 a missing
        # `after` defaults to before-24h, and a range over a year is rejected (always at 2, ~1% at 1).
        before_dt = relative_date_parse(before, tzinfo) if before else datetime.now(tzinfo) + timedelta(seconds=5)
        if after:
            after_dt: Optional[datetime] = relative_date_parse(after, tzinfo)
        elif settings.PATCH_EVENT_LIST_MAX_OFFSET > 1:
            after_dt = before_dt - timedelta(hours=24)
        else:
            after_dt = None

        if settings.PATCH_EVENT_LIST_MAX_OFFSET > 0 and after_dt is not None:
            if (before_dt - after_dt) > timedelta(days=366) and (
                settings.PATCH_EVENT_LIST_MAX_OFFSET > 1 or random.random() < 0.01
            ):
                raise ValueError("Date range cannot exceed 1 year")

        applied_window_seconds: Optional[int] = None
        if (
            order == "DESC"
            and time_window_seconds is not None
            and (after_dt is None or (before_dt - after_dt).total_seconds() > time_window_seconds)
        ):
            after_dt = before_dt - timedelta(seconds=time_window_seconds)
            applied_window_seconds = time_window_seconds

        # Match the legacy behaviour for actions with no match groups (or that no longer exist):
        # an empty result, not an error. The runner would otherwise raise. A malformed action_id
        # is left to fail (int() raises) — bad input should error, not silently return nothing.
        if action_id:
            try:
                action = Action.objects.get(pk=int(action_id), team__project_id=self.team.project_id)
            except Action.DoesNotExist:
                return [], False, applied_window_seconds
            if not action.steps:
                return [], False, applied_window_seconds

        # A flat list of leaf filters goes through `properties`; a property group goes through
        # `fixedProperties`, where the runner's `property_to_expr` preserves its nested AND/OR.
        where_properties: builtins.list[dict] = []
        fixed_properties: builtins.list[dict] = []
        if isinstance(properties, dict):
            fixed_properties = [properties]
        elif properties:
            where_properties = list(properties)
        if distinct_id is not None:
            where_properties.append(
                {"type": "event_metadata", "key": "distinct_id", "value": distinct_id, "operator": "exact"}
            )

        events_query = EventsQuery(
            select=EVENT_LIST_SELECT_COLUMNS,
            before=before_dt.isoformat(),
            # "all" disables the runner's default 24h lower bound: with no `after` and no window,
            # the query has no lower timestamp bound at all.
            after=after_dt.isoformat() if after_dt is not None else "all",
            event=event or None,
            personId=str(person_id) if person_id else None,
            actionId=int(action_id) if action_id else None,
            properties=cast("builtins.list[dict[str, object]]", where_properties) if where_properties else None,
            fixedProperties=cast("builtins.list[dict[str, object]]", fixed_properties) if fixed_properties else None,
            orderBy=[f"timestamp {order}"],
            limit=limit,
            offset=offset,
        )

        runner = EventsQueryRunner(query=events_query, team=self.team, user=self.user, modifiers=self.modifiers)
        rows, has_more = _execute_events_list_query(runner, self.database)
        return rows, has_more, applied_window_seconds
