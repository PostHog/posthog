from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.demo import ORGANIZATION_NAME, TEAM_NAME, create_demo_data
from posthog.models import EventDefinition, PersonalAPIKey, User
from posthog.models.property_definition import PropertyDefinition


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
                },
            )
            EventDefinition.objects.create(team=team, name="$pageview")
            EventDefinition.objects.create(team=team, name="$autocapture")
            PropertyDefinition.objects.create(team=team, name="$current_url")
            PropertyDefinition.objects.create(team=team, name="$browser")
            PropertyDefinition.objects.create(team=team, name="$os")
            PropertyDefinition.objects.create(team=team, name="usage_count", is_numerical=True)
            PropertyDefinition.objects.create(team=team, name="volume", is_numerical=True)
            PropertyDefinition.objects.create(team=team, name="is_first_movie")

            PersonalAPIKey.objects.create(user=user, label="e2e_demo_api_key key", value="e2e_demo_api_key")
            if not options["no_data"]:
                create_demo_data(team)
