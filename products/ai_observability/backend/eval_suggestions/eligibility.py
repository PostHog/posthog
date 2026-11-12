"""Who gets suggestions: a flagged organization, a recent visit, and steady AI traffic."""

from datetime import date, datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.models.team import Team

from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
    EvalSuggestionTeamState,
)

from .config import SuggestionSettings, is_enabled_for_organization
from .queries import MAX_EXECUTION_TIME_SECONDS

VISIT_LOOKBACK = timedelta(days=14)
MIN_DAYS_IN_28 = 4
MIN_DAYS_IN_7 = 2
TRAFFIC_BATCH = 500

# Cross-team by design: one aggregate over the visited teams instead of one query per team.
_GENERATION_DAYS_SQL = """
SELECT
    team_id,
    uniqExact(toDate(timestamp)) AS days_28,
    uniqExactIf(toDate(timestamp), timestamp >= %(week_start)s) AS days_7
FROM events
WHERE team_id IN %(team_ids)s
  AND event = '$ai_generation'
  AND timestamp >= %(start)s
  AND timestamp < %(end)s
GROUP BY team_id
"""


def record_visit(team: Team) -> None:
    # The row belongs to the root team, which for_team already resolves, so a child environment must not look
    # itself up by its own id: it would miss the row and try to create a second one.
    now = timezone.now()
    EvalSuggestionTeamState.objects.for_team(team.pk).update_or_create(
        defaults={"last_visited_at": now}, create_defaults={"team": team, "last_visited_at": now}
    )


def claim_first_visit_run(team: Team, today: date | None = None) -> bool:
    """True once per team and day while the team has no completed run, so the first page load fills the
    page the same day without a reload starting a run each time."""
    if EvalSuggestionRun.objects.for_team(team.pk).filter(status=EvalSuggestionRunStatus.COMPLETED).exists():
        return False
    today = today or timezone.now().date()
    claimed = (
        EvalSuggestionTeamState.objects.for_team(team.pk)
        .filter(Q(first_visit_run_on__isnull=True) | Q(first_visit_run_on__lt=today))
        .update(first_visit_run_on=today)
    )
    return claimed == 1


def steady_traffic_team_ids(team_ids: list[int], now: datetime) -> set[int]:
    if not team_ids:
        return set()
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.EVAL_SUGGESTIONS):
        rows = sync_execute(
            _GENERATION_DAYS_SQL,
            {
                "team_ids": team_ids,
                "start": now - timedelta(days=28),
                "week_start": now - timedelta(days=7),
                "end": now,
            },
            workload=Workload.OFFLINE,
            # Well inside the plan activity's 10 minutes, so a slow batch fails the query, not the activity.
            settings={"max_execution_time": MAX_EXECUTION_TIME_SECONDS},
        )
    return {int(team_id) for team_id, days_28, days_7 in rows if days_28 >= MIN_DAYS_IN_28 and days_7 >= MIN_DAYS_IN_7}


def eligible_team_ids(settings: SuggestionSettings, now: datetime | None = None) -> list[int]:
    """Teams someone visited in the last 14 days, in a flagged organization, with generations on at least
    4 of the last 28 days and 2 of the last 7. The most recently visited come first, up to the run cap."""
    now = now or timezone.now()
    visited = list(
        # The weekly plan reads every team that visited, by design.
        EvalSuggestionTeamState.objects.unscoped()
        .filter(last_visited_at__gte=now - VISIT_LOOKBACK)
        .order_by("-last_visited_at")
        .values_list("team_id", "team__organization_id")
    )
    flagged: dict[str, bool] = {}
    candidates = []
    for team_id, organization_id in visited:
        organization = str(organization_id)
        if organization not in flagged:
            flagged[organization] = is_enabled_for_organization(organization)
        if flagged[organization]:
            candidates.append(team_id)
    # Most recently visited first, in batches, so a cap of a few teams never aggregates traffic for thousands.
    eligible: list[int] = []
    for start in range(0, len(candidates), TRAFFIC_BATCH):
        batch = candidates[start : start + TRAFFIC_BATCH]
        steady = steady_traffic_team_ids(batch, now)
        eligible += [team_id for team_id in batch if team_id in steady]
        if len(eligible) >= settings.max_teams_per_run:
            break
    return eligible[: settings.max_teams_per_run]
