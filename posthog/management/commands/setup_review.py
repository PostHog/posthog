import os

from django.core.management.base import BaseCommand
from django.db import connection

from posthog.demo import _create_anonymous_users, _create_funnel, _recalculate
from posthog.models import Team, User


class Command(BaseCommand):
    help = "Migrate data to new model"

    def handle(self, *args, **options):
        user = User.objects.create(email="test@posthog.com", password="pass")
        team = Team.objects.create_with_data(users=[user], name="PostHog")
        base_url = "https://{}.herokuapp.com/demo/".format(os.environ.get("HEROKU_APP_NAME"))
        _create_anonymous_users(team=team, base_url=base_url)
        _create_funnel(team=team, base_url=base_url)
        _recalculate(team=team)
