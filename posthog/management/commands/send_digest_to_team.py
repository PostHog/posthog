from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team
from posthog.tasks.email import send_team_hog_functions_digest


class Command(BaseCommand):
    help = "Send HogFunctions digest email to a specific team to test notification logic"

    def add_arguments(self, parser):
        parser.add_argument(
            "team_id",
            type=int,
            help="Team ID that should receive the digest",
        )

    def handle(self, **options):
        team_id = options["team_id"]

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team with ID {team_id} does not exist.")

        self.stdout.write(f"Team: {team.name} (ID: {team_id})")
        self.stdout.write(f"Organization: {team.organization.name}")

        try:
            # Trigger the same logic as the daily digest for this specific team
            send_team_hog_functions_digest(team_id)
            self.stdout.write(self.style.SUCCESS(f"Successfully triggered HogFunctions digest for team {team_id}"))
        except Exception as e:
            raise CommandError(f"Failed to send digest: {str(e)}")
