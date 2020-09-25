import os

from django.core.management.base import BaseCommand
from django.db import connection

from posthog.demo import _create_anonymous_users, _create_funnel, _recalculate
from posthog.models import User


class Command(BaseCommand):
    help = "Set up the instance for development/review with demo data"

    def handle(self, *args, **options):
        organization, team, user = User.objects.bootstrap(
            company_name="Hogflix",
            email="test@posthog.com",
            password="pass",
            first_name="Mr. Pokee",
            team_fields={
                "name": "Hogflix App",
                "completed_snippet_onboarding": True,
                "event_names": ["$pageview", "$autocapture"],
                "event_properties": ["$current_url", "$browser", "$os"],
            },
        )
        base_url = "https://{}.herokuapp.com/demo/".format(os.environ.get("HEROKU_APP_NAME"))
        _create_anonymous_users(team=team, base_url=base_url)
        _create_funnel(team=team, base_url=base_url)
        _recalculate(team=team)
