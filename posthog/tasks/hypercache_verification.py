"""
Celery tasks for HyperCache verification.

Provides separate tasks for verifying and fixing each HyperCache-backed cache
(flags, flag definitions, team metadata). Split into separate tasks to:
- Give each cache its own time budget (avoiding timeouts)
- Enable independent monitoring and metrics
- Allow parallel execution when workers are available
- Isolate failures so one cache's issues don't affect the other
"""

import time
from typing import Literal, get_args

from django.conf import settings
from django.core.cache import cache as django_cache

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import Counter

from posthog.celery_task_names import (
    VERIFY_FLAG_DEFINITIONS_CACHE_TASK_NAME,
    VERIFY_FLAGS_CACHE_TASK_NAME,
    VERIFY_TEAM_METADATA_CACHE_TASK_NAME,
)
from posthog.exceptions_capture import capture_exception
from posthog.storage.hypercache_manager import HyperCacheManagementConfig
from posthog.storage.hypercache_verifier import (
    HYPERCACHE_VERIFY_FIX_COUNTER,
    TeamBatchFetchError,
    VerifyTeamFn,
    _run_verification_for_cache,
)
from posthog.tasks.utils import CeleryQueue, PushGatewayTask

from products.feature_flags.backend.local_evaluation import (
    FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
    verify_team_flag_definitions,
)

logger = structlog.get_logger(__name__)

CacheType = Literal["flags", "team_metadata"]

# Each task locks for its own hard time limit, passed in as ``self.time_limit``. A
# crashed task that never runs its finally block still releases the lock when the
# timeout expires. The timeout is measured from lock acquisition, and every task's
# hard limit is <= its schedule interval, so under on-time scheduling that expiry
# lands before the next scheduled run and a crash skips no runs. A run that starts
# late enough for its lock to outlive the next tick skips at most one run.

# Wind the sweep down this long before the soft time limit, so the batch-boundary
# deadline check trips before Celery's SoftTimeLimitExceeded can fire mid-batch. Must
# exceed one batch's processing time (1-3s in prod); 2 minutes leaves wide margin
# while giving up little of the time budget.
DEADLINE_HEADROOM_SECONDS = 2 * 60

FLAG_DEFINITIONS_CACHE_TYPE = "flag_definitions"

# Both "deadline" and "soft_time_limit" are expected wind-downs recorded for
# observability only. "deadline" is the graceful path: the sweep hit its own
# monotonic deadline and stopped at a batch boundary — the healthy steady state.
# "soft_time_limit" means Celery's soft-limit signal fired first, so the deadline
# was too loose to wind down in time; a rise here says the budget needs tuning.
# "db_unreachable" and "error" drive the FlagsCacheVerificationRepeatedGiveUps
# alert in PostHog/charts.
IncompleteRunReason = Literal["db_unreachable", "error", "soft_time_limit", "deadline"]

# Verification runs that wound down before completing their sweep, by reason.
HYPERCACHE_VERIFICATION_INCOMPLETE_RUNS_COUNTER = Counter(
    "posthog_hypercache_verification_incomplete_runs_total",
    "Hypercache verification runs that wound down before completing the sweep",
    labelnames=["cache_type", "reason"],
)

# Pre-create every label pair so zero-valued series exist from worker boot: increase()
# never misses a series' first increment, and alert expressions can be validated
# against live series before any incident occurs.
for _cache_type in (*get_args(CacheType), FLAG_DEFINITIONS_CACHE_TYPE):
    for _reason in get_args(IncompleteRunReason):
        HYPERCACHE_VERIFICATION_INCOMPLETE_RUNS_COUNTER.labels(cache_type=_cache_type, reason=_reason)

_FIX_ISSUE_TYPES = ("cache_miss", "cache_mismatch", "expiry_missing")
# Only the flags cache has a second writer (the Rust Kafka builder); the other
# caches are Python-written, so pre-creating rust/unknown series for them would
# publish zero-valued series that can never increment.
_FIX_WRITERS_BY_CACHE_TYPE = {
    cache_type: ("python", "rust", "unknown") if cache_type == "flags" else ("python",)
    for cache_type in (*get_args(CacheType), FLAG_DEFINITIONS_CACHE_TYPE)
}
# Same pre-creation rationale as above. It matters most for writer="rust": a
# rust-attributed fix is the rare parity signal the Kafka-builder ramp gates on,
# and its first increment must not be invisible to increase().
for _cache_type, _writers in _FIX_WRITERS_BY_CACHE_TYPE.items():
    for _issue_type in _FIX_ISSUE_TYPES:
        for _writer in _writers:
            HYPERCACHE_VERIFY_FIX_COUNTER.labels(cache_type=_cache_type, issue_type=_issue_type, writer=_writer)


def _record_incomplete_run(cache_type: str, reason: IncompleteRunReason) -> None:
    HYPERCACHE_VERIFICATION_INCOMPLETE_RUNS_COUNTER.labels(cache_type=cache_type, reason=reason).inc()


def _log_batch_fetch_exhausted(cache_type: str, start_time: float, error: TeamBatchFetchError) -> None:
    # Not a code failure: Postgres stayed unreachable across retries, so the run
    # winds down. Unverified teams are picked up on the next scheduled cycle.
    logger.warning(
        "Cache verification wound down early, database unreachable",
        cache_type=cache_type,
        duration_seconds=time.time() - start_time,
        error=str(error),
    )


def _log_soft_time_limit_exceeded(cache_type: str, start_time: float) -> None:
    # Not a failure: the run wound down early because it ran out of time.
    # Unverified teams are picked up on the next scheduled cycle.
    logger.warning(
        "Cache verification wound down early, time limit reached",
        cache_type=cache_type,
        duration_seconds=time.time() - start_time,
    )


def _execute_verification_run(
    config: HyperCacheManagementConfig,
    verify_team_fn: VerifyTeamFn,
    cache_type: str,
    chunk_size: int,
    soft_limit_seconds: float,
) -> None:
    """Run one verification sweep, classifying early wind-downs vs real failures.

    The sweep gets a monotonic deadline ``DEADLINE_HEADROOM_SECONDS`` before the soft
    time limit, so it winds down at a batch boundary and reports the deferral before
    Celery's SoftTimeLimitExceeded fires mid-batch (recorded as ``soft_time_limit``)
    or the hard time limit SIGKILLs the worker (which reports nothing).
    """
    start_time = time.time()
    stop_time = time.monotonic() + max(soft_limit_seconds - DEADLINE_HEADROOM_SECONDS, 0)

    try:
        result = _run_verification_for_cache(
            config=config,
            verify_team_fn=verify_team_fn,
            cache_type=cache_type,
            chunk_size=chunk_size,
            stop_time=stop_time,
        )
    except SoftTimeLimitExceeded:
        _record_incomplete_run(cache_type, "soft_time_limit")
        _log_soft_time_limit_exceeded(cache_type, start_time)
        return
    except TeamBatchFetchError as e:
        _record_incomplete_run(cache_type, "db_unreachable")
        _log_batch_fetch_exhausted(cache_type, start_time, e)
        return
    except Exception as e:
        _record_incomplete_run(cache_type, "error")
        logger.exception("Failed cache verification", cache_type=cache_type, error=str(e))
        capture_exception(e)
        raise

    # A deadline wind-down returns normally (no SoftTimeLimitExceeded raised). Record it
    # under its own reason so the metric distinguishes the graceful path from Celery's
    # soft-limit firing first (which means the deadline was too loose).
    if result.wound_down_early:
        _record_incomplete_run(cache_type, "deadline")

    logger.info("Completed cache verification", cache_type=cache_type, duration_seconds=time.time() - start_time)


def _run_flag_definitions_verification(soft_limit_seconds: float, lock_timeout_seconds: float) -> None:
    """
    Run verification for the flag definitions cache.

    Acquires a distributed lock so overlapping scheduled runs skip instead of
    duplicating work.

    Note: Unlike the flags cache (which uses FLAGS_REDIS_URL), the flag definitions
    cache uses the default cache backend (REDIS_URL). No special guard needed since
    Django's default cache is always available.
    """
    lock_key = f"posthog:hypercache_verification:{FLAG_DEFINITIONS_CACHE_TYPE}:lock"

    if not django_cache.add(lock_key, "locked", timeout=lock_timeout_seconds):
        logger.info("Skipping cache verification - already running", cache_type=FLAG_DEFINITIONS_CACHE_TYPE)
        return

    try:
        logger.info("Starting cache verification", cache_type=FLAG_DEFINITIONS_CACHE_TYPE)
        _execute_verification_run(
            config=FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
            verify_team_fn=verify_team_flag_definitions,
            cache_type=FLAG_DEFINITIONS_CACHE_TYPE,
            chunk_size=settings.FLAGS_CACHE_VERIFICATION_CHUNK_SIZE,
            soft_limit_seconds=soft_limit_seconds,
        )
    finally:
        django_cache.delete(lock_key)


def _run_cache_verification(
    cache_type: CacheType, chunk_size: int, soft_limit_seconds: float, lock_timeout_seconds: float
) -> None:
    """
    Run verification for a specific cache type.

    Shared logic for all HyperCache verification tasks. Handles:
    - Early exit if FLAGS_REDIS_URL not configured
    - Distributed lock to prevent concurrent executions
    - Importing cache-specific config and verify function
    - Running verification with timing and error handling
    """
    # Check Redis URL first to avoid holding a lock when no work will be done
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping cache verification", cache_type=cache_type)
        return

    lock_key = f"posthog:hypercache_verification:{cache_type}:lock"

    # Attempt to acquire lock - cache.add returns False if key already exists
    if not django_cache.add(lock_key, "locked", timeout=lock_timeout_seconds):
        logger.info("Skipping cache verification - already running", cache_type=cache_type)
        return

    try:
        logger.info("Starting cache verification", cache_type=cache_type, chunk_size=chunk_size)

        # Import cache-specific config and verify function
        if cache_type == "flags":
            from products.feature_flags.backend.flags_cache import (
                FLAGS_HYPERCACHE_MANAGEMENT_CONFIG as config,
                verify_team_flags as verify_fn,
            )
        else:
            from posthog.storage.team_metadata_cache import (
                TEAM_HYPERCACHE_MANAGEMENT_CONFIG as config,
                verify_team_metadata as verify_fn,
            )

        _execute_verification_run(
            config=config,
            verify_team_fn=verify_fn,
            cache_type=cache_type,
            chunk_size=chunk_size,
            soft_limit_seconds=soft_limit_seconds,
        )
    finally:
        django_cache.delete(lock_key)


@shared_task(
    bind=True,
    base=PushGatewayTask,
    ignore_result=True,
    name=VERIFY_FLAGS_CACHE_TASK_NAME,
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    soft_time_limit=25 * 60,  # 25 min soft limit
    time_limit=28 * 60,  # 28 min hard limit (< the 30 min schedule; also the lock timeout)
)
def verify_and_fix_flags_cache_task(self: PushGatewayTask) -> None:
    """
    Periodic task to verify the flags HyperCache and fix issues.

    Runs every 30 minutes. Verifies all teams' flags caches, automatically
    fixing any cache misses, mismatches, or expiry tracking issues.
    Uses a distributed lock to skip execution if a previous run is still in progress.

    Expected duration: ~8 minutes (observed 2026-08-21); the hard limit stays under the
    30-minute schedule so a run always finishes before the next one is due.

    Metrics: posthog_hypercache_verify_fixes_total{cache_type="flags", issue_type="...", writer="..."},
    posthog_hypercache_verification_incomplete_runs_total{cache_type="flags", reason="..."}
    """
    _run_cache_verification(
        "flags", settings.FLAGS_CACHE_VERIFICATION_CHUNK_SIZE, self.soft_time_limit, self.time_limit
    )


@shared_task(
    bind=True,
    base=PushGatewayTask,
    ignore_result=True,
    name=VERIFY_TEAM_METADATA_CACHE_TASK_NAME,
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    soft_time_limit=35 * 60,  # 35 min soft limit
    time_limit=40 * 60,  # 40 min hard limit (< the hourly schedule; also the lock timeout)
)
def verify_and_fix_team_metadata_cache_task(self: PushGatewayTask) -> None:
    """
    Periodic task to verify the team metadata HyperCache and fix issues.

    Runs hourly at minute 20. Verifies all teams' metadata caches,
    automatically fixing any cache misses, mismatches, or expiry tracking issues.
    Uses a distributed lock to skip execution if a previous run is still in progress.

    Expected duration: ~15-20 minutes (observed 2026-08-19).

    Metrics: posthog_hypercache_verify_fixes_total{cache_type="team_metadata", issue_type="..."},
    posthog_hypercache_verification_incomplete_runs_total{cache_type="team_metadata", reason="..."}
    """
    _run_cache_verification(
        "team_metadata", settings.TEAM_METADATA_CACHE_VERIFICATION_CHUNK_SIZE, self.soft_time_limit, self.time_limit
    )


@shared_task(
    bind=True,
    base=PushGatewayTask,
    ignore_result=True,
    name=VERIFY_FLAG_DEFINITIONS_CACHE_TASK_NAME,
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    soft_time_limit=35 * 60,  # 35 min soft limit
    time_limit=40 * 60,  # 40 min hard limit (< the hourly schedule; also the lock timeout)
)
def verify_and_fix_flag_definitions_cache_task(self: PushGatewayTask) -> None:
    """
    Periodic task to verify the flag definitions HyperCache and fix issues.

    Runs hourly at minute 50. Verifies all teams' flag definitions cache entries,
    fixing cache misses, mismatches, or expiry tracking issues.

    Uses a distributed lock to skip execution if a previous run is still in progress.

    Expected duration: was pinned at its old 30-minute hard limit in prod (observed
    2026-08-21), so the budget is now 35/40 min; the sweep still winds down gracefully
    at the deadline if it runs long, and the every-minute self-heal drain covers gaps.

    Metrics: posthog_hypercache_verify_fixes_total{cache_type="flag_definitions", issue_type="..."},
    posthog_hypercache_verification_incomplete_runs_total{cache_type="flag_definitions", reason="..."}
    """
    _run_flag_definitions_verification(self.soft_time_limit, self.time_limit)
