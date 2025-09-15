from django.core.management.base import BaseCommand

from posthog.constants import AvailableFeature
from posthog.models.team import Team


class Command(BaseCommand):
    help = "Migrate teams from legacy Replay retention to 30d/90d retention"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Run without making any changes")
        parser.add_argument("--batch-size", type=int, default=100, help="Number of teams to migrate per DB query")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        teams_to_migrate = []

        try:
            self.stdout.write(
                self.style.SUCCESS("Starting Replay retention migration" + (" (DRY RUN)" if dry_run else ""))
            )

            for team in Team.objects.filter(session_recording_retention_period="legacy").only(
                "id", "organization", "session_recording_retention_period"
            ):
                # NOTE: We use file export as a proxy to see if they are subbed to Recordings
                is_paid = team.organization.is_feature_available(AvailableFeature.RECORDINGS_FILE_EXPORT)
                team.session_recording_retention_period = "90d" if is_paid else "30d"

                teams_to_migrate.append(team)
                self.stdout.write(self.style.SUCCESS(f"{'Would migrate' if dry_run else 'Migrating'} team {team.id}"))

            if not dry_run:
                Team.objects.bulk_update(
                    teams_to_migrate, ["session_recording_retention_period"], batch_size=batch_size
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"Success - {len(teams_to_migrate)} teams migrated" + (" (DRY RUN)" if dry_run else "")
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error occurred: {e}"))
