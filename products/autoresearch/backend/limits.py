"""Per-project autoresearch limits, resolved from the `autoresearch-limits` flag payload.

A training run is a paid Tasks sandbox whose LLM traffic the project does not pay for, so these
limits are the only bound on what one project can spend. Each limit resolves through three
layers, most specific first: the project's own `team_configs["<team_id>"]` entry, then the
fleet-wide `default_team_config`, then the code constant here. Edit the flag payload to change a
limit without a deploy:

    {
        "default_team_config": {"max_training_runs_per_day": 3, "max_iterations_per_run": 10, "max_live_pipelines": 3},
        "team_configs": {"2": {"max_training_runs_per_day": 20, "max_live_pipelines": 10, "max_training_spend_usd_per_month": 500}}
    }

`max_training_spend_usd_per_month` is whole US dollars. The month's spend is the token cost plus
the compute cost that Tasks records for the project's `autoresearch` task runs created since the
start of the current UTC calendar month. A run whose token cost is not recorded counts as 0. The
budget refuses a new run at or above the limit and never stops a run in progress, so a month can
end above it by the runs that were in progress when it was reached.

`autoresearch-limits` holds only the payload and must stay 100% on. The payload is read for a
synthetic distinct id, so a flag with release conditions on people evaluates to false for it,
serves no payload, and every project silently gets the code constants.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from django.db import connection, models
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.tasks.backend.facade.api import TaskOriginProduct, origin_run_ids_since
from products.tasks.backend.facade.billing import get_task_runs_spend

from .access import AUTORESEARCH_FLAG
from .models import AutoresearchPipeline, AutoresearchTrainingRun

logger = structlog.get_logger(__name__)

AUTORESEARCH_LIMITS_FLAG = "autoresearch-limits"

# Fixed distinct id for the payload read, because the limits are per project, not per person.
_PAYLOAD_DISTINCT_ID = "internal_autoresearch_team_limits"

DEFAULT_MAX_TRAINING_RUNS_PER_DAY = 3
DEFAULT_MAX_ITERATIONS_PER_RUN = 10
DEFAULT_MAX_LIVE_PIPELINES = 3
DEFAULT_MAX_TRAINING_SPEND_USD_PER_MONTH = 100

TEAM_CONFIG_MAX_TRAINING_RUNS_PER_DAY = "max_training_runs_per_day"
TEAM_CONFIG_MAX_ITERATIONS_PER_RUN = "max_iterations_per_run"
TEAM_CONFIG_MAX_LIVE_PIPELINES = "max_live_pipelines"
TEAM_CONFIG_MAX_TRAINING_SPEND_USD_PER_MONTH = "max_training_spend_usd_per_month"

# Each of these adds scoring, shadow scoring and validation to the daily sweep, and competes for
# the project's training runs. Paused, draft and archived pipelines do none of that.
LIVE_PIPELINE_STATUSES = (
    AutoresearchPipeline.Status.BOOTSTRAPPING,
    AutoresearchPipeline.Status.RUNNING,
    AutoresearchPipeline.Status.CONVERGED,
)

# The daily cap counts runs over a rolling window, so a burst just after midnight UTC cannot
# spend two days of runs in one sitting. Shorter than a day, so the runs one daily sweep starts
# have left the window when the next sweep reaches kickoff, even up to two hours earlier in the day.
TRAINING_RUN_WINDOW = timedelta(hours=22)

# Namespace for the per-team advisory lock, so it cannot collide with another product's key.
_TRAINING_CAP_LOCK_NAMESPACE = 0x41525452  # "ARTR"
_LIVE_PIPELINE_CAP_LOCK_NAMESPACE = 0x41524C50  # "ARLP"


class LimitSource(models.TextChoices):
    PROJECT = "project"
    DEFAULT = "default"
    CODE = "code"


@frozen
class LimitSources:
    max_training_runs_per_day: LimitSource = LimitSource.CODE
    max_iterations_per_run: LimitSource = LimitSource.CODE
    max_live_pipelines: LimitSource = LimitSource.CODE
    max_training_spend_usd_per_month: LimitSource = LimitSource.CODE


@frozen
class TeamLimits:
    # 0 stops every sandbox training run for the project.
    max_training_runs_per_day: int
    max_iterations_per_run: int
    # 0 stops every pipeline from going live.
    max_live_pipelines: int
    # Whole US dollars. 0 stops every sandbox training run for the project.
    max_training_spend_usd_per_month: int = DEFAULT_MAX_TRAINING_SPEND_USD_PER_MONTH
    # The payload layer each limit came from.
    sources: LimitSources = LimitSources()


@frozen
class TrainingCapReached:
    used: int
    limit: int
    # When the oldest counted run leaves the window. None when the limit is 0.
    next_slot_at: datetime | None


@frozen
class TrainingRunUsage:
    used: int
    limit: int
    # When the next run can start while the project is at its limit. None while a slot is free,
    # and when the limit is 0.
    next_slot_at: datetime | None


@frozen
class LiveCapReached:
    used: int
    limit: int


@frozen
class TrainingSpend:
    # Token plus compute cost of this month's sandbox training runs, in US dollars.
    spent_usd: float
    limit_usd: int
    # The start of the next UTC calendar month.
    resets_at: datetime


@frozen
class TrainingBudgetReached:
    spent_usd: float
    limit_usd: int
    resets_at: datetime


def limits_for_team(team_id: int) -> TeamLimits:
    """The project's effective limits. A missing or unreadable payload resolves to the code constants."""
    payload = _read_limits_payload()
    training_runs, training_runs_source = _resolve_int(
        payload, team_id, TEAM_CONFIG_MAX_TRAINING_RUNS_PER_DAY, DEFAULT_MAX_TRAINING_RUNS_PER_DAY, minimum=0
    )
    iterations, iterations_source = _resolve_int(
        payload, team_id, TEAM_CONFIG_MAX_ITERATIONS_PER_RUN, DEFAULT_MAX_ITERATIONS_PER_RUN, minimum=1
    )
    live_pipelines, live_pipelines_source = _resolve_int(
        payload, team_id, TEAM_CONFIG_MAX_LIVE_PIPELINES, DEFAULT_MAX_LIVE_PIPELINES, minimum=0
    )
    spend, spend_source = _resolve_int(
        payload,
        team_id,
        TEAM_CONFIG_MAX_TRAINING_SPEND_USD_PER_MONTH,
        DEFAULT_MAX_TRAINING_SPEND_USD_PER_MONTH,
        minimum=0,
    )
    return TeamLimits(
        max_training_runs_per_day=training_runs,
        max_iterations_per_run=iterations,
        max_live_pipelines=live_pipelines,
        max_training_spend_usd_per_month=spend,
        sources=LimitSources(
            max_training_runs_per_day=training_runs_source,
            max_iterations_per_run=iterations_source,
            max_live_pipelines=live_pipelines_source,
            max_training_spend_usd_per_month=spend_source,
        ),
    )


def check_training_run_cap(team_id: int, limits: TeamLimits) -> TrainingCapReached | None:
    """Whether the project has used its sandbox training runs for the window, or None when a slot is free.

    Call inside the ``transaction.atomic()`` that creates the run. The advisory lock is held until
    that transaction ends, so two pipelines of one team cannot both take the last slot.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_TRAINING_CAP_LOCK_NAMESPACE, team_id])
    usage = training_run_usage(team_id, limits)
    if usage.used < usage.limit:
        return None
    logger.info("autoresearch_training_cap_reached", team_id=team_id, used=usage.used, limit=usage.limit)
    return TrainingCapReached(used=usage.used, limit=usage.limit, next_slot_at=usage.next_slot_at)


def training_run_usage(team_id: int, limits: TeamLimits) -> TrainingRunUsage:
    """The project's sandbox training runs in the window, and when the next one can start if it is at its limit."""
    limit = limits.max_training_runs_per_day
    window_start = timezone.now() - TRAINING_RUN_WINDOW
    created = list(
        counted_training_runs(team_id)
        .filter(created_at__gte=window_start)
        .order_by("created_at")
        .values_list("created_at", flat=True)
    )
    at_limit = limit > 0 and len(created) >= limit
    next_slot_at = created[len(created) - limit] + TRAINING_RUN_WINDOW if at_limit else None
    return TrainingRunUsage(used=len(created), limit=limit, next_slot_at=next_slot_at)


def check_training_budget(team_id: int, limits: TeamLimits) -> TrainingBudgetReached | None:
    """Whether the project has used its monthly training budget, or None when a run can start.

    Call after ``check_training_run_cap()``, inside the same transaction, so its advisory lock
    serializes two starts of one team.
    """
    spend = training_spend(team_id, limits)
    if spend.spent_usd < spend.limit_usd:
        return None
    logger.info(
        "autoresearch_training_budget_reached", team_id=team_id, spent_usd=spend.spent_usd, limit_usd=spend.limit_usd
    )
    return TrainingBudgetReached(spent_usd=spend.spent_usd, limit_usd=spend.limit_usd, resets_at=spend.resets_at)


def training_spend(team_id: int, limits: TeamLimits) -> TrainingSpend:
    """This month's spend on the project's sandbox training runs, a run in progress included."""
    month_start = timezone.now().astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    resets_at = (month_start + timedelta(days=32)).replace(day=1)
    # Read from Tasks, not from the training run rows, because deleting a pipeline deletes its
    # training runs and would take their spend out of the month.
    run_ids = origin_run_ids_since(team_id=team_id, origin_product=TaskOriginProduct.AUTORESEARCH, since=month_start)
    spends = get_task_runs_spend(team_id=team_id, run_ids=run_ids) if run_ids else []
    spent_microusd = sum((spend.cost_microusd or 0) + spend.compute_cost_microusd for spend in spends)
    # A run that has not reached the gateway yet, or whose sandbox did not route through it, has no
    # token cost, so a month of these would read as no spend at all.
    unrecorded = len(run_ids) - sum(1 for spend in spends if spend.cost_microusd is not None)
    if unrecorded:
        logger.info(
            "autoresearch_training_spend_unrecorded", team_id=team_id, unrecorded_runs=unrecorded, runs=len(run_ids)
        )
    return TrainingSpend(
        spent_usd=round(spent_microusd / 1_000_000, 2),
        limit_usd=limits.max_training_spend_usd_per_month,
        resets_at=resets_at,
    )


def check_live_pipeline_cap(team_id: int, limits: TeamLimits) -> LiveCapReached | None:
    """Whether the project already has its limit of live pipelines, or None when another can go live.

    Call inside the ``transaction.atomic()`` that makes a pipeline live, before the pipeline being
    changed counts as live. The advisory lock is held until that transaction ends, so two
    pipelines of one team cannot both take the last slot. Pipelines already over the limit keep
    running: the cap only stops another one from going live.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_LIVE_PIPELINE_CAP_LOCK_NAMESPACE, team_id])
    used = live_pipeline_count(team_id)
    if used < limits.max_live_pipelines:
        return None
    logger.info("autoresearch_live_pipeline_cap_reached", team_id=team_id, used=used, limit=limits.max_live_pipelines)
    return LiveCapReached(used=used, limit=limits.max_live_pipelines)


def live_pipeline_count(team_id: int) -> int:
    """Live pipelines, plus drafts with an open training run.

    A draft stays a draft while an external agent's run is open, and its promotion makes it live
    with no check, so the open run holds its slot from the start.
    """
    open_run = AutoresearchTrainingRun.objects.for_team(team_id).filter(
        pipeline=OuterRef("pk"),
        status__in=[AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING],
    )
    return (
        AutoresearchPipeline.objects.for_team(team_id)
        .annotate(has_open_run=Exists(open_run))
        .filter(Q(status__in=LIVE_PIPELINE_STATUSES) | Q(status=AutoresearchPipeline.Status.DRAFT, has_open_run=True))
        .count()
    )


def counted_training_runs(team_id: int) -> QuerySet[AutoresearchTrainingRun]:
    """The project's training runs that ran, or are about to run, in a paid sandbox.

    A run that ``open_training_run()`` opened records no agent settings and no task, because the
    caller's own agent does the work, so it does not count. Neither does a stub run.
    """
    live = [AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING]
    return AutoresearchTrainingRun.objects.for_team(team_id).filter(
        Q(task_id__isnull=False) | Q(status__in=live, agent_runtime_adapter__isnull=False)
    )


def _read_limits_payload() -> dict | None:
    payload = _read_flag_payload(AUTORESEARCH_LIMITS_FLAG)
    if payload is None:
        # Remove this fallback once the payload has moved off the access flag.
        payload = _read_flag_payload(AUTORESEARCH_FLAG)
    if payload is None and is_cloud():
        # Self-hosted instances have no flag, so the code constants are expected there.
        logger.warning("autoresearch_limits_payload_missing", flag=AUTORESEARCH_LIMITS_FLAG)
    return payload


def _read_flag_payload(flag_key: str) -> dict | None:
    try:
        payload = posthoganalytics.get_feature_flag_payload(flag_key, _PAYLOAD_DISTINCT_ID, match_value=True)
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as error:
        capture_exception(error)
        return None


def _resolve_int(
    payload: dict | None, team_id: int, key: str, default: int, *, minimum: int
) -> tuple[int, LimitSource]:
    """The first valid value from the team's entry, then the fleet default, then ``default``, with its layer.

    A value that is not an integer at least ``minimum`` is skipped, so a typo in one layer falls
    through to the next rather than lifting the limit.
    """
    if payload is None:
        return default, LimitSource.CODE
    team_configs = payload.get("team_configs")
    layers = [
        (team_configs.get(str(team_id)) if isinstance(team_configs, dict) else None, LimitSource.PROJECT),
        (payload.get("default_team_config"), LimitSource.DEFAULT),
    ]
    for layer, source in layers:
        if not isinstance(layer, dict):
            continue
        value = layer.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= minimum:
            return value, source
    return default, LimitSource.CODE
