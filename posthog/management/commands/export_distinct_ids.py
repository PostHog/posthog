import random
from django.core.management.base import BaseCommand
from posthog.models import Person, PersonDistinctId, Team


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

        # Build the query
        distinct_ids_query = PersonDistinctId.objects.filter(team=team)

        if identified_only:
            distinct_ids_query = distinct_ids_query.filter(person__is_identified=True)
            self.stdout.write("Filtering for identified persons only")

        if demo_only:
            distinct_ids_query = distinct_ids_query.filter(person__properties__is_demo=True)
            self.stdout.write("Filtering for demo persons only")

        # Get distinct IDs
        distinct_ids = list(distinct_ids_query.values_list("distinct_id", flat=True))

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
        total_persons = Person.objects.filter(team=team).count()
        identified_persons = Person.objects.filter(team=team, is_identified=True).count()
        demo_persons = Person.objects.filter(team=team, properties__is_demo=True).count()

        self.stdout.write(f"\nTeam statistics:")
        self.stdout.write(f"  Total persons: {total_persons}")
        self.stdout.write(f"  Identified persons: {identified_persons}")
        self.stdout.write(f"  Demo persons: {demo_persons}")
        self.stdout.write(f"  Exported distinct IDs: {len(distinct_ids)}")
