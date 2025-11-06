from django.core.management.base import BaseCommand

from posthog.models import Team

from products.synthetic_monitoring.backend.models import SyntheticMonitor


class Command(BaseCommand):
    help = "Create a test synthetic monitor for development/testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            help="Team ID to create monitor for (defaults to first team)",
        )
        parser.add_argument(
            "--url",
            type=str,
            default="https://httpbin.org/status/200",
            help="URL to monitor (default: https://httpbin.org/status/200)",
        )
        parser.add_argument(
            "--name",
            type=str,
            default="Test Monitor",
            help="Monitor name (default: Test Monitor)",
        )
        parser.add_argument(
            "--frequency",
            type=int,
            default=1,
            choices=[1, 5, 15, 30, 60],
            help="Check frequency in minutes (default: 1)",
        )
        parser.add_argument(
            "--regions",
            type=str,
            default="us-east-2,eu-west-1",
            help="Comma-separated list of regions (default: us-east-2,eu-west-1)",
        )
        parser.add_argument(
            "--enabled",
            action="store_true",
            default=True,
            help="Enable the monitor (default: True)",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]

        if not team_id:
            team = Team.objects.first()
            if not team:
                self.stdout.write(self.style.ERROR("No teams found. Please create a team first."))
                return
            team_id = team.id
        else:
            try:
                team = Team.objects.get(id=team_id)
            except Team.DoesNotExist:
                self.stdout.write(self.style.ERROR(f"Team with ID {team_id} not found."))
                return

        # Parse regions
        regions = [r.strip() for r in options["regions"].split(",") if r.strip()]

        # Create monitor
        monitor = SyntheticMonitor.objects.create(
            team=team,
            name=options["name"],
            url=options["url"],
            frequency_minutes=options["frequency"],
            regions=regions,
            method="GET",
            expected_status_code=200,
            timeout_seconds=30,
            enabled=options["enabled"],
        )

        self.stdout.write(self.style.SUCCESS(f"\n✓ Created synthetic monitor:"))
        self.stdout.write(f"  ID: {monitor.id}")
        self.stdout.write(f"  Name: {monitor.name}")
        self.stdout.write(f"  URL: {monitor.url}")
        self.stdout.write(f"  Team: {team.name} (ID: {team.id})")
        self.stdout.write(f"  Frequency: Every {monitor.frequency_minutes} minute(s)")
        self.stdout.write(f"  Regions: {', '.join(monitor.regions)}")
        self.stdout.write(f"  Enabled: {monitor.enabled}")
        self.stdout.write(f"\n✓ The monitor will be checked on the next scheduler run (every 60 seconds)")
        self.stdout.write(f"✓ Check Temporal UI at http://localhost:8081 to see executions")
