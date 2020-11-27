import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.demo import ORGANIZATION_NAME, TEAM_NAME, _create_anonymous_users, _create_funnel, _recalculate
from posthog.models import User


class Command(BaseCommand):
    help = "Set up the instance for development/review with demo data"

    def handle(self, *args, **options):
        with transaction.atomic():
            organization, team, user = User.objects.bootstrap(
                company_name=ORGANIZATION_NAME,
                email="test@posthog.com",
                password="pass",
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
            heroku_app_name = os.getenv("HEROKU_APP_NAME")
            base_url = (
                f"https://{heroku_app_name}.herokuapp.com/demo/" if heroku_app_name else f"{settings.SITE_URL}/demo/"
            )
            _create_anonymous_users(team=team, base_url=base_url)
            _create_funnel(team=team, base_url=base_url)
            _recalculate(team=team)
