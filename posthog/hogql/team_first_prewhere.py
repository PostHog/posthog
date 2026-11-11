import threading
from datetime import timedelta

from django.utils.timezone import now

from cachetools import TTLCache, cached

from posthog.hogql import ast
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.visitor import TraversingVisitor

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.team.team_event_volume import TeamEventVolume
from posthog.ph_client import feature_enabled_or_false

TEAM_FIRST_PREWHERE_FLAG = "hogql-team-first-prewhere"
TEAM_FIRST_PREWHERE_MAX_EVENTS_LAST_YEAR = 100_000_000
TEAM_EVENT_VOLUME_MAX_AGE = timedelta(days=3)

_events_last_year_cache: TTLCache[int, int | None] = TTLCache(maxsize=10_000, ttl=timedelta(minutes=10).total_seconds())


@cached(_events_last_year_cache, lock=threading.Lock())
def _recent_events_last_year(team_id: int) -> int | None:
    return (
        TeamEventVolume.objects.for_team(team_id)
        .filter(computed_at__gte=now() - TEAM_EVENT_VOLUME_MAX_AGE)
        .values_list("events_last_year", flat=True)
        .first()
    )


class _EventsTableFinder(TraversingVisitor):
    def __init__(self) -> None:
        self.found = False

    def visit_table_type(self, node: ast.TableType) -> None:
        self.found = self.found or isinstance(node.table, EventsTable)


def _reads_events_table(prepared_ast: ast.AST | None) -> bool:
    if prepared_ast is None:
        return False
    finder = _EventsTableFinder()
    finder.visit(prepared_ast)
    return finder.found


def should_check_team_first_in_prewhere(team: Team, prepared_ast: ast.AST | None) -> bool:
    try:
        if not feature_enabled_or_false(
            TEAM_FIRST_PREWHERE_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.pk)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.pk)},
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        ):
            return False
        # The volume gate counts events, so it says nothing about how selective `team_id` is on other tables.
        if not _reads_events_table(prepared_ast):
            return False
        events_last_year = _recent_events_last_year(team.pk)
    except Exception as e:
        capture_exception(e)
        return False
    return events_last_year is not None and events_last_year < TEAM_FIRST_PREWHERE_MAX_EVENTS_LAST_YEAR
