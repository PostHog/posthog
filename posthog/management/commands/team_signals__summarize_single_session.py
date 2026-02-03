import asyncio
import traceback

from django.core.management.base import BaseCommand

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session


class Command(BaseCommand):
    help = "Test video-based session analysis workflow using SummarizeSingleSessionWorkflow"

    def add_arguments(self, parser):
        parser.add_argument(
            "session_id",
            type=str,
            help="Session ID to analyze",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Team ID to use (default: uses first team)",
        )
        parser.add_argument(
            "--user-id",
            type=int,
            default=None,
            help="User ID to use (default: uses first user)",
        )

    def handle(self, *args, **options):
        session_id = options["session_id"]
        team_id = options["team_id"]
        user_id = options["user_id"]

        # Get team
        if team_id:
            try:
                team = Team.objects.get(id=team_id)
            except Team.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Team with ID {team_id} not found"))
                return
        else:
            team = Team.objects.first()
            if not team:
                self.stdout.write(self.style.ERROR("No teams found in database"))
                return

        self.stdout.write(f"Using team: {team.name} (ID: {team.id})")

        # Get user
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"User with ID {user_id} not found"))
                return
        else:
            user = User.objects.first()
            if not user:
                self.stdout.write(self.style.ERROR("No users found in database"))
                return

        self.stdout.write(f"Using user: {user.email} (ID: {user.id})")
        self.stdout.write(f"Session ID: {session_id}")
        self.stdout.write("")

        self.stdout.write(
            self.style.WARNING("Starting SummarizeSingleSessionWorkflow with video_validation_enabled='full'...")
        )
        self.stdout.write("")

        try:
            summary = asyncio.run(
                execute_summarize_session(
                    session_id=session_id,
                    user=user,
                    team=team,
                    video_validation_enabled="full",
                )
            )

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("=" * 80))
            self.stdout.write(self.style.SUCCESS("ANALYSIS COMPLETE"))
            self.stdout.write(self.style.SUCCESS("=" * 80))
            self.stdout.write("")

            if not summary:
                self.stdout.write(self.style.WARNING("No summary returned"))
            else:
                self.stdout.write("Summary:")
                self.stdout.write(str(summary))

        except Exception as e:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"Error during analysis: {e}"))

            self.stdout.write(traceback.format_exc())
            raise
