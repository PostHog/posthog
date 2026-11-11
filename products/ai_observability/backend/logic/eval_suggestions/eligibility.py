"""Who gets suggestions: a flagged organization, a recent visit, and steady AI traffic."""

from collections.abc import Awaitable, Callable, Iterable
from datetime import date, datetime, timedelta

from django.db.models import Q
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.models.team import Team

from products.ai_observability.backend.logic.eval_suggestions.eligibility_queries import (
    GenerationDaysRow,
    load_generation_days,
)
from products.ai_observability.backend.models.eval_suggestions import (
    EvalSuggestionRun,
    EvalSuggestionRunStatus,
    EvalSuggestionTeamState,
)

from .config import SuggestionSettings, is_enabled_for_organization

logger = structlog.get_logger(__name__)

VISIT_LOOKBACK = timedelta(days=14)
MIN_DAYS_IN_28 = 4
MIN_DAYS_IN_7 = 2
TRAFFIC_BATCH = 500


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


class TemporalUnreachable(Exception):
    """Connecting failed, so no start request reached Temporal."""


# Starts a team's first-visit workflow for a run row. The facade passes the Temporal client's starter in, so logic
# does not import workflow code.
StartRun = Callable[[int, str], Awaitable[None]]


def queue_first_visit_run(team: Team, start_run: StartRun) -> None:
    """Start the free stages for a team's first visit.

    The run row exists before the workflow starts, so the page reads the queued run as pending until a worker
    finishes it.
    """
    run = EvalSuggestionRun.objects.for_team(team.pk).create(team=team, trigger="first_visit")
    try:
        async_to_sync(start_run)(team.pk, str(run.id))
    except TemporalUnreachable:
        run.delete()
        raise
    except Exception:
        # This error can come after Temporal accepted the start, and the worker may already have published
        # cards on this row. It stays pending; a row no worker picks up stops counting after TEAM_TIMEOUT.
        logger.exception("llma.eval_suggestions_first_visit_start_unclear", team_id=team.pk, run_id=str(run.id))


def steady_traffic(rows: Iterable[GenerationDaysRow]) -> set[int]:
    return {row.team_id for row in rows if row.days_28 >= MIN_DAYS_IN_28 and row.days_7 >= MIN_DAYS_IN_7}


def steady_traffic_team_ids(team_ids: list[int], now: datetime) -> set[int]:
    if not team_ids:
        return set()
    return steady_traffic(load_generation_days(team_ids, now))


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
