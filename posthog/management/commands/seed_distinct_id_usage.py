"""
Seed the distinct_id_usage ClickHouse table with test data that triggers all 3 dashboard queries.

Usage:
    python manage.py seed_distinct_id_usage
    python manage.py seed_distinct_id_usage --clear  # clear existing data first
"""

from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client import sync_execute
from posthog.models.distinct_id_usage.sql import DATA_TABLE_NAME, TABLE_BASE_NAME
from posthog.models.team.team import Team


class Command(BaseCommand):
    help = "Seed distinct_id_usage table with test data for the admin dashboard"

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Clear existing data before seeding")

    def handle(self, *args, **options):
        # Use actual teams from the local DB so tokens resolve correctly
        teams = list(Team.objects.order_by("id").values_list("id", flat=True)[:3])
        if not teams:
            raise CommandError("No teams found in the database. Create a team first.")

        # Reuse the first team if fewer than 3 exist
        team_high_usage = teams[0]
        team_high_cardinality = teams[1] if len(teams) > 1 else teams[0]
        team_burst = teams[2] if len(teams) > 2 else teams[0]

        table = f"{settings.CLICKHOUSE_DATABASE}.{TABLE_BASE_NAME}"
        now = datetime.now(tz=UTC)
        recent_minute = now.replace(second=0, microsecond=0) - timedelta(minutes=5)

        if options["clear"]:
            self.stdout.write("Clearing existing data...")
            sync_execute(f"TRUNCATE TABLE IF EXISTS {settings.CLICKHOUSE_DATABASE}.{DATA_TABLE_NAME}")

        self.stdout.write(f"Seeding high usage distinct IDs (team_id={team_high_usage})...")
        # One dominant distinct_id: 5M events
        # Even if all scenarios share the same team, 5M dominates the ~1.3M from other scenarios
        sync_execute(
            f"""
            INSERT INTO {table} (team_id, distinct_id, minute, event_count)
            VALUES
                (%(team_id)s, 'bot-scraper-abc123', %(minute)s, 5000000)
            """,
            {"team_id": team_high_usage, "minute": recent_minute},
        )
        for i in range(5):
            minute = recent_minute - timedelta(minutes=i)
            sync_execute(
                f"""
                INSERT INTO {table} (team_id, distinct_id, minute, event_count)
                SELECT %(team_id)s, concat('normal-user-', toString(number)), %(minute)s, 300
                FROM numbers(20)
                """,
                {"team_id": team_high_usage, "minute": minute},
            )

        self.stdout.write(f"Seeding high cardinality team (team_id={team_high_cardinality})...")
        # 1.1M unique distinct_ids — default threshold is 1M
        batch_size = 200_000
        total = 1_100_000
        inserted = 0
        while inserted < total:
            count = min(batch_size, total - inserted)
            sync_execute(
                f"""
                INSERT INTO {table} (team_id, distinct_id, minute, event_count)
                SELECT %(team_id)s, concat('uid-', toString(%(offset)s + number)), %(minute)s, 1
                FROM numbers(%(count)s)
                """,
                {
                    "team_id": team_high_cardinality,
                    "minute": recent_minute - timedelta(minutes=inserted // batch_size),
                    "offset": inserted,
                    "count": count,
                },
            )
            inserted += count
            self.stdout.write(f"  {inserted:,}/{total:,} distinct IDs inserted")

        self.stdout.write(f"Seeding burst events (team_id={team_burst})...")
        # Single (team, distinct_id) with 150k events in one minute — default threshold is 100k
        sync_execute(
            f"""
            INSERT INTO {table} (team_id, distinct_id, minute, event_count)
            VALUES
                (%(team_id)s, 'runaway-script-xyz', %(minute)s, 150000)
            """,
            {"team_id": team_burst, "minute": recent_minute},
        )
        sync_execute(
            f"""
            INSERT INTO {table} (team_id, distinct_id, minute, event_count)
            SELECT %(team_id)s, concat('user-', toString(number)), %(minute)s, 50
            FROM numbers(100)
            """,
            {"team_id": team_burst, "minute": recent_minute},
        )

        self.stdout.write(self.style.SUCCESS("\nDone! Test data seeded for all 3 query types:"))
        self.stdout.write(f"  Team {team_high_usage}: High usage distinct ID ('bot-scraper-abc123' ~80% of traffic)")
        self.stdout.write(f"  Team {team_high_cardinality}: High cardinality (1.1M unique distinct IDs)")
        self.stdout.write(f"  Team {team_burst}: Burst events ('runaway-script-xyz' 150k events/min)")
        self.stdout.write("\nVisit /admin/distinct-id-usage/ and click 'Run queries' to see results.")
