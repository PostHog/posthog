from django.core.management.base import BaseCommand

from posthog.constants import AvailableFeature
from posthog.models.team import Team


class Command(BaseCommand):
    help = "Migrate teams from legacy Replay retention to 30d/90d retention"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Run without making any changes")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        teams_migrated = 0

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

                if not dry_run:
                    team.save()

                teams_migrated += 1
                self.stdout.write(self.style.SUCCESS(f"{'Would migrate' if dry_run else 'Migrated'} team {team.id}"))

            self.stdout.write(
                self.style.SUCCESS(f"Success - {teams_migrated} teams migrated" + (" (DRY RUN)" if dry_run else ""))
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error occurred: {e}"))
