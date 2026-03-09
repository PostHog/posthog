"""
HyperCache verification and auto-fix utilities.

Provides reusable verification logic for Celery tasks that verify cache consistency
and automatically fix issues.
"""

import gc
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings

import structlog
from prometheus_client import Counter

from posthog.models.team.team import Team
from posthog.storage.hypercache_manager import HyperCacheManagementConfig, batch_check_expiry_tracking

logger = structlog.get_logger(__name__)

# Number of batches between progress logs (balance between log spam and visibility)
# With 250 teams/batch and ~238K teams, we have ~950 batches. Logging every 20
# batches gives us ~48 progress logs total.
PROGRESS_LOG_BATCH_INTERVAL = 20

# Prometheus counter for tracking fixes during scheduled verification
HYPERCACHE_VERIFY_FIX_COUNTER = Counter(
    "posthog_hypercache_verify_fixes_total",
    "Cache entries fixed during scheduled verification",
    labelnames=["cache_type", "issue_type"],
)

# Maximum number of team IDs to store for logging
MAX_FIXED_TEAM_IDS_TO_LOG = 10


@dataclass
class VerificationResult:
    """Result of verifying all teams' caches."""

    total: int = 0
    cache_miss_fixed: int = 0
    cache_mismatch_fixed: int = 0
    expiry_missing_fixed: int = 0
    fix_failed: int = 0
    errors: int = 0
    skipped_for_grace_period: int = 0
    fixed_team_ids: list[int] = field(default_factory=list)
    skipped_team_ids: list[int] = field(default_factory=list)

    @property
    def total_fixed(self) -> int:
        return self.cache_miss_fixed + self.cache_mismatch_fixed + self.expiry_missing_fixed

    def formatted_fixed_team_ids(self) -> str:
        """Format fixed_team_ids for logging: first 10 with '... and N more' if truncated."""
        if not self.fixed_team_ids:
            return "[]"
        if len(self.fixed_team_ids) <= MAX_FIXED_TEAM_IDS_TO_LOG:
            return str(self.fixed_team_ids)
        truncated = self.fixed_team_ids[:MAX_FIXED_TEAM_IDS_TO_LOG]
        remaining = len(self.fixed_team_ids) - MAX_FIXED_TEAM_IDS_TO_LOG
        return f"{truncated} ... and {remaining} more"

    def formatted_skipped_team_ids(self) -> str:
        """Format skipped_team_ids for logging: first 10 with '... and N more' if truncated."""
        if not self.skipped_team_ids:
            return "[]"
        if len(self.skipped_team_ids) <= MAX_FIXED_TEAM_IDS_TO_LOG:
            return str(self.skipped_team_ids)
        truncated = self.skipped_team_ids[:MAX_FIXED_TEAM_IDS_TO_LOG]
        remaining = len(self.skipped_team_ids) - MAX_FIXED_TEAM_IDS_TO_LOG
        return f"{truncated} ... and {remaining} more"


def verify_and_fix_all_teams(
    config: HyperCacheManagementConfig,
    verify_team_fn: Callable[[Team, dict | None, dict | None], dict],
    cache_type: str,
    chunk_size: int | None = None,
) -> VerificationResult:
    """
    Verify caches for teams in the configured scope and auto-fix any issues.

    Uses ``config.get_teams_queryset()`` to determine scope — if a queryset
    function is configured, only those teams are processed; otherwise all teams
    are verified, and teams are processed in chunks using seek-based pagination
    for memory efficiency. For each team,
    calls verify_team_fn to check cache consistency. If issues are found,
    automatically fixes them using config.update_fn.

    Args:
        config: HyperCache management configuration with update_fn
        verify_team_fn: Function that takes (team, db_batch_data, cache_batch_data) and returns
            a dict with 'status' ("match", "miss", "mismatch") and 'issue' type
        cache_type: Name for metrics/logging (e.g., "team_metadata", "flags")
        chunk_size: Number of teams to process per batch. Defaults to
            settings.FLAGS_CACHE_VERIFICATION_CHUNK_SIZE (the more conservative setting).

    Returns:
        VerificationResult with stats and list of fixed team IDs
    """
    # Clear any accumulated garbage before starting to maximize available memory.
    # Workers can accumulate memory from previous tasks, and starting clean
    # gives us more headroom for this memory-intensive operation.
    gc.collect()

    if chunk_size is None:
        # Use the more conservative flags setting as default
        chunk_size = settings.FLAGS_CACHE_VERIFICATION_CHUNK_SIZE

    result = VerificationResult()
    last_id = 0

    base_qs = config.get_teams_queryset()

    batch_number = 0
    while True:
        teams = list(
            base_qs.filter(id__gt=last_id).select_related("organization", "project").order_by("id")[:chunk_size]
        )

        if not teams:
            break

        batch_number += 1
        batch_start = result.total
        batch_fixes_start = result.total_fixed

        _verify_and_fix_batch(teams, config, verify_team_fn, cache_type, result)

        batch_verified = result.total - batch_start
        batch_fixed = result.total_fixed - batch_fixes_start

        # Log periodically to avoid log spam while still showing progress
        if batch_number % PROGRESS_LOG_BATCH_INTERVAL == 0:
            logger.info(
                "Verification progress",
                cache_type=cache_type,
                batch_number=batch_number,
                teams_verified_total=result.total,
                teams_fixed_total=result.total_fixed,
                last_team_id=teams[-1].id,
            )
        elif batch_fixed > 0:
            # Always log batches that had fixes
            logger.info(
                "Batch completed with fixes",
                cache_type=cache_type,
                batch_number=batch_number,
                batch_verified=batch_verified,
                batch_fixed=batch_fixed,
                teams_verified_total=result.total,
                teams_fixed_total=result.total_fixed,
            )

        last_id = teams[-1].id

        # Explicitly release memory between batches to prevent accumulation.
        # Python's GC doesn't aggressively return memory to the OS, so without this,
        # memory can accumulate across batches and contribute to OOMs in workers
        # with high baseline memory from other tasks.
        gc.collect()

    return result


def _verify_and_fix_batch(
    teams: list[Team],
    config: HyperCacheManagementConfig,
    verify_team_fn: Callable[[Team, dict | None, dict | None], dict],
    cache_type: str,
    result: VerificationResult,
) -> None:
    """
    Verify and fix a batch of teams.

    Args:
        teams: List of Team objects to verify
        config: HyperCache management configuration
        verify_team_fn: Function to verify a single team (team, db_batch_data, cache_batch_data)
        cache_type: Name for metrics/logging
        result: VerificationResult to accumulate stats
    """
    # Batch-read cached values using MGET (single Redis round trip)
    try:
        cache_batch_data = config.hypercache.batch_get_from_cache(teams)
    except Exception as e:
        logger.warning("Batch cache read failed, falling back to individual lookups", error=str(e))
        cache_batch_data = {}

    # Batch-check expiry tracking
    expiry_status = batch_check_expiry_tracking(teams, config)

    # Batch-check which teams should skip fixes (e.g., grace period for recently updated flags)
    # This is done once per batch to avoid N+1 queries
    team_ids_to_skip_fix: set[int] = set()
    if config.get_team_ids_to_skip_fix_fn:
        try:
            team_ids_to_skip_fix = config.get_team_ids_to_skip_fix_fn([t.id for t in teams])
        except Exception as e:
            logger.warning("Batch skip-fix check failed, proceeding without skips", error=str(e))

    # Batch-load DB data for all teams in the batch
    db_batch_data = None
    if config.hypercache.batch_load_fn:
        try:
            db_batch_data = config.hypercache.batch_load_fn(teams)
        except Exception as e:
            logger.warning("Batch load failed, falling back to individual loads", error=str(e))

    for team in teams:
        result.total += 1

        try:
            verification = verify_team_fn(team, db_batch_data, cache_batch_data)
        except Exception as e:
            result.errors += 1
            logger.exception("Error verifying team", team_id=team.id, error=str(e))
            continue

        # Ensure db_data is available for cache fixes even if the verify
        # function didn't include it. This avoids a redundant per-team DB
        # query inside _fix_and_record.
        if "db_data" not in verification and db_batch_data:
            db_data = db_batch_data.get(team.id)
            if db_data is not None:
                verification["db_data"] = db_data

        status = verification["status"]

        # Determine issue type (if any)
        issue_type: str | None = None
        if status == "miss":
            issue_type = "cache_miss"
        elif status == "mismatch":
            issue_type = "cache_mismatch"
        elif status == "match":
            # Check expiry tracking for teams with valid cache
            identifier = config.hypercache.get_cache_identifier(team)
            if expiry_status and not expiry_status.get(identifier, True):
                issue_type = "expiry_missing"

        if issue_type:
            # Check if we should skip fixing (e.g., grace period for recently updated flags)
            if team.id in team_ids_to_skip_fix:
                result.skipped_for_grace_period += 1
                if len(result.skipped_team_ids) < MAX_FIXED_TEAM_IDS_TO_LOG:
                    result.skipped_team_ids.append(team.id)
                logger.debug(
                    "Skipping fix due to grace period",
                    team_id=team.id,
                    issue_type=issue_type,
                    cache_type=cache_type,
                )
                continue

            _fix_and_record(
                team=team,
                config=config,
                issue_type=issue_type,
                cache_type=cache_type,
                result=result,
                verification=verification,
            )


def _fix_and_record(
    *,
    team: Team,
    config: HyperCacheManagementConfig,
    issue_type: str,
    cache_type: str,
    result: VerificationResult,
    verification: dict,
) -> None:
    """
    Fix a team's cache and record the result.

    Args:
        team: Team to fix
        config: HyperCache management configuration
        issue_type: Type of issue (cache_miss, cache_mismatch, expiry_missing)
        cache_type: Cache type for metrics
        result: VerificationResult to update
        verification: Verification result dict containing diff info.
            If it contains a "db_data" key, that data is written directly to
            cache to avoid a redundant DB query.
    """
    # Log what's being fixed, including diff details for mismatches
    log_kwargs: dict = {"team_id": team.id, "issue_type": issue_type, "cache_type": cache_type}
    if "diff_fields" in verification:
        log_kwargs["diff_fields"] = verification["diff_fields"]
    if "diff_flags" in verification:
        log_kwargs["diff_flags"] = verification["diff_flags"]
    logger.info("Fixing cache entry", **log_kwargs)

    try:
        # Use preloaded db_data if available to avoid redundant DB query
        if "db_data" in verification:
            config.hypercache.set_cache_value(team, verification["db_data"])
            success = True
        else:
            success = config.update_fn(team)
    except Exception as e:
        success = False
        logger.exception("Error fixing cache", team_id=team.id, issue_type=issue_type, error=str(e))

    if success:
        # Increment appropriate counter
        if issue_type == "cache_miss":
            result.cache_miss_fixed += 1
        elif issue_type == "cache_mismatch":
            result.cache_mismatch_fixed += 1
        elif issue_type == "expiry_missing":
            result.expiry_missing_fixed += 1

        result.fixed_team_ids.append(team.id)

        # Update Prometheus metric
        HYPERCACHE_VERIFY_FIX_COUNTER.labels(cache_type=cache_type, issue_type=issue_type).inc()
    else:
        result.fix_failed += 1


def _run_verification_for_cache(
    config: HyperCacheManagementConfig,
    verify_team_fn: Callable[[Team, dict | None, dict | None], dict],
    cache_type: str,
    chunk_size: int,
) -> VerificationResult:
    """
    Run verification for a single cache type and log results.

    Args:
        config: HyperCache management configuration
        verify_team_fn: Function to verify a single team
        cache_type: Name for metrics/logging
        chunk_size: Number of teams to process per batch

    Returns:
        VerificationResult with stats
    """
    start_time = time.time()
    logger.info(f"Starting {cache_type} cache verification", chunk_size=chunk_size)

    result = verify_and_fix_all_teams(
        config=config,
        verify_team_fn=verify_team_fn,
        cache_type=cache_type,
        chunk_size=chunk_size,
    )

    duration = time.time() - start_time

    log_kwargs: dict = {
        "cache_type": cache_type,
        "teams_verified": result.total,
        "teams_fixed": result.total_fixed,
        "cache_miss_fixed": result.cache_miss_fixed,
        "cache_mismatch_fixed": result.cache_mismatch_fixed,
        "expiry_missing_fixed": result.expiry_missing_fixed,
        "fix_failures": result.fix_failed,
        "errors": result.errors,
        "fixed_team_ids": result.formatted_fixed_team_ids(),
        "duration_seconds": duration,
    }

    # Only include skipped info if there were skips (keeps logs clean for caches without grace period)
    if result.skipped_for_grace_period > 0:
        log_kwargs["skipped_for_grace_period"] = result.skipped_for_grace_period
        log_kwargs["skipped_team_ids"] = result.formatted_skipped_team_ids()

    logger.info(f"Completed {cache_type} cache verification", **log_kwargs)

    return result
