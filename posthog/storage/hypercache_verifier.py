"""
HyperCache verification and auto-fix utilities.

Provides reusable verification logic for Celery tasks that verify cache consistency
and automatically fix issues.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field

import structlog
from prometheus_client import Counter

from posthog.models.team.team import Team
from posthog.storage.hypercache_manager import HyperCacheManagementConfig, batch_check_expiry_tracking

logger = structlog.get_logger(__name__)

# Default chunk size for batch processing, configurable via environment variable
DEFAULT_VERIFICATION_CHUNK_SIZE = int(os.environ.get("HYPERCACHE_VERIFICATION_CHUNK_SIZE", "1000"))

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
    fixed_team_ids: list[int] = field(default_factory=list)

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


def verify_and_fix_all_teams(
    config: HyperCacheManagementConfig,
    verify_team_fn: Callable[[Team, dict | None], dict],
    cache_type: str,
    chunk_size: int | None = None,
) -> VerificationResult:
    """
    Verify all teams' caches and auto-fix any issues.

    Processes teams in chunks using seek-based pagination for memory efficiency.
    For each team, calls verify_team_fn to check cache consistency. If issues
    are found, automatically fixes them using config.update_fn.

    Args:
        config: HyperCache management configuration with update_fn
        verify_team_fn: Function that takes (team, batch_data) and returns
            a dict with 'status' ("match", "miss", "mismatch") and 'issue' type
        cache_type: Name for metrics/logging (e.g., "team_metadata", "flags")
        chunk_size: Number of teams to process per batch. Defaults to
            HYPERCACHE_VERIFICATION_CHUNK_SIZE env var or 1000.

    Returns:
        VerificationResult with stats and list of fixed team IDs
    """
    if chunk_size is None:
        chunk_size = DEFAULT_VERIFICATION_CHUNK_SIZE

    result = VerificationResult()
    last_id = 0

    while True:
        teams = list(
            Team.objects.filter(id__gt=last_id).select_related("organization", "project").order_by("id")[:chunk_size]
        )

        if not teams:
            break

        _verify_and_fix_batch(teams, config, verify_team_fn, cache_type, result)

        last_id = teams[-1].id

    return result


def _verify_and_fix_batch(
    teams: list[Team],
    config: HyperCacheManagementConfig,
    verify_team_fn: Callable[[Team, dict | None], dict],
    cache_type: str,
    result: VerificationResult,
) -> None:
    """
    Verify and fix a batch of teams.

    Args:
        teams: List of Team objects to verify
        config: HyperCache management configuration
        verify_team_fn: Function to verify a single team
        cache_type: Name for metrics/logging
        result: VerificationResult to accumulate stats
    """
    # Batch-load data if supported
    batch_data = None
    if config.hypercache.batch_load_fn:
        try:
            batch_data = config.hypercache.batch_load_fn(teams)
        except Exception as e:
            logger.warning("Batch load failed, falling back to individual loads", error=str(e))

    # Batch-check expiry tracking
    expiry_status = batch_check_expiry_tracking(teams, config)

    for team in teams:
        result.total += 1

        try:
            verification = verify_team_fn(team, batch_data)
        except Exception as e:
            result.errors += 1
            logger.exception("Error verifying team", team_id=team.id, error=str(e))
            continue

        status = verification["status"]

        if status == "match":
            # Check expiry tracking for teams with valid cache
            identifier = config.hypercache.get_cache_identifier(team)
            if expiry_status and not expiry_status.get(identifier, True):
                _fix_and_record(
                    team=team,
                    config=config,
                    issue_type="expiry_missing",
                    cache_type=cache_type,
                    result=result,
                )

        elif status == "miss":
            _fix_and_record(
                team=team,
                config=config,
                issue_type="cache_miss",
                cache_type=cache_type,
                result=result,
            )

        elif status == "mismatch":
            _fix_and_record(
                team=team,
                config=config,
                issue_type="cache_mismatch",
                cache_type=cache_type,
                result=result,
                verification=verification,
            )


def _fix_and_record(
    team: Team,
    config: HyperCacheManagementConfig,
    issue_type: str,
    cache_type: str,
    result: VerificationResult,
    verification: dict | None = None,
) -> None:
    """
    Fix a team's cache and record the result.

    Args:
        team: Team to fix
        config: HyperCache management configuration
        issue_type: Type of issue (cache_miss, cache_mismatch, expiry_missing)
        cache_type: Cache type for metrics
        result: VerificationResult to update
        verification: Optional verification result dict containing diff info
    """
    # Log what's being fixed, including diff details for mismatches
    log_kwargs: dict = {"team_id": team.id, "issue_type": issue_type, "cache_type": cache_type}
    if verification:
        if "diff_fields" in verification:
            log_kwargs["diff_fields"] = verification["diff_fields"]
        if "diff_flags" in verification:
            log_kwargs["diff_flags"] = verification["diff_flags"]
    logger.info("Fixing cache entry", **log_kwargs)

    try:
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
    verify_team_fn: Callable[[Team, dict | None], dict],
    cache_type: str,
) -> VerificationResult:
    """
    Run verification for a single cache type and log results.

    Args:
        config: HyperCache management configuration
        verify_team_fn: Function to verify a single team
        cache_type: Name for metrics/logging

    Returns:
        VerificationResult with stats
    """
    import time

    start_time = time.time()
    logger.info(f"Starting {cache_type} cache verification")

    result = verify_and_fix_all_teams(
        config=config,
        verify_team_fn=verify_team_fn,
        cache_type=cache_type,
    )

    duration = time.time() - start_time

    logger.info(
        f"Completed {cache_type} cache verification",
        cache_type=cache_type,
        teams_verified=result.total,
        teams_fixed=result.total_fixed,
        cache_miss_fixed=result.cache_miss_fixed,
        cache_mismatch_fixed=result.cache_mismatch_fixed,
        expiry_missing_fixed=result.expiry_missing_fixed,
        fix_failures=result.fix_failed,
        errors=result.errors,
        fixed_team_ids=result.formatted_fixed_team_ids(),
        duration_seconds=duration,
    )

    return result
