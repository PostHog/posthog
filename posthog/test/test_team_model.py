from django.test import TestCase

from ..models.team import Team


class TestTeam(TestCase):
    def test_team_str(self):
        # 1. Use the team.name by default
        team: Team = Team.objects.create(name="The Mighty Library")
        self.assertEqual(str(team), "The Mighty Library")

        # 2. If the team has no name:

        # 2.1 Team has one app_url
        team = Team.objects.create(app_urls=["app.posthog.com"])
        self.assertEqual(str(team), "app.posthog.com")

        # 2.2 Team has multiple app_urls
        team = Team.objects.create(app_urls=["app.posthog.com", "custom.posthog.com"])
        self.assertEqual(str(team), "app.posthog.com, custom.posthog.com")

        # 2.3 Team has empty app_url
        team = Team.objects.create(app_urls=[""])
        self.assertEqual(str(team), str(team.pk))

        # 2.3 Team has no app_urls
        team = Team.objects.create(app_urls=[])
        self.assertEqual(str(team), str(team.pk))
