"""
Management command to verify flags cache consistency.

Compares cached flags data against database to detect discrepancies.

IMPORTANT: This command requires FLAGS_REDIS_URL to be set. It will error if the
dedicated flags cache is not configured to prevent misleading results.

Usage:
    # Verify all teams
    python manage.py verify_flags_cache

    # Verify specific teams
    python manage.py verify_flags_cache --team-ids 123 456 789

    # Sample random teams
    python manage.py verify_flags_cache --sample 100

    # Check dedicated flags cache too
    python manage.py verify_flags_cache --check-dedicated-cache

    # Verbose output (show full diffs)
    python manage.py verify_flags_cache --verbose

    # Automatically fix cache issues
    python manage.py verify_flags_cache --fix

    # Fix specific teams
    python manage.py verify_flags_cache --team-ids 123 456 --fix
"""

from django.conf import settings
from django.core.cache import caches

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.models.feature_flag.flags_cache import (
    _get_feature_flags_for_service,
    _get_feature_flags_for_teams_batch,
    flags_hypercache,
    get_flags_from_cache,
    update_flags_cache,
)


class Command(BaseHyperCacheCommand):
    help = "Verify flags cache consistency against database"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_verify_arguments(parser)

    def handle(self, *args, **options):
        team_ids = options.get("team_ids")
        sample_size = options.get("sample")
        verbose = options.get("verbose", False)
        check_dedicated = options.get("check_dedicated_cache", False)
        fix = options.get("fix", False)

        # Validate input arguments to prevent resource exhaustion
        if sample_size is not None:
            if not self.validate_sample_size(sample_size):
                return

        # Check if dedicated flags cache is configured
        if not self.check_dedicated_cache_configured(
            "verifies the dedicated flags cache used by the Rust feature-flags service"
        ):
            return

        # Use the generic verification framework
        self.run_verification(
            team_ids=team_ids,
            sample_size=sample_size,
            verbose=verbose,
            check_dedicated=check_dedicated,
            fix=fix,
            use_connection_pooling=not settings.TEST,
        )

    # Implement required methods for verification framework

    def get_cache_name(self) -> str:
        """Return name of cache for display purposes."""
        return "flags"

    def get_update_cache_fn(self):
        """Return function to update the cache."""
        return update_flags_cache

    def get_batch_load_fn(self):
        """Return function to batch-load flags for multiple teams."""
        return _get_feature_flags_for_teams_batch

    def verify_team(self, team, verbose: bool, check_dedicated: bool, batch_data: dict | None = None) -> dict:
        """Verify a single team's flags cache against the database."""
        cached_flags = get_flags_from_cache(team)

        # Get flags from database (use pre-loaded data if available)
        if batch_data and team.id in batch_data:
            db_data = batch_data[team.id]
        else:
            db_data = _get_feature_flags_for_service(team)

        db_flags = db_data.get("flags", []) if isinstance(db_data, dict) else []

        # Handle cache miss (None means FLAGS_REDIS_URL not configured or cache miss)
        if cached_flags is None:
            if len(db_flags) == 0:
                # Team has no flags anyway, so missing cache is not a problem
                return {"status": "match", "issue": "", "details": ""}

            # Team has flags but cache is missing
            return {
                "status": "miss",
                "issue": "CACHE_MISS",
                "details": f"No cached flags found (team has {len(db_flags)} flags in DB)",
            }

        # Compare flags (cached_flags is now guaranteed to be a list)
        match, diffs = self._compare_flags(db_flags, cached_flags)

        if match:
            # Check dedicated cache if requested
            if check_dedicated:
                cache_key = flags_hypercache.get_cache_key(team)
                dedicated_cache = caches[FLAGS_DEDICATED_CACHE_ALIAS]
                dedicated_data = dedicated_cache.get(cache_key)

                if not dedicated_data:
                    return {
                        "status": "dedicated_miss",
                        "issue": "DEDICATED_CACHE_MISS",
                        "details": "Data not found in dedicated flags cache",
                    }

            return {"status": "match", "issue": "", "details": ""}

        # Cache mismatch
        details = diffs if verbose else self._summarize_diffs(diffs)
        return {
            "status": "mismatch",
            "issue": "DATA_MISMATCH",
            "details": details,
            "diffs": diffs,
        }

    def format_verbose_diff(self, diff):
        """Format a single diff for verbose output (flags-specific formatting)."""
        diff_type = diff.get("type")
        if diff_type == "MISSING_IN_CACHE":
            self.stdout.write(f"  Missing flag: {diff.get('flag_key')} (ID: {diff.get('flag_id')})")
        elif diff_type == "STALE_IN_CACHE":
            self.stdout.write(f"  Stale flag: {diff.get('flag_key')} (ID: {diff.get('flag_id')})")
        elif diff_type == "FIELD_MISMATCH":
            self.stdout.write(f"  Mismatched flag: {diff.get('flag_key')} (ID: {diff.get('flag_id')})")
            for field_diff in diff.get("field_diffs", []):
                self.stdout.write(f"    Field: {field_diff['field']}")
                self.stdout.write(f"      DB:    {field_diff['db_value']}")
                self.stdout.write(f"      Cache: {field_diff['cached_value']}")

    # Private helper methods for flag comparison

    def _find_missing_flags(self, db_flags_by_id: dict, cached_flags_by_id: dict) -> list[dict]:
        """Find flags that exist in DB but are missing from cache."""
        missing = []
        for flag_id in db_flags_by_id:
            if flag_id not in cached_flags_by_id:
                missing.append(
                    {
                        "type": "MISSING_IN_CACHE",
                        "flag_id": flag_id,
                        "flag_key": db_flags_by_id[flag_id].get("key"),
                    }
                )
        return missing

    def _find_stale_flags(self, db_flags_by_id: dict, cached_flags_by_id: dict) -> list[dict]:
        """Find flags that exist in cache but have been deleted from DB."""
        stale = []
        for flag_id in cached_flags_by_id:
            if flag_id not in db_flags_by_id:
                stale.append(
                    {
                        "type": "STALE_IN_CACHE",
                        "flag_id": flag_id,
                        "flag_key": cached_flags_by_id[flag_id].get("key"),
                    }
                )
        return stale

    def _compare_flag_fields(self, db_flag: dict, cached_flag: dict) -> list[dict]:
        """Compare field values between DB and cached versions of a flag."""
        field_diffs = []
        all_keys = set(db_flag.keys()) | set(cached_flag.keys())

        for key in all_keys:
            db_val = db_flag.get(key)
            cached_val = cached_flag.get(key)

            if db_val != cached_val:
                field_diffs.append(
                    {
                        "field": key,
                        "db_value": db_val,
                        "cached_value": cached_val,
                    }
                )

        return field_diffs

    def _compare_flags(self, db_flags: list, cached_flags: list) -> tuple[bool, list[dict]]:
        """Compare DB and cached flags, return (match, diffs)."""
        # Create ID-indexed dicts for comparison
        db_flags_by_id = {flag["id"]: flag for flag in db_flags}
        cached_flags_by_id = {flag["id"]: flag for flag in cached_flags}

        diffs = []

        # Find missing flags
        diffs.extend(self._find_missing_flags(db_flags_by_id, cached_flags_by_id))

        # Find stale flags
        diffs.extend(self._find_stale_flags(db_flags_by_id, cached_flags_by_id))

        # Compare field values for flags that exist in both
        for flag_id in db_flags_by_id:
            if flag_id in cached_flags_by_id:
                db_flag = db_flags_by_id[flag_id]
                cached_flag = cached_flags_by_id[flag_id]

                field_diffs = self._compare_flag_fields(db_flag, cached_flag)

                if field_diffs:
                    diffs.append(
                        {
                            "type": "FIELD_MISMATCH",
                            "flag_id": flag_id,
                            "flag_key": db_flag.get("key"),
                            "field_diffs": field_diffs,
                        }
                    )

        return len(diffs) == 0, diffs

    def _summarize_diffs(self, diffs: list[dict]) -> str:
        """Summarize diffs into a readable string."""
        missing_count = sum(1 for d in diffs if d.get("type") == "MISSING_IN_CACHE")
        stale_count = sum(1 for d in diffs if d.get("type") == "STALE_IN_CACHE")
        mismatch_count = sum(1 for d in diffs if d.get("type") == "FIELD_MISMATCH")

        summary_parts = []
        if missing_count > 0:
            summary_parts.append(f"{missing_count} missing")
        if stale_count > 0:
            summary_parts.append(f"{stale_count} stale")
        if mismatch_count > 0:
            summary_parts.append(f"{mismatch_count} mismatched")

        return f"{', '.join(summary_parts)} flags" if summary_parts else "unknown differences"
