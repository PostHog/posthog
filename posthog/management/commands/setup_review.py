import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from posthog.demo import _create_anonymous_users, _create_funnel, _recalculate
from posthog.models import Organization, OrganizationMembership, Team, User


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
        user = User.objects.create_superuser(email="test@posthog.com", password="pass")
        OrganizationMembership.objects.create(
            organization=organization, user=user, level=OrganizationMembership.Level.ADMIN
        )
        user.current_organization = organization
        user.current_team = team
        user.save()
        heroku_app_name = os.getenv("HEROKU_APP_NAME")
        base_url = f"https://{heroku_app_name}.herokuapp.com/demo/" if heroku_app_name else f"{settings.SITE_URL}/demo/"
        _create_anonymous_users(team=team, base_url=base_url)
        _create_funnel(team=team, base_url=base_url)
        _recalculate(team=team)
