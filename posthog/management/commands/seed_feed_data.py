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

        created_at = timezone.now() - timedelta(days=days_ago)

        # Get a user for created_by
        user = team.organization.members.first()
        user_id = user.id if user else None

        # Create dashboards
        dashboards = [
            {"name": "Product Analytics Dashboard", "description": "Main product analytics dashboard"},
            {"name": "Marketing Performance", "description": "Marketing KPIs and metrics"},
            {"name": "User Engagement Metrics", "description": "Track user engagement over time"},
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
                self.stdout.write(self.style.SUCCESS(f"✓ Created dashboard: {dashboard.name}"))
            else:
                # Update created_at if it already exists
                dashboard.created_at = created_at
                dashboard.save()
                self.stdout.write(self.style.WARNING(f"• Updated dashboard: {dashboard.name}"))

        # Create event definitions
        events = [
            "button_clicked",
            "page_viewed",
            "form_submitted",
            "video_played",
            "checkout_completed",
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
                self.stdout.write(self.style.SUCCESS(f"✓ Created event definition: {event_name}"))
            else:
                event_def.created_at = created_at
                event_def.save()
                self.stdout.write(self.style.WARNING(f"• Updated event definition: {event_name}"))

        # Create feature flags
        flags = [
            {"key": "new_checkout_flow", "name": "New Checkout Flow"},
            {"key": "dark_mode", "name": "Dark Mode"},
            {"key": "ai_recommendations", "name": "AI Recommendations"},
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
                self.stdout.write(self.style.SUCCESS(f"✓ Created feature flag: {flag.name}"))
            else:
                flag.created_at = created_at
                flag.save()
                self.stdout.write(self.style.WARNING(f"• Updated feature flag: {flag.name}"))

        # Create surveys
        surveys = [
            {
                "name": "Product Feedback Survey",
                "description": "Gather feedback on our new features",
            },
            {
                "name": "NPS Survey",
                "description": "Net Promoter Score survey",
            },
        ]

        for survey_data in surveys:
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
                self.stdout.write(self.style.SUCCESS(f"✓ Created survey: {survey.name}"))
            else:
                survey.start_date = created_at
                survey.save()
                self.stdout.write(self.style.WARNING(f"• Updated survey: {survey.name}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Feed data seeded successfully! Items created {days_ago} days ago.\n"
                f"Visit the feed page to see the results."
            )
        )
