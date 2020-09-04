import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from posthog.demo import _create_anonymous_users, _create_funnel, _recalculate
from posthog.models import Team, User


class Command(BaseCommand):
    help = "Set up review instance with demo data"

    def handle(self, *args, **options):
        user = User.objects.create(email="test@posthog.com", is_staff=True)
        user.set_password("pass")
        user.save()
        team = Team.objects.create_with_data(
            users=[user],
            name="PostHog",
            completed_snippet_onboarding=True,
            event_names=["$pageview", "$autocapture"],
            event_properties=["$current_url", "$browser", "$os"],
        )
        heroku_app_name = os.getenv("HEROKU_APP_NAME")
        base_url = f"https://{heroku_app_name}.herokuapp.com/demo/" if heroku_app_name else f"{settings.SITE_URL}/demo/"
        _create_anonymous_users(team=team, base_url=base_url)
        _create_funnel(team=team, base_url=base_url)
        _recalculate(team=team)
