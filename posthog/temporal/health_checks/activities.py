import dataclasses
from datetime import timedelta
from itertools import batched

from django.db import close_old_connections
from django.db.models import Exists, OuterRef
from django.utils import timezone

import structlog
import temporalio.activity

from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models.organization import OrganizationMembership
from posthog.sync import database_sync_to_async
from posthog.temporal.common.rollout import filter_ids_for_rollout
from posthog.temporal.health_checks.models import BatchResult, HealthCheckWorkflowInputs
from posthog.temporal.health_checks.observability import push_health_check_metrics
from posthog.temporal.health_checks.processing import _process_batch_detection
from posthog.temporal.health_checks.registry import ensure_registry_loaded, get_detect_fn, get_product

logger = structlog.get_logger(__name__)


@database_sync_to_async
def _get_team_id_batches_sync(inputs: HealthCheckWorkflowInputs) -> list[list[int]]:
    from posthog.models.team import Team

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
        qs = Team.objects.exclude(id=0)
        cutoff = None
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
        team_ids = list(qs.values_list("id", flat=True))
        logger.info(
            "team query complete",
            count=len(team_ids),
            active_since_days=inputs.active_since_days,
            cutoff=cutoff.isoformat() if cutoff else None,
        )

    if inputs.rollout_percentage < 1.0:
        team_ids = filter_ids_for_rollout(team_ids, inputs.rollout_percentage)
        logger.info("after rollout filtering", rollout_pct=inputs.rollout_percentage, count=len(team_ids))

    batches = [list(b) for b in batched(team_ids, inputs.batch_size)]

    logger.info("created team batches", batch_count=len(batches), batch_size=inputs.batch_size)
    return batches


@temporalio.activity.defn
async def get_team_id_batches(inputs: HealthCheckWorkflowInputs) -> list[list[int]]:
    return await _get_team_id_batches_sync(inputs)


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
