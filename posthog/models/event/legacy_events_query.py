import random
import builtins
from datetime import datetime, timedelta
from typing import Optional, cast

from django.conf import settings

from posthog.schema import EventsQuery, HogQLQueryModifiers

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models.team import Team
from posthog.models.user import User
from posthog.utils import relative_date_parse

from products.actions.backend.models.action import Action

# Columns the events list/retrieve endpoints read. The order is the contract for zipping HogQL
# result rows back into the dict shape `ClickhouseEventSerializer` expects. Deliberately NOT "*":
# that triggers the runner's session-recording lookup and element expansion, which this endpoint's
# serializer does its own version of.
EVENT_LIST_SELECT_COLUMNS = ["uuid", "event", "properties", "timestamp", "distinct_id", "elements_chain"]


def _execute_events_list_query(runner: EventsQueryRunner, database: Database) -> tuple[builtins.list[dict], bool]:
    """Execute the events-list HogQL query and return ``(page_rows, has_more)``.

    Split out from `LegacyEventsListQuery.run_page` so the progressive-window probing in the
    viewset can be tested against the real window/date logic while stubbing only the ClickHouse
    round-trip. The pre-built `database` is handed to the executor so it isn't rebuilt per probe.
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


class LegacyEventsListQuery:
    """Backing query for the deprecated events list REST API (`posthog/api/event.py`).

    Translates the old endpoint's loose query params into a typed HogQL `EventsQuery` and runs it
    through `EventsQueryRunner`, reproducing the legacy response shape. It replaces the hand-written
    raw-SQL path that used to live in `query_event_list.py`. The HogQL schema (database + modifiers)
    is built once here and reused across every progressive-window probe the viewset issues, so it
    isn't rebuilt per probe.

    New code should build an `EventsQuery` (or use the `/query` endpoint) directly, not this.
    """

    def __init__(self, team: Team, user: Optional[User]) -> None:
        self.team = team
        self.user = user
        self.modifiers: HogQLQueryModifiers = create_default_modifiers_for_team(team)
        self.database = Database.create_for(team=team, user=user, modifiers=self.modifiers)

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
        """Run a single events-list page.

        Returns the page rows (already trimmed to `limit`), whether more rows exist, and the time
        window that was applied (`None` when the request's own date range was used). The
        progressive-window probing and result-count cache live in the viewset; this is one probe.
        Heavy event-list scans run on the OFFLINE workload, isolated from the main query nodes.
        """
        tzinfo = self.team.timezone_info

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
            # "all" disables the runner's lower timestamp bound — matches the legacy path, which
            # applied no `timestamp >` condition when there was no `after` and no window.
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
