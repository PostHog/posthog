import dataclasses
from datetime import timedelta
from itertools import batched
from typing import TYPE_CHECKING

from django.db import close_old_connections
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

import structlog
import temporalio.activity

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.organization import OrganizationMembership
from posthog.sync import database_sync_to_async
from posthog.temporal.common.rollout import filter_ids_for_rollout
from posthog.temporal.health_checks.models import BatchResult, HealthCheckWorkflowInputs, TeamIdPage
from posthog.temporal.health_checks.observability import push_health_check_metrics
from posthog.temporal.health_checks.processing import _process_batch_detection
from posthog.temporal.health_checks.registry import ensure_registry_loaded, get_detect_fn, get_product

if TYPE_CHECKING:
    from posthog.models.team import Team

logger = structlog.get_logger(__name__)

# A page holds this many batches at most, so one page adds a bounded number of events to the workflow history.
BATCHES_PER_TEAM_ID_PAGE = 200
# Keeps the page payload far below Temporal's 2 MiB limit whatever the batch size.
MAX_TEAM_IDS_PER_PAGE = 20_000


def team_id_page_size(batch_size: int) -> int:
    return max(batch_size, min(batch_size * BATCHES_PER_TEAM_ID_PAGE, MAX_TEAM_IDS_PER_PAGE))


def _scheduled_teams(inputs: HealthCheckWorkflowInputs) -> "QuerySet[Team]":
    """Teams a scheduled run visits: every team, or only those with a member who logged in recently."""
    from posthog.models.team import Team

    qs = Team.objects.exclude(id=0)
    if inputs.active_since_days is not None and inputs.active_since_days > 0:
        cutoff = timezone.now() - timedelta(days=inputs.active_since_days)
        qs = qs.filter(
            Exists(
                OrganizationMembership.objects.filter(
                    organization_id=OuterRef("organization_id"),
                    user__last_login__gte=cutoff,
                )
            )
        )
    return qs


@database_sync_to_async
def _get_team_id_batches_sync(inputs: HealthCheckWorkflowInputs) -> list[list[int]]:
    # Temporal activities run in a thread pool where DB connections can go stale
    # between executions. close_old_connections() ensures we get a fresh connection.
    close_old_connections()

    kill_switch_level = get_kill_switch_level()
    if kill_switch_level != KillSwitchLevel.OFF:
        logger.info(
            "skipping health check due to clickhouse kill switch",
            kind=inputs.kind,
            kill_switch_level=kill_switch_level.value,
        )
        return []

    if inputs.team_ids:
        team_ids = inputs.team_ids
        logger.info("processing configured teams", count=len(team_ids))
    else:
        team_ids = list(_scheduled_teams(inputs).values_list("id", flat=True))
        logger.info("team query complete", count=len(team_ids), active_since_days=inputs.active_since_days)

    if inputs.rollout_percentage < 1.0:
        team_ids = filter_ids_for_rollout(team_ids, inputs.rollout_percentage)
        logger.info("after rollout filtering", rollout_pct=inputs.rollout_percentage, count=len(team_ids))

    batches = [list(b) for b in batched(team_ids, inputs.batch_size, strict=False)]

    logger.info("created team batches", batch_count=len(batches), batch_size=inputs.batch_size)
    return batches


@temporalio.activity.defn
async def get_team_id_batches(inputs: HealthCheckWorkflowInputs) -> list[list[int]]:
    return await _get_team_id_batches_sync(inputs)


def _next_team_ids(inputs: HealthCheckWorkflowInputs, after_team_id: int, page_size: int) -> list[int]:
    if inputs.team_ids:
        return sorted(team_id for team_id in set(inputs.team_ids) if team_id > after_team_id)[:page_size]

    teams = _scheduled_teams(inputs).filter(id__gt=after_team_id).order_by("id")
    return list(teams.values_list("id", flat=True)[:page_size])


def build_team_id_page(inputs: HealthCheckWorkflowInputs, after_team_id: int) -> TeamIdPage:
    """The next scheduled teams after `after_team_id`, in id order. `next_after_team_id` is None on the last page."""
    kill_switch_level = get_kill_switch_level()
    if kill_switch_level != KillSwitchLevel.OFF:
        logger.info(
            "skipping health check due to clickhouse kill switch",
            kind=inputs.kind,
            kill_switch_level=kill_switch_level.value,
        )
        return TeamIdPage(team_ids=[], next_after_team_id=None, stopped_by_kill_switch=True)

    page_size = team_id_page_size(inputs.batch_size)
    team_ids = _next_team_ids(inputs, after_team_id, page_size)
    next_after_team_id = team_ids[-1] if len(team_ids) == page_size else None

    # The rollout keeps the same share of every page. The pages are stable while the team set is stable,
    # so the selected teams are stable across runs too.
    if inputs.rollout_percentage < 1.0:
        team_ids = filter_ids_for_rollout(team_ids, inputs.rollout_percentage)

    logger.info(
        "team id page",
        kind=inputs.kind,
        after_team_id=after_team_id,
        count=len(team_ids),
        next_after_team_id=next_after_team_id,
    )
    return TeamIdPage(team_ids=team_ids, next_after_team_id=next_after_team_id)


@temporalio.activity.defn
async def get_team_id_page(inputs: HealthCheckWorkflowInputs, after_team_id: int) -> TeamIdPage:
    return await _get_team_id_page_sync(inputs, after_team_id)


@database_sync_to_async
def _get_team_id_page_sync(inputs: HealthCheckWorkflowInputs, after_team_id: int) -> TeamIdPage:
    # See comment in _get_team_id_batches_sync for why this is needed.
    close_old_connections()
    return build_team_id_page(inputs, after_team_id)


@database_sync_to_async
def _run_health_check_batch_sync(
    team_ids: list[int],
    kind: str,
    dry_run: bool,
) -> dict:
    # See comment in _get_team_id_batches_sync for why this is needed.
    close_old_connections()

    ensure_registry_loaded()
    tag_queries(
        product=get_product(kind),
        feature=Feature.HEALTH_CHECK,
        name=kind,
        query_type=f"health_check_{kind}",
    )
    detect_fn = get_detect_fn(kind)

    result = _process_batch_detection(team_ids, kind, detect_fn, dry_run=dry_run)
    return dataclasses.asdict(result)


@temporalio.activity.defn
async def run_health_check_batch(
    team_ids: list[int],
    kind: str,
    dry_run: bool,
) -> dict:
    return await _run_health_check_batch_sync(team_ids, kind, dry_run)


@temporalio.activity.defn
async def push_health_check_metrics_activity(
    kind: str,
    totals_dict: dict,
    success: bool,
) -> None:
    totals = BatchResult(**totals_dict)
    push_health_check_metrics(kind, totals, success=success)
