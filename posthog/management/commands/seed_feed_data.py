# ruff: noqa: T201 allow print statements

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from posthog.models import Dashboard, EventDefinition, FeatureFlag, Survey, Team


class Command(BaseCommand):
    help = "Seed database with sample data for the feed page"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            help="Team ID to create data for (defaults to first team)",
        )
        parser.add_argument(
            "--days-ago",
            type=int,
            default=5,
            help="How many days ago to create the data (default: 5)",
        )

    def handle(self, *args, **options):
        team_id = options.get("team_id")
        days_ago = options.get("days_ago", 5)

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

        self.stdout.write(f"Creating feed data for team: {team.name} (ID: {team.id})")
        self.stdout.write(f"Creating items for each day from {days_ago} days ago until today\n")

        # Get a user for created_by
        user = team.organization.members.first()
        user_id = user.id if user else None

        total_created = 0

        # Loop through each day from days_ago to 0 (today)
        for day_offset in range(days_ago, -1, -1):
            created_at = timezone.now() - timedelta(days=day_offset)
            day_label = f"Day {days_ago - day_offset + 1}"

            self.stdout.write(self.style.WARNING(f"\n{day_label} ({day_offset} days ago):"))

            # Create dashboards
            dashboards = [
                {
                    "name": f"Product Analytics Dashboard - {day_label}",
                    "description": f"Dashboard created on {day_label}",
                },
                {"name": f"Marketing Performance - {day_label}", "description": f"Marketing metrics for {day_label}"},
            ]

            for dashboard_data in dashboards:
                dashboard, created = Dashboard.objects.get_or_create(
                    team=team,
                    name=dashboard_data["name"],
                    defaults={
                        "description": dashboard_data["description"],
                        "created_at": created_at,
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Created dashboard: {dashboard.name}"))
                    total_created += 1
                else:
                    dashboard.created_at = created_at
                    dashboard.save()
                    self.stdout.write(f"  • Updated dashboard: {dashboard.name}")

            # Create event definitions with day-specific names
            events = [
                f"user_action_{day_offset}",
                f"page_visit_{day_offset}",
            ]

            for event_name in events:
                event_def, created = EventDefinition.objects.get_or_create(
                    team=team,
                    name=event_name,
                    defaults={
                        "created_at": created_at,
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Created event definition: {event_name}"))
                    total_created += 1
                else:
                    event_def.created_at = created_at
                    event_def.save()
                    self.stdout.write(f"  • Updated event definition: {event_name}")

            # Create feature flags
            flags = [
                {"key": f"feature_test_{day_offset}", "name": f"Feature Test {day_label}"},
            ]

            for flag_data in flags:
                flag, created = FeatureFlag.objects.get_or_create(
                    team=team,
                    key=flag_data["key"],
                    defaults={
                        "name": flag_data["name"],
                        "created_by_id": user_id,
                        "created_at": created_at,
                        "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Created feature flag: {flag.name}"))
                    total_created += 1
                else:
                    flag.created_at = created_at
                    flag.save()
                    self.stdout.write(f"  • Updated feature flag: {flag.name}")

            # Create survey
            survey_data = {
                "name": f"Feedback Survey - {day_label}",
                "description": f"Survey created on {day_label}",
            }

            survey, created = Survey.objects.get_or_create(
                team=team,
                name=survey_data["name"],
                defaults={
                    "description": survey_data["description"],
                    "start_date": created_at,
                    "created_by_id": user_id,
                    "type": "popover",
                    "questions": [
                        {
                            "type": "rating",
                            "scale": 10,
                            "display": "number",
                            "question": "How likely are you to recommend us?",
                        }
                    ],
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"  ✓ Created survey: {survey.name}"))
                total_created += 1
            else:
                survey.start_date = created_at
                survey.save()
                self.stdout.write(f"  • Updated survey: {survey.name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Feed data seeded successfully!\n"
                f"Created {total_created} new items across {days_ago + 1} days.\n"
                f"Visit the feed page to see the results."
            )
        )
