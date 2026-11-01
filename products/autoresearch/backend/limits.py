"""
Autoresearch project-level limits and daily budget enforcement.

Autoresearch backlog id: A119.

Resolves per-project limits from the ``autoresearch`` feature flag JSON payload
across three layers, most-specific first:
1. ``team_configs["<team_id>"]`` (per-team override)
2. ``default_team_config`` (fleet-wide default)
3. Code constants (last-resort defaults)

Provides advisory-locked daily run cap checks in a rolling 24-hour window across all
pipelines in a team, and caps iteration budgets for sandbox runs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from typing import Any

from django.db import connection
from django.db.models import Q
from django.utils import timezone as django_timezone

import posthoganalytics
import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from products.autoresearch.backend.models import AutoresearchTrainingRun

logger = structlog.get_logger(__name__)

AUTORESEARCH_FLAG = "autoresearch"
AUTORESEARCH_LIMITS_DISTINCT_ID = "internal_autoresearch_limits"

DEFAULT_MAX_TRAINING_RUNS_PER_DAY = 3
DEFAULT_MAX_ITERATIONS_PER_RUN = 10
DAILY_CAP_WINDOW = timedelta(hours=24)

# 32-bit namespace key for PostgreSQL transaction-scoped advisory lock: pg_advisory_xact_lock(key1, team_id)
_AUTORESEARCH_TEAM_CAP_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"autoresearch_team_training_cap").digest()[:4], "big", signed=True
)


class DailyTrainingCapExceeded(Exception):
    """Raised when a team has reached its rolling 24-hour sandbox training run limit."""

    def __init__(self, runs_used: int, limit: int, next_slot_opens_at: datetime) -> None:
        self.runs_used = runs_used
        self.limit = limit
        self.next_slot_opens_at = next_slot_opens_at
        super().__init__(
            f"Daily training run limit reached for this project ({runs_used}/{limit}). "
            f"Next slot opens at {next_slot_opens_at.isoformat()}."
        )


@frozen
class AutoresearchLimits:
    """Resolved limits for a project."""

    max_training_runs_per_day: int = DEFAULT_MAX_TRAINING_RUNS_PER_DAY
    max_iterations_per_run: int = DEFAULT_MAX_ITERATIONS_PER_RUN
    max_live_pipelines: int | None = None


def read_flag_payload(
    flag_key: str = AUTORESEARCH_FLAG, distinct_id: str = AUTORESEARCH_LIMITS_DISTINCT_ID
) -> dict | None:
    """Read and defensively parse the feature flag JSON payload for the synthetic discovery distinct ID."""
    try:
        payload = posthoganalytics.get_feature_flag_payload(flag_key, distinct_id, match_value=True)
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as error:
        capture_exception(error)
        return None


def _resolve_int(*values: Any, default: int) -> int:
    for v in values:
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            return v
    return default


def _resolve_optional_int(*values: Any, default: int | None = None) -> int | None:
    for v in values:
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            return v
    return default


def resolve_autoresearch_limits(team_id: int, payload: dict | None = None) -> AutoresearchLimits:
    """
    Resolve limits for a project from the flag payload in three layers:
    team_configs[team_id] -> default_team_config -> code constants.
    """
    if payload is None:
        payload = read_flag_payload()

    team_configs = payload.get("team_configs") if isinstance(payload, dict) else None
    team_cfg = None
    if isinstance(team_configs, dict):
        team_cfg = team_configs.get(str(team_id)) or team_configs.get(team_id)
    team_cfg = team_cfg if isinstance(team_cfg, dict) else {}

    default_cfg = payload.get("default_team_config") if isinstance(payload, dict) else None
    default_cfg = default_cfg if isinstance(default_cfg, dict) else {}

    max_runs = _resolve_int(
        team_cfg.get("max_training_runs_per_day"),
        default_cfg.get("max_training_runs_per_day"),
        default=DEFAULT_MAX_TRAINING_RUNS_PER_DAY,
    )
    max_iterations = _resolve_int(
        team_cfg.get("max_iterations_per_run"),
        default_cfg.get("max_iterations_per_run"),
        default=DEFAULT_MAX_ITERATIONS_PER_RUN,
    )
    max_live = _resolve_optional_int(
        team_cfg.get("max_live_pipelines"),
        default_cfg.get("max_live_pipelines"),
        default=None,
    )

    return AutoresearchLimits(
        max_training_runs_per_day=max_runs,
        max_iterations_per_run=max_iterations,
        max_live_pipelines=max_live,
    )


def acquire_team_training_lock(team_id: int) -> None:
    """Take a transaction-scoped advisory lock on (namespace_key, team_id). Released at transaction end."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_AUTORESEARCH_TEAM_CAP_LOCK_KEY, team_id])


def enforce_team_training_daily_cap(
    team_id: int,
    *,
    now: datetime | None = None,
    payload: dict | None = None,
    raise_error: bool = False,
) -> tuple[bool, int, int, datetime | None]:
    """
    Check and enforce the rolling 24-hour sandbox training run cap for a team.

    Must be called inside an open transaction holding the pipeline row lock.
    Takes an advisory lock keyed on team_id to serialize concurrent pipelines in the same project.
    Counts all sandbox training runs (with task_id or pending/running), excluding external runs.

    Returns (allowed, runs_used, limit, next_slot_opens_at).
    If raise_error is True and the cap is reached, raises DailyTrainingCapExceeded.
    """
    acquire_team_training_lock(team_id)

    now_dt = now or django_timezone.now()
    limits = resolve_autoresearch_limits(team_id, payload=payload)
    cap = limits.max_training_runs_per_day

    window_start = now_dt - DAILY_CAP_WINDOW
    qs = AutoresearchTrainingRun.objects.for_team(team_id).filter(created_at__gte=window_start)

    # All sandbox training runs: has a task_id OR is currently pending/running
    qs = qs.filter(
        Q(task_id__isnull=False)
        | Q(status__in=[AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING])
    )

    # Exclude external runs opened via open_training_run() (they run on caller's agent, no task_id or adapter)
    qs = qs.exclude(task_id__isnull=True, agent_runtime_adapter__isnull=True)
    qs = qs.exclude(task_id__isnull=True, agent_runtime_adapter="")

    runs_in_window = list(qs.order_by("created_at"))
    runs_count = len(runs_in_window)

    if runs_count >= cap:
        oldest_run = runs_in_window[0]
        next_slot = oldest_run.created_at + DAILY_CAP_WINDOW
        if next_slot <= now_dt:
            next_slot = now_dt + timedelta(seconds=1)

        if raise_error:
            raise DailyTrainingCapExceeded(runs_used=runs_count, limit=cap, next_slot_opens_at=next_slot)
        return False, runs_count, cap, next_slot

    return True, runs_count, cap, None
