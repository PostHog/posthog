"""
Base class for HyperCache management commands.

Provides common utilities for HyperCache management commands.
This is specific to HyperCache instances (feature flags, team metadata, etc.).
For other cache types, create a different base class.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.db import connection

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.team.team import Team
from posthog.storage.hypercache_manager import (
    HyperCacheManagementConfig,
    batch_check_expiry_tracking,
    get_cache_stats,
    warm_caches,
)


class BaseHyperCacheCommand(BaseCommand):
    """
    Utility base class for HyperCache management commands.

    Provides common helpers for:
    - Argument parsing (team IDs, batch sizes, TTL ranges)
    - Output formatting (headers, progress, statistics)
    - Verification framework (compare cache vs database)
    - Warming framework (batch loading, TTL staggering)
    - Progress reporting and metrics

    This base class is specifically designed for HyperCache implementations.
    Commands for feature flags cache, team metadata cache, etc. inherit from this
    and implement the required abstract methods.

    Commands keep their own implementation logic while this class reduces boilerplate.
    """

    # Argument parsing helpers - commands can call these in add_arguments()

    def add_common_team_arguments(self, parser: CommandParser):
        """Add --team-ids argument common to all cache commands."""
        parser.add_argument(
            "--team-ids",
            nargs="+",
            type=int,
            help="Specific team IDs to process (if not provided, processes all teams)",
        )

    def add_warm_arguments(self, parser: CommandParser):
        """
        Add arguments specific to warming commands.

        Includes: --batch-size, --invalidate-first, --no-stagger, --min-ttl-days, --max-ttl-days
        """
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of teams to process at a time (default: 1000)",
        )
        parser.add_argument(
            "--invalidate-first",
            action="store_true",
            help="Invalidate all existing caches before warming (use when schema changes)",
        )
        parser.add_argument(
            "--no-stagger",
            action="store_true",
            help="Disable TTL staggering (all caches get same TTL)",
        )
        parser.add_argument(
            "--min-ttl-days",
            type=int,
            default=5,
            help="Minimum TTL in days when staggering (default: 5)",
        )
        parser.add_argument(
            "--max-ttl-days",
            type=int,
            default=7,
            help="Maximum TTL in days when staggering (default: 7)",
        )

    def add_verify_arguments(self, parser: CommandParser):
        """
        Add arguments specific to verification commands.

        Includes: --sample, --verbose, --fix
        """
        parser.add_argument(
            "--sample",
            type=int,
            help="Verify a random sample of N teams instead of all teams",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information about mismatches",
        )
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Automatically update mismatched or missing caches from database",
        )

    def add_analyze_arguments(self, parser: CommandParser):
        """
        Add arguments specific to analysis commands.

        Includes: --sample-size, --detailed
        """
        parser.add_argument(
            "--sample-size",
            type=int,
            default=100,
            help="Number of teams to sample for size analysis (default: 100)",
        )
        parser.add_argument(
            "--detailed",
            action="store_true",
            help="Show detailed field-by-field size breakdown",
        )

    # Output formatting helpers

    def print_header(self, title: str, width: int = 70):
        """Print a formatted section header with borders."""
        self.stdout.write("\n" + "=" * width)
        self.stdout.write(self.style.SUCCESS(title))
        self.stdout.write("=" * width)

    def print_separator(self, width: int = 70):
        """Print a separator line."""
        self.stdout.write("=" * width)

    def format_percentage(self, part: int, total: int) -> str:
        """
        Format part/total as percentage string with 1 decimal place.

        Args:
            part: The partial count
            total: The total count

        Returns:
            Formatted percentage string (e.g., "75.0%")
        """
        if total == 0:
            return "0.0%"
        return f"{(part / total * 100):.1f}%"

    def format_bytes(self, bytes_val: float) -> str:
        """
        Format bytes in human-readable format.

        Args:
            bytes_val: Number of bytes to format

        Returns:
            Formatted string with appropriate unit (B, KB, MB, GB, TB)

        Example:
            >>> format_bytes(1536)
            "1.5 KB"
        """
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} TB"

    def calculate_percentile(self, data: list[float] | list[int], percentile: int) -> float:
        """
        Calculate percentile of numeric data.

        Args:
            data: List of numeric values
            percentile: Percentile to calculate (0-100)

        Returns:
            Calculated percentile value (0 if data is empty)

        Example:
            >>> calculate_percentile([1, 2, 3, 4, 5], 50)
            3.0
        """
        if not data:
            return 0
        data_sorted = sorted(data)
        index = (percentile / 100) * (len(data_sorted) - 1)
        lower = data_sorted[int(index)]
        upper = data_sorted[min(int(index) + 1, len(data_sorted) - 1)]
        return lower + (upper - lower) * (index % 1)

    def process_teams_in_chunks(
        self,
        queryset,
        chunk_size: int,
        process_chunk_fn,
        progress_interval: int = 1000,
    ) -> int:
        """
        Process teams in chunks using the seek method to avoid memory exhaustion.

        This method implements an efficient chunking pattern that maintains constant memory
        usage regardless of total team count. It uses the seek method (WHERE id > last_id)
        rather than OFFSET-based pagination to avoid performance degradation with large datasets.

        Args:
            queryset: Django QuerySet of teams to process (must be orderable by id)
            chunk_size: Number of teams to load into memory at once
            process_chunk_fn: Callback function that takes a list of teams and processes them
            progress_interval: Show progress message every N teams (0 to disable)

        Returns:
            Total number of teams processed

        Example:
            def process_chunk(teams):
                for team in teams:
                    # Do something with team
                    pass

            total = self.process_teams_in_chunks(
                Team.objects.select_related("organization", "project"),
                chunk_size=1000,
                process_chunk_fn=process_chunk
            )
        """
        total_processed = 0
        last_id = 0

        while True:
            chunk = list(queryset.filter(id__gt=last_id).order_by("id")[:chunk_size])
            if not chunk:
                break

            # Process this chunk
            process_chunk_fn(chunk)

            # Track progress
            total_processed += len(chunk)
            last_id = chunk[-1].id

            # Show progress if configured
            if progress_interval > 0 and total_processed % progress_interval == 0:
                self.stdout.write(f"Progress: {total_processed} teams processed...")

        return total_processed

    # Verification framework

    def run_verification(
        self,
        team_ids: list[int] | None,
        sample_size: int | None,
        verbose: bool,
        fix: bool,
    ):
        """
        Generic verification flow for cache commands.

        This method implements the complete verification workflow that is common across
        all verify commands. Subclasses only need to implement cache-specific logic.

        Args:
            team_ids: Specific team IDs to verify, or None for all/sample
            sample_size: Number of random teams to sample, or None
            verbose: Show detailed diff information
            fix: Automatically fix cache issues

        Subclasses must implement:
            - get_hypercache_config() -> HyperCacheManagementConfig
            - verify_team(team, verbose, batch_data) -> dict

        Subclasses may optionally implement:
            - format_verbose_diff(diff) -> None (for custom verbose output)
        """
        # Establish persistent database connection (disabled in tests to avoid connection leaks)
        if not settings.TEST:
            connection.ensure_connection()

        try:
            stats: dict[str, int] = {
                "total": 0,
                "cache_miss": 0,
                "cache_match": 0,
                "cache_mismatch": 0,
                "expiry_missing": 0,
                "error": 0,
                "fixed": 0,
                "fix_failed": 0,
                "skipped_for_grace_period": 0,
            }

            mismatches: list[dict] = []

            # Process teams in chunks to avoid loading all teams into memory at once
            if team_ids:
                teams_queryset = Team.objects.filter(id__in=team_ids).select_related("organization", "project")
                self.stdout.write(f"Verifying {teams_queryset.count()} specific teams...\n")
                self._verify_teams_batch(list(teams_queryset), stats, mismatches, verbose, fix)
            elif sample_size:
                teams_queryset = Team.objects.select_related("organization", "project").order_by("?")[:sample_size]
                self.stdout.write(f"Verifying random sample of {teams_queryset.count()} teams...\n")
                self._verify_teams_batch(list(teams_queryset), stats, mismatches, verbose, fix)
            else:
                # For all teams, use chunked iteration to avoid memory exhaustion
                teams_queryset = Team.objects.select_related("organization", "project")
                total = teams_queryset.count()
                self.stdout.write(f"Verifying all {total} teams...\n")

                # Process teams in chunks using the helper method
                def process_chunk(chunk):
                    self._verify_teams_batch(chunk, stats, mismatches, verbose, fix)

                self.process_teams_in_chunks(
                    teams_queryset,
                    chunk_size=1000,
                    process_chunk_fn=process_chunk,
                    progress_interval=1000,
                )

            self._print_verification_results(stats, mismatches, verbose, fix)
        finally:
            # Update cache metrics after verification completes (even on failure)
            self._update_cache_stats_safe()

            if not settings.TEST:
                connection.close()

    def _verify_teams_batch(
        self,
        teams: list,
        stats: dict[str, int],
        mismatches: list[dict],
        verbose: bool,
        fix: bool,
    ):
        """
        Verify a batch of teams against their cached data.

        This method handles batch loading (if available) and delegates verification
        to the subclass's verify_team() method. Also checks expiry tracking.
        """
        # Batch-load data if the HyperCache supports it
        config = self.get_hypercache_config()
        batch_data = None
        if config.hypercache.batch_load_fn:
            try:
                batch_data = config.hypercache.batch_load_fn(teams)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Batch load failed, falling back to individual loads: {e}"))

        # Batch-check expiry tracking (pipelined for efficiency)
        expiry_status: dict[str | int, bool] = {}
        try:
            expiry_status = batch_check_expiry_tracking(teams, config)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Expiry tracking check failed, skipping: {e}"))

        # Batch-check which teams should skip fixes (e.g., grace period for recently updated data)
        team_ids_to_skip_fix: set[int] = set()
        if fix and config.get_team_ids_to_skip_fix_fn:
            try:
                team_ids_to_skip_fix = config.get_team_ids_to_skip_fix_fn([t.id for t in teams])
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Skip-fix check failed, proceeding without skips: {e}"))

        for team in teams:
            stats["total"] += 1

            # Delegate to subclass for actual verification
            try:
                result = self.verify_team(team, verbose, batch_data)
            except Exception as e:
                stats["error"] += 1
                self.stdout.write(self.style.ERROR(f"Error verifying team {team.id}: {e}"))
                continue

            # Handle result
            if result["status"] == "match":
                stats["cache_match"] += 1

                # Check expiry tracking for teams with valid cache data
                identifier = config.hypercache.get_cache_identifier(team)
                if expiry_status and not expiry_status.get(identifier, True):
                    stats["expiry_missing"] += 1
                    self._handle_expiry_issue(team, stats, mismatches, fix, config, team_ids_to_skip_fix)

            elif result["status"] == "miss":
                stats["cache_miss"] += 1
                self._handle_cache_issue(team, result, stats, mismatches, fix, team_ids_to_skip_fix)
            elif result["status"] == "mismatch":
                stats["cache_mismatch"] += 1
                self._handle_cache_issue(team, result, stats, mismatches, fix, team_ids_to_skip_fix)

    def _handle_cache_issue(
        self,
        team,
        result: dict,
        stats: dict[str, int],
        mismatches: list[dict],
        fix: bool,
        team_ids_to_skip_fix: set[int],
    ):
        """Handle a cache issue (miss or mismatch)."""
        issue_detail = {
            "team_id": team.id,
            "team_name": team.name,
            "issue": result["issue"],
            "details": result["details"],
        }

        if "diffs" in result:
            issue_detail["diffs"] = result["diffs"]

        if fix:
            # Check if we should skip fixing (e.g., grace period for recently updated data)
            if team.id in team_ids_to_skip_fix:
                stats["skipped_for_grace_period"] += 1
                issue_detail["skipped"] = True
                self.stdout.write(
                    self.style.WARNING(f"  ⏳ Skipped fix for team {team.id} ({team.name}) - within grace period")
                )
            else:
                issue_detail["fixed"] = self._fix_team_cache(team, stats)

        mismatches.append(issue_detail)

    def _fix_team_cache(
        self,
        team: Team,
        stats: dict[str, int],
        operation: str = "cache",
        config: HyperCacheManagementConfig | None = None,
    ) -> bool:
        """
        Fix a team by running update_fn (updates cache and re-tracks expiry).

        Args:
            team: Team to fix
            stats: Stats dict to update (increments 'fixed' or 'fix_failed')
            operation: Description for log messages (e.g., "cache", "expiry tracking")
            config: HyperCache config. If None, uses get_hypercache_config().
        """
        try:
            config = config or self.get_hypercache_config()
            success = config.update_fn(team)
            if success:
                stats["fixed"] += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Fixed {operation} for team {team.id} ({team.name})"))
            else:
                stats["fix_failed"] += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Failed to fix {operation} for team {team.id} ({team.name})"))
            return success
        except Exception as e:
            stats["fix_failed"] += 1
            self.stdout.write(self.style.ERROR(f"  ✗ Error fixing {operation} for team {team.id} ({team.name}): {e}"))
            return False

    def _handle_expiry_issue(
        self,
        team: Team,
        stats: dict[str, int],
        mismatches: list[dict],
        fix: bool,
        config: HyperCacheManagementConfig,
        team_ids_to_skip_fix: set[int],
    ):
        """Handle a team missing from expiry tracking."""
        issue_detail: dict = {
            "team_id": team.id,
            "team_name": team.name,
            "issue": "EXPIRY_MISSING",
            "details": "Cache exists but not tracked in expiry sorted set",
        }

        if fix:
            # Check if we should skip fixing (e.g., grace period for recently updated data)
            if team.id in team_ids_to_skip_fix:
                stats["skipped_for_grace_period"] += 1
                issue_detail["skipped"] = True
                self.stdout.write(
                    self.style.WARNING(f"  ⏳ Skipped fix for team {team.id} ({team.name}) - within grace period")
                )
            else:
                issue_detail["fixed"] = self._fix_team_cache(team, stats, "expiry tracking", config)

        mismatches.append(issue_detail)

    def _print_verification_results(self, stats: dict, mismatches: list[dict], verbose: bool, fix: bool):
        """Print verification results."""
        config = self.get_hypercache_config()
        cache_name = config.cache_display_name

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("\nVerification Results:"))
        self.stdout.write("=" * 70 + "\n")

        self.stdout.write(f"Total teams verified: {stats['total']}")
        self.stdout.write(
            f"Cache matches:        {stats['cache_match']} ({self.format_percentage(stats['cache_match'], stats['total'])})"
        )
        self.stdout.write(
            f"Cache mismatches:     {stats['cache_mismatch']} ({self.format_percentage(stats['cache_mismatch'], stats['total'])})"
        )
        self.stdout.write(
            f"Cache misses:         {stats['cache_miss']} ({self.format_percentage(stats['cache_miss'], stats['total'])})"
        )
        if stats.get("expiry_missing", 0) > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"Expiry missing:       {stats['expiry_missing']} ({self.format_percentage(stats['expiry_missing'], stats['total'])})"
                )
            )
        if stats["error"] > 0:
            self.stdout.write(
                self.style.ERROR(
                    f"Errors:               {stats['error']} ({self.format_percentage(stats['error'], stats['total'])})"
                )
            )

        if fix:
            self.stdout.write(
                f"Cache fixes applied:  {stats['fixed']} ({self.format_percentage(stats['fixed'], stats['total'])})"
            )
            if stats["fix_failed"] > 0:
                self.stdout.write(
                    self.style.ERROR(
                        f"Cache fixes failed:   {stats['fix_failed']} ({self.format_percentage(stats['fix_failed'], stats['total'])})"
                    )
                )
            if stats.get("skipped_for_grace_period", 0) > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipped (grace period): {stats['skipped_for_grace_period']} ({self.format_percentage(stats['skipped_for_grace_period'], stats['total'])})"
                    )
                )

        if mismatches:
            self.stdout.write("\n" + "=" * 70)
            self.stdout.write(self.style.WARNING(f"\nFound {len(mismatches)} issue(s):"))
            self.stdout.write("=" * 70 + "\n")

            for mismatch in mismatches:
                issue_prefix = f"[{mismatch['issue']}] Team {mismatch['team_id']} ({mismatch['team_name']})"

                if fix:
                    if mismatch.get("skipped"):
                        self.stdout.write(self.style.WARNING(f"\n{issue_prefix} - SKIPPED (grace period)"))
                    elif "fixed" in mismatch:
                        if mismatch["fixed"]:
                            self.stdout.write(self.style.SUCCESS(f"\n{issue_prefix} - FIXED"))
                        else:
                            self.stdout.write(self.style.ERROR(f"\n{issue_prefix} - FIX FAILED"))
                    else:
                        self.stdout.write(self.style.ERROR(f"\n{issue_prefix}"))
                else:
                    self.stdout.write(self.style.ERROR(f"\n{issue_prefix}"))

                if verbose and mismatch.get("diffs"):
                    # Use subclass's format_verbose_diff (or base implementation)
                    for diff in mismatch["diffs"]:
                        self.format_verbose_diff(diff)
                else:
                    self.stdout.write(f"  {mismatch['details']}")

        self.stdout.write("\n" + "=" * 70)

        all_verified = stats["cache_match"] == stats["total"] and stats.get("expiry_missing", 0) == 0
        if all_verified:
            self.stdout.write(self.style.SUCCESS(f"\n✓ All {cache_name} caches verified successfully!\n"))
        else:
            if fix:
                skipped = stats.get("skipped_for_grace_period", 0)
                skipped_suffix = f", {skipped} skipped (grace period)" if skipped > 0 else ""

                if stats["fixed"] > 0 and stats["fix_failed"] == 0:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"\n✓ Found and fixed {stats['fixed']} issue(s) with {len(mismatches)} team(s){skipped_suffix}\n"
                        )
                    )
                elif stats["fix_failed"] > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"\n⚠ Fixed {stats['fixed']} issue(s), but {stats['fix_failed']} fixes failed{skipped_suffix}\n"
                        )
                    )
                elif skipped > 0:
                    self.stdout.write(
                        self.style.WARNING(f"\n⚠ Found {len(mismatches)} issue(s), all skipped due to grace period\n")
                    )
            else:
                if stats["error"] > 0:
                    self.stdout.write(
                        self.style.ERROR(
                            f"\n✗ Verification incomplete: {stats['error']} error(s) occurred, "
                            f"{len(mismatches)} issue(s) found\n"
                        )
                    )
                else:
                    self.stdout.write(self.style.WARNING(f"\n⚠ Found issues with {len(mismatches)} team(s)\n"))

    # Methods that subclasses must implement

    def get_hypercache_config(self) -> HyperCacheManagementConfig:
        """
        Return the HyperCache management configuration for this cache type.

        Required properties:
        - hypercache: HyperCache instance (with batch_load_fn)
        - update_fn: Function to update cache for a team
        - cache_name: Canonical cache name (e.g., "flags", "team_metadata")

        All other properties (display name, Redis patterns, expiry tracking, etc.) are
        derived from cache_name and other required properties.

        Example:
            return FLAGS_HYPERCACHE_MANAGEMENT_CONFIG
        """
        raise NotImplementedError("Subclasses must implement get_hypercache_config()")

    def verify_team(self, team, verbose: bool, batch_data: dict | None = None) -> dict:
        """
        Verify a single team's cache against the database.

        Args:
            team: Team object to verify
            verbose: Whether to include detailed diff information
            batch_data: Pre-loaded batch data (if batch loading is supported)

        Returns:
            dict with keys:
                - status: "match", "miss", or "mismatch"
                - issue: Issue type (e.g., "CACHE_MISS", "DATA_MISMATCH")
                - details: Human-readable description
                - diffs: (optional) List of differences for verbose output
        """
        raise NotImplementedError("Subclasses must implement verify_team()")

    # Warming framework

    def _display_warm_results(self, cache_name: str, successful: int, failed: int):
        """Display warming results summary."""
        total = successful + failed
        success_rate = self.format_percentage(successful, total)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{cache_name.capitalize()} cache warm completed:\n"
                f"  Total teams: {total}\n"
                f"  Successful: {successful}\n"
                f"  Failed: {failed}\n"
                f"  Success rate: {success_rate}\n"
            )
        )

    def _validate_teams(self, team_ids: list[int], cache_name: str) -> list[Team] | None:
        """
        Validate team IDs exist and warn about missing ones.

        Returns:
            List of Team objects, or None if no teams found
        """
        self.stdout.write(f"\nWarming {cache_name} cache for {len(team_ids)} specific team(s)...\n")

        teams = list(Team.objects.filter(id__in=team_ids).select_related("organization", "project"))
        found_ids = {team.id for team in teams}
        missing_ids = set(team_ids) - found_ids

        if missing_ids:
            self.stdout.write(self.style.WARNING(f"Warning: Could not find teams with IDs: {sorted(missing_ids)}\n"))

        return teams if teams else None

    def _confirm_invalidate(self, cache_name: str) -> bool:
        """
        Get user confirmation for invalidating all caches.

        Returns:
            True if user confirmed, False otherwise
        """
        self.stdout.write(
            self.style.WARNING(
                f"WARNING: This will invalidate ALL existing {cache_name} caches before warming.\n"
                "This should only be used when the cache schema has changed.\n"
            )
        )
        confirm = input("Are you sure? Type 'yes' to continue: ")
        if confirm.lower() != "yes":
            self.stdout.write(self.style.ERROR("Aborted."))
            return False
        return True

    def run_warm(
        self,
        team_ids: list[int] | None,
        batch_size: int,
        invalidate_first: bool,
        stagger_ttl: bool,
        min_ttl_days: int,
        max_ttl_days: int,
    ):
        """
        Generic warming flow for cache commands.

        This method implements the complete warming workflow that is common across
        all warm commands. Subclasses only need to implement cache-specific logic.

        Args:
            team_ids: Specific team IDs to warm, or None for all teams
            batch_size: Number of teams to process at a time
            invalidate_first: Whether to invalidate all caches before warming
            stagger_ttl: Whether to randomize TTLs
            min_ttl_days: Minimum TTL in days (when staggering)
            max_ttl_days: Maximum TTL in days (when staggering)

        Subclasses must implement:
            - get_hypercache_config() -> HyperCacheManagementConfig
        """
        config = self.get_hypercache_config()
        cache_name = config.cache_display_name

        # Handle specific teams
        if team_ids:
            teams = self._validate_teams(team_ids, cache_name)
            if not teams:
                return

            # Process all specific teams at once (small batch)
            actual_batch_size = len(teams)
            actual_invalidate_first = False  # Never invalidate for specific teams
        else:
            # Get current cache stats for upfront reporting
            total_teams = Team.objects.count()
            cache_stats = get_cache_stats(config)

            # Handle all teams - show configuration and current state
            self.stdout.write(
                f"\nStarting {cache_name} cache warm:\n"
                f"  Total teams: {total_teams:,}\n"
                f"  Current cache coverage: {cache_stats.get('cache_coverage', 'unknown')}\n"
                f"  Batch size: {batch_size}\n"
                f"  Invalidate first: {invalidate_first}\n"
                f"  Stagger TTL: {stagger_ttl}\n"
                f"  TTL range: {min_ttl_days}-{max_ttl_days} days\n"
            )

            if invalidate_first and not self._confirm_invalidate(cache_name):
                return

            actual_batch_size = batch_size
            actual_invalidate_first = invalidate_first

        # Callbacks to write progress to stdout
        last_percent_reported = [0]  # Use list to allow mutation in closure

        def batch_start_callback(batch_num: int, batch_len: int):
            self.stdout.write(f"  Processing batch {batch_num} ({batch_len:,} teams)…")

        def progress_callback(processed: int, total: int, successful: int, failed: int):
            if total == 0:
                return
            percent = int(100 * processed / total)
            # Report every 5% to avoid too much output
            if percent >= last_percent_reported[0] + 5 or processed == total:
                self.stdout.write(
                    f"  Progress: {processed:,}/{total:,} teams ({percent}%) "
                    f"- {successful:,} successful, {failed:,} failed"
                )
                last_percent_reported[0] = percent

        # Warm the caches
        successful, failed = warm_caches(
            config,
            batch_size=actual_batch_size,
            invalidate_first=actual_invalidate_first,
            stagger_ttl=stagger_ttl,
            min_ttl_days=min_ttl_days,
            max_ttl_days=max_ttl_days,
            team_ids=team_ids,
            progress_callback=progress_callback,
            batch_start_callback=batch_start_callback,
        )

        # Display results
        self._display_warm_results(cache_name, successful, failed)

        # Warn about failures (only for all teams workflow)
        if not team_ids and failed > 0:
            self.stdout.write(self.style.WARNING(f"Warning: {failed} teams failed to cache. Check logs for details."))

        # Update cache metrics after warming completes
        self._update_cache_stats_safe(config)

    # Optional methods that subclasses can override for enhanced functionality

    def format_verbose_diff(self, diff: dict):
        """
        Format and print a single diff for verbose verification output.

        Override this in subclasses to provide custom formatting for cache diffs.
        The base implementation provides generic field-based diff formatting.

        Args:
            diff: Dict containing diff information (structure varies by subclass)
        """
        # Default formatting for generic diffs
        if "field" in diff:
            self.stdout.write(f"  Field: {diff['field']}")
            self.stdout.write(f"    DB:    {diff.get('db_value')}")
            self.stdout.write(f"    Cache: {diff.get('cached_value')}")

    # Configuration and validation helpers

    def _update_cache_stats_safe(self, config: HyperCacheManagementConfig | None = None) -> None:
        """
        Update cache metrics, logging a warning on failure.

        This wraps get_cache_stats() in a try/except to handle Redis timeouts
        gracefully without crashing the command. Metric updates are non-critical
        operations that shouldn't abort the main workflow.

        Args:
            config: HyperCache config. If None, uses get_hypercache_config().
        """
        try:
            config = config or self.get_hypercache_config()
            get_cache_stats(config)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Failed to update cache metrics: {e}"))

    def check_dedicated_cache_configured(self) -> bool:
        """
        Check if the dedicated cache is configured and display status.

        Auto-generates the operation description based on the command name and config.

        Returns:
            True if dedicated cache is configured, False otherwise

        Example:
            if not self.check_dedicated_cache_configured():
                return
        """
        has_dedicated_cache = FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES
        has_flags_redis_url = bool(settings.FLAGS_REDIS_URL)

        # Display cache configuration status
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("Cache Configuration:"))
        self.stdout.write("=" * 70)
        self.stdout.write(f"FLAGS_REDIS_URL configured: {has_flags_redis_url}")
        self.stdout.write(f"Dedicated cache available: {has_dedicated_cache}")
        self.stdout.write("=" * 70 + "\n")

        # Error if dedicated cache is not available
        if not has_dedicated_cache:
            # Auto-generate operation description from config and command name
            operation_description = self._get_operation_description()

            self.stdout.write(
                self.style.ERROR(
                    f"\nERROR: Dedicated cache (FLAGS_REDIS_URL) is NOT configured.\n"
                    "\n"
                    f"This command {operation_description}.\n"
                    "Without FLAGS_REDIS_URL set, the system falls back to the default Redis cache,\n"
                    "which would cause incorrect behavior.\n"
                    "\n"
                    "To fix this:\n"
                    "  1. Set the FLAGS_REDIS_URL environment variable to your dedicated Redis instance\n"
                    "  2. Re-run this command\n"
                    "\n"
                    "Example: FLAGS_REDIS_URL=redis://your-redis:6379/0\n"
                )
            )
            return False

        return True

    def _get_operation_description(self) -> str:
        """
        Generate operation description for error messages based on command and config.

        Returns a description like:
        - "warms the dedicated flags cache"
        - "verifies the dedicated team metadata cache"
        """
        config = self.get_hypercache_config()

        # Derive operation verb from module name
        module_name = self.__class__.__module__
        if "warm" in module_name:
            operation = "warms"
        elif "verify" in module_name:
            operation = "verifies"
        elif "analyze" in module_name:
            operation = "analyzes"
        else:
            operation = "operates on"

        return f"{operation} the dedicated {config.cache_display_name} cache"

    def validate_batch_size(self, batch_size: int) -> bool:
        """
        Validate batch size is within safe limits.

        Args:
            batch_size: The batch size to validate

        Returns:
            True if valid, False otherwise
        """
        if batch_size < 1:
            self.stdout.write(self.style.ERROR("--batch-size must be at least 1"))
            return False
        if batch_size > 5000:
            self.stdout.write(self.style.ERROR("--batch-size cannot be greater than 5000 (too many teams at once)"))
            return False
        return True

    def validate_sample_size(self, sample_size: int) -> bool:
        """
        Validate sample size is within safe limits.

        Args:
            sample_size: The sample size to validate

        Returns:
            True if valid, False otherwise
        """
        if sample_size < 1:
            self.stdout.write(self.style.ERROR("--sample must be at least 1"))
            return False
        if sample_size > 10000:
            self.stdout.write(self.style.ERROR("--sample cannot exceed 10000 (use smaller sample for verification)"))
            return False
        return True

    def validate_ttl_range(self, min_ttl_days: int, max_ttl_days: int) -> bool:
        """
        Validate TTL day range is within safe limits.

        Args:
            min_ttl_days: Minimum TTL in days
            max_ttl_days: Maximum TTL in days

        Returns:
            True if valid, False otherwise
        """
        if min_ttl_days < 1:
            self.stdout.write(self.style.ERROR("--min-ttl-days must be at least 1"))
            return False
        if min_ttl_days > 30:
            self.stdout.write(self.style.ERROR("--min-ttl-days cannot be greater than 30 days"))
            return False
        if max_ttl_days < 1:
            self.stdout.write(self.style.ERROR("--max-ttl-days must be at least 1"))
            return False
        if max_ttl_days > 30:
            self.stdout.write(self.style.ERROR("--max-ttl-days cannot be greater than 30 days"))
            return False
        if min_ttl_days > max_ttl_days:
            self.stdout.write(
                self.style.ERROR(
                    f"--min-ttl-days ({min_ttl_days}) cannot be greater than --max-ttl-days ({max_ttl_days})"
                )
            )
            return False
        return True
