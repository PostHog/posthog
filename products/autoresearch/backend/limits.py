"""
Autoresearch project-level limits and daily budget enforcement.

Autoresearch backlog id: A119 and A120.

Resolves per-project limits from the ``autoresearch`` feature flag JSON payload
across three layers, most-specific first:
1. ``team_configs["<team_id>"]`` (per-team override)
2. ``default_team_config`` (fleet-wide default)
3. Code constants (last-resort defaults)

Provides:
- Advisory-locked daily run cap checks in a rolling 24-hour window across all pipelines in a team.
- Advisory-locked live pipeline cap checks (bootstrapping, running, converged).
- Caps on iteration budgets for sandbox runs.
- Summary reports for UI and API consumption.
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
from products.autoresearch.backend.models import AutoresearchPipeline, AutoresearchTrainingRun

logger = structlog.get_logger(__name__)

AUTORESEARCH_FLAG = "autoresearch"
AUTORESEARCH_LIMITS_DISTINCT_ID = "internal_autoresearch_limits"

DEFAULT_MAX_TRAINING_RUNS_PER_DAY = 3
DEFAULT_MAX_ITERATIONS_PER_RUN = 10
DEFAULT_MAX_LIVE_PIPELINES = 3
DAILY_CAP_WINDOW = timedelta(hours=24)

# 32-bit namespace keys for PostgreSQL transaction-scoped advisory locks: pg_advisory_xact_lock(key1, team_id)
_AUTORESEARCH_TEAM_CAP_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"autoresearch_team_training_cap").digest()[:4], "big", signed=True
)
_AUTORESEARCH_TEAM_PIPELINES_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"autoresearch_team_live_pipelines_cap").digest()[:4], "big", signed=True
)

LIVE_PIPELINE_STATUSES = (
    AutoresearchPipeline.Status.BOOTSTRAPPING,
    AutoresearchPipeline.Status.RUNNING,
    AutoresearchPipeline.Status.CONVERGED,
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


class LivePipelineCapExceeded(Exception):
    """Raised when a project already has max_live_pipelines active models."""

    def __init__(self, count: int, limit: int) -> None:
        self.count = count
        self.limit = limit
        super().__init__(
            f"This project already has {limit} active models. Pause or archive one to start another."
        )


@frozen
class AutoresearchLimits:
    """Resolved limits for a project."""

    max_training_runs_per_day: int = DEFAULT_MAX_TRAINING_RUNS_PER_DAY
    max_iterations_per_run: int = DEFAULT_MAX_ITERATIONS_PER_RUN
    max_live_pipelines: int = DEFAULT_MAX_LIVE_PIPELINES


@frozen
class AutoresearchLimitsReport:
    """Read-only view of a project's limits, current usage, and slot availability."""

    max_training_runs_per_day: int
    max_iterations_per_run: int
    max_live_pipelines: int
    training_runs_used_today: int
    live_pipelines_count: int
    next_training_slot_opens_at: datetime | None
    daily_training_cap_exceeded: bool
    live_pipelines_cap_exceeded: bool


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
    max_live = _resolve_int(
        team_cfg.get("max_live_pipelines"),
        default_cfg.get("max_live_pipelines"),
        default=DEFAULT_MAX_LIVE_PIPELINES,
    )

    return AutoresearchLimits(
        max_training_runs_per_day=max_runs,
        max_iterations_per_run=max_iterations,
        max_live_pipelines=max_live,
    )


def acquire_team_training_lock(team_id: int) -> None:
    """Take a transaction-scoped advisory lock on (training_cap_key, team_id). Released at transaction end."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_AUTORESEARCH_TEAM_CAP_LOCK_KEY, team_id])


def acquire_team_pipelines_lock(team_id: int) -> None:
    """Take a transaction-scoped advisory lock on (pipelines_cap_key, team_id). Released at transaction end."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_AUTORESEARCH_TEAM_PIPELINES_LOCK_KEY, team_id])


def enforce_live_pipelines_cap(
    team_id: int,
    *,
    payload: dict | None = None,
) -> tuple[int, int]:
    """
    Check and enforce the live pipelines cap for a team.

    Must be called inside an open transaction. Takes an advisory lock keyed on team_id to
    prevent concurrent requests from exceeding the cap.
    Counts pipelines with status bootstrapping, running, or converged.
    Draft, paused, and archived do not count.

    Raises LivePipelineCapExceeded if the team is already at or above the cap.
    Returns (live_count, cap).
    """
    acquire_team_pipelines_lock(team_id)

    limits = resolve_autoresearch_limits(team_id, payload=payload)
    cap = limits.max_live_pipelines

    live_count = (
        AutoresearchPipeline.objects.for_team(team_id)
        .filter(status__in=LIVE_PIPELINE_STATUSES)
        .count()
    )

    if live_count >= cap:
        raise LivePipelineCapExceeded(count=live_count, limit=cap)

    return live_count, cap


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


def get_team_limits_report(
    team_id: int,
    *,
    now: datetime | None = None,
    payload: dict | None = None,
) -> AutoresearchLimitsReport:
    """Read-only limits and current usage report without taking write locks."""
    now_dt = now or django_timezone.now()
    limits = resolve_autoresearch_limits(team_id, payload=payload)

    window_start = now_dt - DAILY_CAP_WINDOW
    qs = AutoresearchTrainingRun.objects.for_team(team_id).filter(created_at__gte=window_start)
    qs = qs.filter(
        Q(task_id__isnull=False)
        | Q(status__in=[AutoresearchTrainingRun.Status.PENDING, AutoresearchTrainingRun.Status.RUNNING])
    )
    qs = qs.exclude(task_id__isnull=True, agent_runtime_adapter__isnull=True)
    qs = qs.exclude(task_id__isnull=True, agent_runtime_adapter="")

    runs_in_window = list(qs.order_by("created_at"))
    runs_count = len(runs_in_window)
    daily_cap_exceeded = runs_count >= limits.max_training_runs_per_day

    next_slot: datetime | None = None
    if daily_cap_exceeded and runs_in_window:
        oldest_run = runs_in_window[0]
        next_slot = oldest_run.created_at + DAILY_CAP_WINDOW
        if next_slot <= now_dt:
            next_slot = now_dt + timedelta(seconds=1)

    live_count = (
        AutoresearchPipeline.objects.for_team(team_id)
        .filter(status__in=LIVE_PIPELINE_STATUSES)
        .count()
    )
    live_cap_exceeded = live_count >= limits.max_live_pipelines

    return AutoresearchLimitsReport(
        max_training_runs_per_day=limits.max_training_runs_per_day,
        max_iterations_per_run=limits.max_iterations_per_run,
        max_live_pipelines=limits.max_live_pipelines,
        training_runs_used_today=runs_count,
        live_pipelines_count=live_count,
        next_training_slot_opens_at=next_slot,
        daily_training_cap_exceeded=daily_cap_exceeded,
        live_pipelines_cap_exceeded=live_cap_exceeded,
    )
