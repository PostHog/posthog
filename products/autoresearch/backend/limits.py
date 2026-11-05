"""Per-project autoresearch limits, resolved from the `autoresearch` flag payload.

A training run is a paid Tasks sandbox whose LLM traffic the project does not pay for, so these
limits are the only bound on what one project can spend. Each limit resolves through three
layers, most specific first: the project's own `team_configs["<team_id>"]` entry, then the
fleet-wide `default_team_config`, then the code constant here. Edit the flag payload to change a
limit without a deploy:

    {
        "default_team_config": {"max_training_runs_per_day": 3, "max_iterations_per_run": 10},
        "team_configs": {"2": {"max_training_runs_per_day": 20}}
    }
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from django.db import connection
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from .access import AUTORESEARCH_FLAG
from .models import AutoresearchTrainingRun

logger = structlog.get_logger(__name__)

# Fixed distinct id for the payload read, because the limits are per project, not per person.
_PAYLOAD_DISTINCT_ID = "internal_autoresearch_team_limits"

DEFAULT_MAX_TRAINING_RUNS_PER_DAY = 3
DEFAULT_MAX_ITERATIONS_PER_RUN = 10

TEAM_CONFIG_MAX_TRAINING_RUNS_PER_DAY = "max_training_runs_per_day"
TEAM_CONFIG_MAX_ITERATIONS_PER_RUN = "max_iterations_per_run"

# The daily cap counts runs over a rolling window, so a burst just after midnight UTC cannot
# spend two days of runs in one sitting.
TRAINING_RUN_WINDOW = timedelta(hours=24)

# Namespace for the per-team advisory lock, so it cannot collide with another product's key.
_TRAINING_CAP_LOCK_NAMESPACE = 0x41525452  # "ARTR"


@frozen
class TeamLimits:
    # 0 stops every sandbox training run for the project.
    max_training_runs_per_day: int
    max_iterations_per_run: int


@frozen
class TrainingCapReached:
    used: int
    limit: int
    # When the oldest counted run leaves the window. None when the limit is 0.
    next_slot_at: datetime | None


def limits_for_team(team_id: int) -> TeamLimits:
    """The project's effective limits. A missing or unreadable payload resolves to the code constants."""
    payload = _read_flag_payload()
    return TeamLimits(
        max_training_runs_per_day=_resolve_int(
            payload, team_id, TEAM_CONFIG_MAX_TRAINING_RUNS_PER_DAY, DEFAULT_MAX_TRAINING_RUNS_PER_DAY, minimum=0
        ),
        max_iterations_per_run=_resolve_int(
            payload, team_id, TEAM_CONFIG_MAX_ITERATIONS_PER_RUN, DEFAULT_MAX_ITERATIONS_PER_RUN, minimum=1
        ),
    )


def check_training_run_cap(team_id: int, limits: TeamLimits) -> TrainingCapReached | None:
    """Whether the project has used its sandbox training runs for the window, or None when a slot is free.

    Call inside the ``transaction.atomic()`` that creates the run. The advisory lock is held until
    that transaction ends, so two pipelines of one team cannot both take the last slot.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_TRAINING_CAP_LOCK_NAMESPACE, team_id])
    limit = limits.max_training_runs_per_day
    window_start = timezone.now() - TRAINING_RUN_WINDOW
    created = list(
        counted_training_runs(team_id)
        .filter(created_at__gte=window_start)
        .order_by("created_at")
        .values_list("created_at", flat=True)
    )
    if len(created) < limit:
        return None
    next_slot_at = created[len(created) - limit] + TRAINING_RUN_WINDOW if limit > 0 else None
    logger.info("autoresearch_training_cap_reached", team_id=team_id, used=len(created), limit=limit)
    return TrainingCapReached(used=len(created), limit=limit, next_slot_at=next_slot_at)


def counted_training_runs(team_id: int) -> QuerySet[AutoresearchTrainingRun]:
    """The project's training runs that ran, or are about to run, in a paid sandbox.

    A run that ``open_training_run()`` opened records no agent settings and no task, because the
    caller's own agent does the work, so it does not count. Neither does a stub run.
    """
    live = [AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING]
    return AutoresearchTrainingRun.objects.for_team(team_id).filter(
        Q(task_id__isnull=False) | Q(status__in=live, agent_runtime_adapter__isnull=False)
    )


def _read_flag_payload() -> dict | None:
    try:
        payload = posthoganalytics.get_feature_flag_payload(AUTORESEARCH_FLAG, _PAYLOAD_DISTINCT_ID, match_value=True)
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as error:
        capture_exception(error)
        return None


def _resolve_int(payload: dict | None, team_id: int, key: str, default: int, *, minimum: int) -> int:
    """The first valid value from the team's entry, then the fleet default, then ``default``.

    A value that is not an integer at least ``minimum`` is skipped, so a typo in one layer falls
    through to the next rather than lifting the limit.
    """
    if payload is None:
        return default
    team_configs = payload.get("team_configs")
    layers = [
        team_configs.get(str(team_id)) if isinstance(team_configs, dict) else None,
        payload.get("default_team_config"),
    ]
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        value = layer.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= minimum:
            return value
    return default
