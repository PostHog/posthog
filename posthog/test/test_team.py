from unittest import mock

from posthog.models import Organization, PluginConfig, Team, User
from posthog.plugins.test.mock import mocked_plugin_requests_get

from .base import BaseTest


class TestTeam(BaseTest):
    def test_team_has_expected_defaults(self):
        team: Team = Team.objects.create(name="New Team", organization=self.organization)
        self.assertEqual(team.timezone, "UTC")
        self.assertEqual(team.data_attributes, ["data-attr"])

    def test_create_team_with_test_account_filters(self):
        team = Team.objects.create_with_data(organization=self.organization)
        self.assertEqual(
            team.test_account_filters,
            [
                {"key": "email", "value": "@posthog.com", "operator": "not_icontains", "type": "person"},
                {
                    "key": "$host",
                    "operator": "is_not",
                    "value": ["localhost:8000", "localhost:5000", "127.0.0.1:8000", "127.0.0.1:3000", "localhost:3000"],
                },
            ],
        )

        # test generic emails
        user = User.objects.create(email="test@gmail.com")
        organization = Organization.objects.create()
        organization.members.set([user])
        team = Team.objects.create_with_data(organization=organization)
        self.assertEqual(
            team.test_account_filters,
            [
                {
                    "key": "$host",
                    "operator": "is_not",
                    "value": ["localhost:8000", "localhost:5000", "127.0.0.1:8000", "127.0.0.1:3000", "localhost:3000"],
                },
            ],
        )

    @mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
    def test_preinstalled_are_autoenabled(self, mock_get):
        with self.settings(
            MULTI_TENANCY=False, PLUGINS_PREINSTALLED_URLS=["https://github.com/PostHog/helloworldplugin/"]
        ):
            _, _, new_team = Organization.objects.bootstrap(
                self.user, plugins_access_level=Organization.PluginsAccessLevel.INSTALL
            )

        self.assertEqual(PluginConfig.objects.filter(team=new_team, enabled=True).count(), 1)
        self.assertEqual(PluginConfig.objects.filter(team=new_team, enabled=True).get().plugin.name, "helloworldplugin")
        self.assertEqual(mock_get.call_count, 2)
