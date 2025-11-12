"""
Management command to warm the team metadata cache.

Usage:
    # Initial cache warm (preserves existing caches)
    python manage.py warm_team_metadata_cache

    # Schema changes (invalidates all caches first)
    python manage.py warm_team_metadata_cache --invalidate-first

    # Custom batch size and TTL range
    python manage.py warm_team_metadata_cache --batch-size 200 --min-ttl-days 6 --max-ttl-days 8
"""

from django.core.management.base import BaseCommand

from posthog.storage.team_metadata_cache import warm_all_team_caches


class Command(BaseCommand):
    help = "Warm team metadata cache for all teams (initial build or schema migration)"

    def add_arguments(self, parser):
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
        batch_size = options["batch_size"]
        invalidate_first = options["invalidate_first"]
        stagger_ttl = not options["no_stagger"]
        min_ttl_days = options["min_ttl_days"]
        max_ttl_days = options["max_ttl_days"]

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
