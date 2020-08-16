from django.test import TestCase

from ..models.team import Team


class TestTeam(TestCase):
    def test_team_str(self):
        # Use the team.name by default
        team: Team = Team.objects.create(name="The Mighty Library")
        self.assertEqual(str(team), "The Mighty Library")

        # If the team has no name:

        # Team has one app_url
        team = Team.objects.create(app_urls=["app.posthog.com"])
        self.assertEqual(str(team), "app.posthog.com")

        # Team has multiple app_urls
        team = Team.objects.create(app_urls=["app.posthog.com", "custom.posthog.com"])
        self.assertEqual(str(team), "app.posthog.com, custom.posthog.com")

        # Team has empty app_url
        team = Team.objects.create(app_urls=[""])
        self.assertEqual(str(team), str(team.pk))

        # Team has no app_urls
        team = Team.objects.create(app_urls=[])
        self.assertEqual(str(team), str(team.pk))
