"""
Management command to warm the team metadata cache.

Usage:
    # Initial cache warm (preserves existing caches)
    python manage.py warm_team_metadata_cache

    # Warm specific teams
    python manage.py warm_team_metadata_cache --team-ids 12345 67890

    # Schema changes (invalidates all caches first)
    python manage.py warm_team_metadata_cache --invalidate-first

    # Custom batch size and TTL range
    python manage.py warm_team_metadata_cache --batch-size 200 --min-ttl-days 6 --max-ttl-days 8
"""

from django.core.management.base import BaseCommand

from posthog.models.team.team import Team
from posthog.storage.team_metadata_cache import update_team_metadata_cache, warm_all_team_caches


class Command(BaseCommand):
    help = "Warm team metadata cache for all teams (initial build or schema migration)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-ids",
            nargs="+",
            type=int,
            help="Specific team IDs to warm (if not provided, warms all teams)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of teams to process at a time (default: 100)",
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

    def handle(self, *args, **options):
        team_ids = options.get("team_ids")
        batch_size = options["batch_size"]
        invalidate_first = options["invalidate_first"]
        stagger_ttl = not options["no_stagger"]
        min_ttl_days = options["min_ttl_days"]
        max_ttl_days = options["max_ttl_days"]

        # Handle specific teams
        if team_ids:
            self._warm_specific_teams(team_ids, stagger_ttl, min_ttl_days, max_ttl_days)
            return

        # Handle all teams
        self.stdout.write(
            self.style.WARNING(
                f"\nStarting team metadata cache warm:\n"
                f"  Batch size: {batch_size}\n"
                f"  Invalidate first: {invalidate_first}\n"
                f"  Stagger TTL: {stagger_ttl}\n"
                f"  TTL range: {min_ttl_days}-{max_ttl_days} days\n"
            )
        )

        if invalidate_first:
            self.stdout.write(
                self.style.WARNING(
                    "WARNING: This will invalidate ALL existing caches before warming.\n"
                    "This should only be used when the cache schema has changed.\n"
                )
            )
            confirm = input("Are you sure? Type 'yes' to continue: ")
            if confirm.lower() != "yes":
                self.stdout.write(self.style.ERROR("Aborted."))
                return

        successful, failed = warm_all_team_caches(
            batch_size=batch_size,
            invalidate_first=invalidate_first,
            stagger_ttl=stagger_ttl,
            min_ttl_days=min_ttl_days,
            max_ttl_days=max_ttl_days,
        )

        total = successful + failed
        success_rate = (successful / total * 100) if total > 0 else 0

        self.stdout.write(
            self.style.SUCCESS(
                f"\nCache warm completed:\n"
                f"  Total teams: {total}\n"
                f"  Successful: {successful}\n"
                f"  Failed: {failed}\n"
                f"  Success rate: {success_rate:.1f}%\n"
            )
        )

        if failed > 0:
            self.stdout.write(self.style.WARNING(f"Warning: {failed} teams failed to cache. Check logs for details."))

    def _warm_specific_teams(self, team_ids: list[int], stagger_ttl: bool, min_ttl_days: int, max_ttl_days: int):
        """Warm cache for specific teams."""
        import random

        self.stdout.write(f"\nWarming cache for {len(team_ids)} specific team(s)...\n")

        teams = Team.objects.filter(id__in=team_ids).select_related("organization", "project")
        found_ids = {team.id for team in teams}
        missing_ids = set(team_ids) - found_ids

        if missing_ids:
            self.stdout.write(self.style.WARNING(f"Warning: Could not find teams with IDs: {sorted(missing_ids)}\n"))

        successful = 0
        failed = 0

        for team in teams:
            try:
                if stagger_ttl:
                    ttl_seconds = random.randint(min_ttl_days * 24 * 3600, max_ttl_days * 24 * 3600)
                    update_team_metadata_cache(team, ttl=ttl_seconds)
                else:
                    update_team_metadata_cache(team)

                successful += 1
                self.stdout.write(self.style.SUCCESS(f"  ✓ Warmed cache for team {team.id} ({team.name})"))
            except Exception as e:
                failed += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Failed to warm cache for team {team.id} ({team.name}): {e}"))

        total = successful + failed
        success_rate = (successful / total * 100) if total > 0 else 0

        self.stdout.write(
            self.style.SUCCESS(
                f"\nCache warm completed:\n"
                f"  Total teams: {total}\n"
                f"  Successful: {successful}\n"
                f"  Failed: {failed}\n"
                f"  Success rate: {success_rate:.1f}%\n"
            )
        )
