import random

from django.conf import settings
from django.core.management.base import BaseCommand

from posthog.models import Team
from posthog.persons_db import persons_db_connection


class Command(BaseCommand):
    help = "Export distinct IDs to a text file for static cohort import"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            help="Team ID to export distinct IDs for (default: first team)",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="distinct_ids.csv",
            help="Output file path (default: distinct_ids.csv)",
        )
        parser.add_argument(
            "--identified-only",
            action="store_true",
            help="Only export distinct IDs for identified persons",
        )
        parser.add_argument(
            "--demo-only",
            action="store_true",
            help="Only export distinct IDs for demo persons (with is_demo=True)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit the number of distinct IDs to export",
        )
        parser.add_argument(
            "--random",
            type=int,
            help="Pick N distinct IDs at random from the database",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        output_file = options["output"]
        identified_only = options["identified_only"]
        demo_only = options["demo_only"]
        limit = options["limit"]
        random_count = options["random"]

        # Get or create team
        if team_id:
            try:
                team = Team.objects.get(pk=team_id)
            except Team.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Team with ID {team_id} does not exist!"))
                return
        else:
            team = Team.objects.first()
            if not team:
                self.stdout.write(self.style.ERROR("No teams found! Please create a team first."))
                return

        self.stdout.write(self.style.SUCCESS(f"Exporting distinct IDs for team: {team.name}"))

        # Build the distinct-id query, joining to the person table only when filtering on
        # person attributes (identified / demo).
        conditions = ["pdi.team_id = %s"]
        if identified_only:
            conditions.append("p.is_identified = true")
            self.stdout.write("Filtering for identified persons only")
        if demo_only:
            conditions.append("p.properties @> '{\"is_demo\": true}'::jsonb")
            self.stdout.write("Filtering for demo persons only")

        person_join = (
            f"JOIN {settings.PERSON_TABLE_NAME} p ON p.team_id = pdi.team_id AND p.id = pdi.person_id"
            if (identified_only or demo_only)
            else ""
        )
        query = (
            f"SELECT pdi.distinct_id FROM posthog_persondistinctid pdi {person_join} WHERE {' AND '.join(conditions)}"
        )
        with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
            cursor.execute(query, [team.id])
            distinct_ids = [row[0] for row in cursor.fetchall()]

        if not distinct_ids:
            self.stdout.write(self.style.WARNING("No distinct IDs found matching the criteria!"))
            return

        # Handle random selection
        if random_count:
            if random_count > len(distinct_ids):
                self.stdout.write(
                    self.style.WARNING(
                        f"Requested {random_count} random distinct IDs, but only {len(distinct_ids)} available. "
                        f"Using all {len(distinct_ids)} distinct IDs."
                    )
                )
                random_count = len(distinct_ids)

            distinct_ids = random.sample(distinct_ids, random_count)
            self.stdout.write(f"Randomly selected {len(distinct_ids)} distinct IDs")
        elif limit:
            distinct_ids = distinct_ids[:limit]
            self.stdout.write(f"Limited to {len(distinct_ids)} distinct IDs")

        # Write to file
        try:
            with open(output_file, "w") as f:
                # Write header
                f.write("distinct_id\n")

                # Write distinct IDs
                for distinct_id in distinct_ids:
                    f.write(f"{distinct_id}\n")

            self.stdout.write(
                self.style.SUCCESS(f"Successfully exported {len(distinct_ids)} distinct IDs to {output_file}")
            )

            # Show some sample distinct IDs
            sample_size = min(5, len(distinct_ids))
            self.stdout.write(f"Sample distinct IDs:")
            for i in range(sample_size):
                self.stdout.write(f"  {distinct_ids[i]}")

            if len(distinct_ids) > sample_size:
                self.stdout.write(f"  ... and {len(distinct_ids) - sample_size} more")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error writing to file: {e}"))

        # Also show some stats
        with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*), "
                "count(*) FILTER (WHERE is_identified), "
                "count(*) FILTER (WHERE properties @> '{\"is_demo\": true}'::jsonb) "
                f"FROM {settings.PERSON_TABLE_NAME} WHERE team_id = %s",
                [team.id],
            )
            stats_row = cursor.fetchone()
        assert stats_row is not None
        total_persons, identified_persons, demo_persons = stats_row

        self.stdout.write(f"\nTeam statistics:")
        self.stdout.write(f"  Total persons: {total_persons}")
        self.stdout.write(f"  Identified persons: {identified_persons}")
        self.stdout.write(f"  Demo persons: {demo_persons}")
        self.stdout.write(f"  Exported distinct IDs: {len(distinct_ids)}")
