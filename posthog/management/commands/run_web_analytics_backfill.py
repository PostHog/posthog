from django.core.management.base import BaseCommand

from posthog.tasks.scheduled_web_analytics_backfill import discover_and_backfill_teams, backfill_team


class Command(BaseCommand):
    help = "Manually trigger web analytics backfill for teams with pre-aggregated tables enabled"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            help="Backfill a specific team ID",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Number of days to backfill (default: 7, max: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be processed without executing",
        )

    def handle(self, *args, **options):
        days = options["days"]
        team_id = options.get("team_id")
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would backfill last {days} days for web analytics"
                )
            )

        if team_id:
            # Backfill specific team
            self.stdout.write(f"Processing team {team_id}...")

            if not dry_run:
                result = backfill_team(team_id, days)
                self.stdout.write(
                    self.style.SUCCESS(f"Result: {result}")
                )
            else:
                self.stdout.write(f"Would backfill team {team_id} for {days} days")
        else:
            # Discover and backfill teams
            self.stdout.write("Discovering teams needing backfill...")

            if not dry_run:
                result = discover_and_backfill_teams(days)
                self.stdout.write(
                    self.style.SUCCESS(f"Batch result: {result}")
                )
            else:
                from posthog.tasks.scheduled_web_analytics_backfill import get_teams_needing_backfill
                teams = get_teams_needing_backfill()
                self.stdout.write(f"Would process {len(teams)} teams: {teams}")

        self.stdout.write(
            self.style.SUCCESS("Web analytics backfill command completed")
        )

