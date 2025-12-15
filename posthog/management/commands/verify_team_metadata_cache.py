"""
Management command to verify team metadata cache consistency.

Compares cached data against database to detect discrepancies.

IMPORTANT: This command requires FLAGS_REDIS_URL to be set. It will error if the
dedicated flags cache is not configured to prevent misleading results.

Usage:
    # Verify all teams
    python manage.py verify_team_metadata_cache

    # Verify specific teams
    python manage.py verify_team_metadata_cache --team-ids 123 456 789

    # Sample random teams
    python manage.py verify_team_metadata_cache --sample 100

    # Verbose output (show full diffs)
    python manage.py verify_team_metadata_cache --verbose

    # Automatically fix cache issues
    python manage.py verify_team_metadata_cache --fix

    # Fix specific teams
    python manage.py verify_team_metadata_cache --team-ids 123 456 --fix
"""

from posthog.management.commands._base_hypercache_command import BaseHyperCacheCommand
from posthog.storage.team_metadata_cache import (
    TEAM_HYPERCACHE_MANAGEMENT_CONFIG,
    TEAM_METADATA_FIELDS,
    _serialize_team_field,
    get_team_metadata,
)


class Command(BaseHyperCacheCommand):
    help = "Verify team metadata cache consistency against database"

    def add_arguments(self, parser):
        self.add_common_team_arguments(parser)
        self.add_verify_arguments(parser)

    def handle(self, *args, **options):
        # Check if dedicated cache is configured (fail fast)
        if not self.check_dedicated_cache_configured():
            return

        team_ids = options.get("team_ids")
        sample_size = options.get("sample")
        verbose = options.get("verbose", False)
        fix = options.get("fix", False)

        # Use the generic verification framework
        self.run_verification(
            team_ids=team_ids,
            sample_size=sample_size,
            verbose=verbose,
            fix=fix,
        )

    # Implement required methods for verification framework

    def get_hypercache_config(self):
        """Return the HyperCache management configuration."""
        return TEAM_HYPERCACHE_MANAGEMENT_CONFIG

    def verify_team(self, team, verbose: bool, batch_data: dict | None = None) -> dict:
        """Verify a single team's metadata cache against the database."""
        cached_data = get_team_metadata(team)

        # Handle cache miss
        if not cached_data:
            return {
                "status": "miss",
                "issue": "CACHE_MISS",
                "details": "No cached data found",
            }

        # Get DB data from batch_data if available, otherwise serialize from team object
        if batch_data and team.id in batch_data:
            db_data = batch_data[team.id]
        else:
            db_data = self._get_db_data(team)

        match, diffs = self._compare_data(db_data, cached_data)

        if match:
            return {"status": "match", "issue": "", "details": ""}

        # Cache mismatch
        details = diffs if verbose else f"{len(diffs)} field(s) differ"
        return {
            "status": "mismatch",
            "issue": "DATA_MISMATCH",
            "details": details,
            "diffs": diffs,
        }

    def _get_db_data(self, team) -> dict:
        """Get team data from database in same format as cache."""
        data = {}
        for field in TEAM_METADATA_FIELDS:
            value = getattr(team, field, None)
            data[field] = _serialize_team_field(field, value)

        data["organization_name"] = (
            team.organization.name if hasattr(team, "organization") and team.organization else None
        )
        data["project_name"] = team.project.name if hasattr(team, "project") and team.project else None

        return data

    def _compare_data(self, db_data: dict, cached_data: dict) -> tuple[bool, list[dict]]:
        """Compare DB and cached data, return (match, diffs)."""
        diffs = []

        all_keys = set(db_data.keys()) | set(cached_data.keys())

        for key in all_keys:
            db_val = db_data.get(key)
            cached_val = cached_data.get(key)

            if db_val != cached_val:
                diffs.append(
                    {
                        "field": key,
                        "db_value": db_val,
                        "cached_value": cached_val,
                    }
                )

        return len(diffs) == 0, diffs
