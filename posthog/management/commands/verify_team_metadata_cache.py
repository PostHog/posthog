"""
Management command to verify team metadata cache consistency.

Compares cached data against database to detect discrepancies.

Usage:
    # Verify all teams
    python manage.py verify_team_metadata_cache

    # Verify specific teams
    python manage.py verify_team_metadata_cache --team-ids 123 456 789

    # Sample random teams
    python manage.py verify_team_metadata_cache --sample 100

    # Check dedicated flags cache too
    python manage.py verify_team_metadata_cache --check-dedicated-cache

    # Verbose output (show full diffs)
    python manage.py verify_team_metadata_cache --verbose

    # Automatically fix cache issues
    python manage.py verify_team_metadata_cache --fix

    # Fix specific teams
    python manage.py verify_team_metadata_cache --team-ids 123 456 --fix
"""

from django.conf import settings
from django.core.cache import caches
from django.core.management.base import BaseCommand

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.team.team import Team
from posthog.storage.team_metadata_cache import (
    TEAM_METADATA_FIELDS,
    _serialize_team_field,
    get_team_metadata,
    team_metadata_hypercache,
    update_team_metadata_cache,
)


class Command(BaseCommand):
    help = "Verify team metadata cache consistency against database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            nargs="+",
            type=int,
            help="Specific team IDs to verify",
        )
        parser.add_argument(
            "--sample",
            type=int,
            help="Randomly sample N teams to verify",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed diffs for mismatches",
        )
        parser.add_argument(
            "--check-dedicated-cache",
            action="store_true",
            help="Also verify data exists in dedicated flags Redis cache",
        )
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Automatically fix cache mismatches by updating cache from database",
        )

    def handle(self, *args, **options):
        team_ids = options.get("team_ids")
        sample_size = options.get("sample")
        verbose = options.get("verbose", False)
        check_dedicated = options.get("check_dedicated_cache", False)
        fix = options.get("fix", False)

        has_dedicated_cache = FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES

        if check_dedicated and not has_dedicated_cache:
            self.stdout.write(
                self.style.WARNING("Dedicated flags cache not configured, skipping dedicated cache check\n")
            )
            check_dedicated = False

        if team_ids:
            teams = Team.objects.filter(id__in=team_ids).select_related("organization", "project")
            self.stdout.write(f"Verifying {len(teams)} specific teams...\n")
        elif sample_size:
            teams = Team.objects.select_related("organization", "project").order_by("?")[:sample_size]
            self.stdout.write(f"Verifying random sample of {len(teams)} teams...\n")
        else:
            teams = Team.objects.select_related("organization", "project")
            total = teams.count()
            self.stdout.write(f"Verifying all {total} teams...\n")

        stats: dict[str, int] = {
            "total": 0,
            "cache_miss": 0,
            "cache_match": 0,
            "cache_mismatch": 0,
            "dedicated_miss": 0,
            "fixed": 0,
            "fix_failed": 0,
        }

        mismatches = []

        for team in teams:
            stats["total"] += 1

            cached_data = get_team_metadata(team)

            if not cached_data:
                stats["cache_miss"] += 1
                issue_detail = {
                    "team_id": team.id,
                    "team_name": team.name,
                    "issue": "CACHE_MISS",
                    "details": "No cached data found",
                }

                if fix:
                    if self._fix_cache(team, stats):
                        issue_detail["fixed"] = True
                    else:
                        issue_detail["fixed"] = False

                mismatches.append(issue_detail)
                continue

            db_data = self._get_db_data(team)

            match, diffs = self._compare_data(db_data, cached_data)

            if match:
                stats["cache_match"] += 1
            else:
                stats["cache_mismatch"] += 1
                issue_detail = {
                    "team_id": team.id,
                    "team_name": team.name,
                    "issue": "DATA_MISMATCH",
                    "details": diffs if verbose else f"{len(diffs)} field(s) differ",
                    "diffs": diffs,
                }

                if fix:
                    if self._fix_cache(team, stats):
                        issue_detail["fixed"] = True
                    else:
                        issue_detail["fixed"] = False

                mismatches.append(issue_detail)

            if check_dedicated:
                cache_key = team_metadata_hypercache.get_cache_key(team)
                dedicated_cache = caches[FLAGS_DEDICATED_CACHE_ALIAS]
                dedicated_data = dedicated_cache.get(cache_key)

                if not dedicated_data:
                    stats["dedicated_miss"] += 1
                    issue_detail = {
                        "team_id": team.id,
                        "team_name": team.name,
                        "issue": "DEDICATED_CACHE_MISS",
                        "details": "Data not found in dedicated flags cache",
                    }

                    if fix:
                        if self._fix_cache(team, stats):
                            issue_detail["fixed"] = True
                        else:
                            issue_detail["fixed"] = False

                    mismatches.append(issue_detail)

            if stats["total"] % 100 == 0:
                self.stdout.write(f"Progress: {stats['total']} teams verified...")

        self._print_results(stats, mismatches, verbose, check_dedicated, fix)

    def _fix_cache(self, team: Team, stats: dict[str, int]) -> bool:
        """Fix cache for a team by updating from database."""
        try:
            success = update_team_metadata_cache(team)
            if success:
                stats["fixed"] += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Fixed cache for team {team.id} ({team.name})"))
            else:
                stats["fix_failed"] += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Failed to fix cache for team {team.id} ({team.name})"))
            return success
        except Exception as e:
            stats["fix_failed"] += 1
            self.stdout.write(self.style.ERROR(f"  ✗ Error fixing cache for team {team.id} ({team.name}): {e}"))
            return False

    def _get_db_data(self, team: Team) -> dict:
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

    def _print_results(self, stats: dict, mismatches: list[dict], verbose: bool, check_dedicated: bool, fix: bool):
        """Print verification results."""
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS("\nVerification Results:"))
        self.stdout.write("=" * 70 + "\n")

        self.stdout.write(f"Total teams verified: {stats['total']}")
        self.stdout.write(
            f"Cache matches:        {stats['cache_match']} ({self._percent(stats['cache_match'], stats['total'])})"
        )
        self.stdout.write(
            f"Cache mismatches:     {stats['cache_mismatch']} ({self._percent(stats['cache_mismatch'], stats['total'])})"
        )
        self.stdout.write(
            f"Cache misses:         {stats['cache_miss']} ({self._percent(stats['cache_miss'], stats['total'])})"
        )

        if check_dedicated:
            self.stdout.write(
                f"Dedicated cache miss: {stats['dedicated_miss']} ({self._percent(stats['dedicated_miss'], stats['total'])})"
            )

        if fix:
            self.stdout.write(
                f"Cache fixes applied:  {stats['fixed']} ({self._percent(stats['fixed'], stats['total'])})"
            )
            if stats["fix_failed"] > 0:
                self.stdout.write(
                    self.style.ERROR(
                        f"Cache fixes failed:   {stats['fix_failed']} ({self._percent(stats['fix_failed'], stats['total'])})"
                    )
                )

        if mismatches:
            self.stdout.write("\n" + "=" * 70)
            self.stdout.write(self.style.WARNING(f"\nFound {len(mismatches)} issue(s):"))
            self.stdout.write("=" * 70 + "\n")

            for mismatch in mismatches:
                issue_prefix = f"[{mismatch['issue']}] Team {mismatch['team_id']} ({mismatch['team_name']})"

                if fix and "fixed" in mismatch:
                    if mismatch["fixed"]:
                        self.stdout.write(self.style.SUCCESS(f"\n{issue_prefix} - FIXED"))
                    else:
                        self.stdout.write(self.style.ERROR(f"\n{issue_prefix} - FIX FAILED"))
                else:
                    self.stdout.write(self.style.ERROR(f"\n{issue_prefix}"))

                if verbose and mismatch.get("diffs"):
                    for diff in mismatch["diffs"]:
                        self.stdout.write(f"  Field: {diff['field']}")
                        self.stdout.write(f"    DB:    {diff['db_value']}")
                        self.stdout.write(f"    Cache: {diff['cached_value']}")
                else:
                    self.stdout.write(f"  {mismatch['details']}")

        self.stdout.write("\n" + "=" * 70)

        if stats["cache_match"] == stats["total"]:
            self.stdout.write(self.style.SUCCESS("\n✓ All caches verified successfully!\n"))
        else:
            if fix:
                if stats["fixed"] > 0 and stats["fix_failed"] == 0:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"\n✓ Found and fixed {stats['fixed']} issue(s) with {len(mismatches)} team(s)\n"
                        )
                    )
                elif stats["fix_failed"] > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"\n⚠ Fixed {stats['fixed']} issue(s), but {stats['fix_failed']} fix(es) failed\n"
                        )
                    )
            else:
                self.stdout.write(self.style.WARNING(f"\n⚠ Found issues with {len(mismatches)} team(s)\n"))

    def _percent(self, part: int, total: int) -> str:
        """Calculate percentage."""
        if total == 0:
            return "0.0%"
        return f"{(part / total * 100):.1f}%"
