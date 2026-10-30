from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models import Team

from ...logic.usage_scan import DEFAULT_LOOKBACK_DAYS, ScanAlreadyRunning, start_usage_scan


class Command(BaseCommand):
    help = "Start one data catalog usage scan for a team, without the usage flag or the weekly schedule."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team to scan.")
        parser.add_argument(
            "--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS, help="Days of usage the scan reads."
        )

    def handle(self, *args: object, team_id: int, lookback_days: int, **options: object) -> None:
        team = Team.objects.filter(id=team_id).first()
        if team is None:
            raise CommandError(f"Team {team_id} does not exist.")
        try:
            snapshot = start_usage_scan(team, lookback_days)
        except ScanAlreadyRunning:
            raise CommandError(f"A usage scan is already running for team {team_id}.")
        self.stdout.write(f"Started usage scan {snapshot.id} for team {team_id}.")
