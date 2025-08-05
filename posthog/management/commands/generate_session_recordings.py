from django.core.management.base import BaseCommand, CommandError

from posthog.demo.matrix.session_data_fetcher import SessionDataFetcher
from posthog.demo.matrix.session_replay_generator import SessionReplayGenerator
from posthog.models.team.team import Team


class Command(BaseCommand):
    help = "Generate session recordings from real PostHog data using Playwright"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to fetch session data from")
        parser.add_argument(
            "--max-sessions", type=int, default=5, help="Maximum number of sessions to replay (default: 5)"
        )
        parser.add_argument(
            "--days-back", type=int, default=90, help="How many days back to look for sessions (default: 90)"
        )
        parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")

    def handle(self, *args, **options):
        team_id = options["team_id"]
        max_sessions = options["max_sessions"]
        days_back = options["days_back"]
        headless = options["headless"]

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team with ID {team_id} does not exist")

        self.stdout.write("Fetching session data from database...")
        fetcher = SessionDataFetcher(team)
        sessions = fetcher.fetch_sessions_for_replay(max_sessions=max_sessions, days_back=days_back)
        if not sessions:
            self.stdout.write(self.style.WARNING("No suitable sessions found for replay"))
            return
        self.stdout.write(f"Found {len(sessions)} sessions to replay")

        generator = SessionReplayGenerator(posthog_api_token=team.api_token, headless=headless)
        generator.generate_session_recordings(sessions=sessions, print_progress=True)

        self.stdout.write(self.style.SUCCESS(f"Successfully generated {len(sessions)} session recordings!"))
