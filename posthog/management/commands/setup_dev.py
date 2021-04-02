from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.demo import ORGANIZATION_NAME, TEAM_NAME, create_demo_data
from posthog.models import PersonalAPIKey, User


class Command(BaseCommand):
    help = "Set up the instance for development/review with demo data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-data", action="store_true", help="Create demo account without data",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            _, team, user = User.objects.bootstrap(
                organization_name=ORGANIZATION_NAME,
                email="test@posthog.com",
                password="12345678",
                first_name="Jane Doe",
                is_staff=True,
                team_fields={
                    "name": TEAM_NAME,
                    "api_token": "e2e_token_1239",
                    "completed_snippet_onboarding": True,
                    "ingested_event": True,
                    "event_names": ["$pageview", "$autocapture"],
                    "event_properties": ["$current_url", "$browser", "$os"],
                },
            )

            PersonalAPIKey.objects.create(user=user, label="e2e_demo_api_key key", value="e2e_demo_api_key")
            if not options["no_data"]:
                create_demo_data(team)
