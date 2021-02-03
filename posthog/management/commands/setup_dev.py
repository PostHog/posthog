from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.demo import ORGANIZATION_NAME, TEAM_NAME, create_demo_data
from posthog.models import User


class Command(BaseCommand):
    help = "Set up the instance for development/review with demo data"

    def handle(self, *args, **options):
        with transaction.atomic():
            organization, team, user = User.objects.bootstrap(
                company_name=ORGANIZATION_NAME,
                email="test@posthog.com",
                password="12345678",
                first_name="Jane Doe",
                is_staff=True,
                team_fields={
                    "name": TEAM_NAME,
                    "completed_snippet_onboarding": True,
                    "ingested_event": True,
                    "event_names": ["$pageview", "$autocapture"],
                    "event_properties": ["$current_url", "$browser", "$os"],
                },
            )
            create_demo_data(team)
