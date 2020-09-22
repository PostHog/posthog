import os

from django.core.management.base import BaseCommand
from django.db import connection

from posthog.demo import _create_anonymous_users, _create_funnel, _recalculate
from posthog.models import Organization, Team, User


class Command(BaseCommand):
    help = "Set up review instance with demo data"

    def handle(self, *args, **options):
        organization = Organization.objects.create(name="Hogflix")
        team = Team.objects.create_with_data(
            organization=organization,
            name="Hogflix App",
            completed_snippet_onboarding=True,
            event_names=["$pageview", "$autocapture"],
            event_properties=["$current_url", "$browser", "$os"],
        )
        User.objects.create_and_join(organization, team, email="test@posthog.com", password="pass")
        base_url = "https://{}.herokuapp.com/demo/".format(os.environ.get("HEROKU_APP_NAME"))
        _create_anonymous_users(team=team, base_url=base_url)
        _create_funnel(team=team, base_url=base_url)
        _recalculate(team=team)
