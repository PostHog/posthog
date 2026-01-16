import json
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

    def _print_header(self):
        """Print a nice header banner."""
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("═" * 80))
        self.stdout.write(self.style.SUCCESS("  SESSION ANALYSIS WORKFLOW"))
        self.stdout.write(self.style.SUCCESS("═" * 80))
        self.stdout.write("")

    def _print_section(self, title: str):
        """Print a section header."""
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO(f"  {title}"))
        self.stdout.write(self.style.HTTP_INFO("  " + "─" * 76))

    def _print_key_value(self, key: str, value: str, indent: int = 2):
        """Print a key-value pair with nice formatting."""
        spaces = " " * indent
        self.stdout.write(f"{spaces}{self.style.HTTP_INFO(key + ':')} {value}")

    def handle(self, *args, **options):
        session_id = options["session_id"]
        team_id = options["team_id"]
        user_id = options["user_id"]

        self._print_header()

        # Get team
        self._print_section("Configuration")
        if team_id:
            try:
                team = Team.objects.get(id=team_id)
            except Team.DoesNotExist:
                self.stdout.write("")
                self.stdout.write(self.style.ERROR("  ERROR"))
                self.stdout.write(self.style.ERROR("  " + "─" * 76))
                self.stdout.write(self.style.ERROR(f"  Team with ID {team_id} not found"))
                self.stdout.write("")
                return
        else:
            team = Team.objects.first()
            if not team:
                self.stdout.write("")
                self.stdout.write(self.style.ERROR("  ERROR"))
                self.stdout.write(self.style.ERROR("  " + "─" * 76))
                self.stdout.write(self.style.ERROR("  No teams found in database"))
                self.stdout.write("")
                return

        self._print_key_value("Team", f"{team.name} (ID: {team.id})")

        # Get user
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                self.stdout.write("")
                self.stdout.write(self.style.ERROR("  ERROR"))
                self.stdout.write(self.style.ERROR("  " + "─" * 76))
                self.stdout.write(self.style.ERROR(f"  User with ID {user_id} not found"))
                self.stdout.write("")
                return
        else:
            user = User.objects.first()
            if not user:
                self.stdout.write("")
                self.stdout.write(self.style.ERROR("  ERROR"))
                self.stdout.write(self.style.ERROR("  " + "─" * 76))
                self.stdout.write(self.style.ERROR("  No users found in database"))
                self.stdout.write("")
                return

        self._print_key_value("User", f"{user.email} (ID: {user.id})")
        self._print_key_value("Session ID", session_id)
        self._print_key_value("Video Validation", "full")

        self._print_section("Starting Analysis")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("  Running SummarizeSingleSessionWorkflow..."))
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
            self.stdout.write(self.style.SUCCESS("═" * 80))
            self.stdout.write(self.style.SUCCESS("  ANALYSIS COMPLETE"))
            self.stdout.write(self.style.SUCCESS("═" * 80))
            self.stdout.write("")

            if not summary:
                self.stdout.write(self.style.WARNING("  No summary returned"))
                self.stdout.write("")
            else:
                self._print_section("Summary Results")
                self.stdout.write("")
                formatted = json.dumps(summary, indent=2, default=str)
                # Indent each line
                for line in formatted.split("\n"):
                    self.stdout.write(f"  {line}")
                self.stdout.write("")

        except Exception as e:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("═" * 80))
            self.stdout.write(self.style.ERROR("  ERROR"))
            self.stdout.write(self.style.ERROR("═" * 80))
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"  Error during analysis: {e}"))
            self.stdout.write("")
            self._print_section("Traceback")
            self.stdout.write("")
            for line in traceback.format_exc().split("\n"):
                if line.strip():
                    self.stdout.write(f"  {line}")
            self.stdout.write("")
            raise
