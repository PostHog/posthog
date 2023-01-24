from unittest import mock

from posthog.models import Dashboard, DashboardTile, Organization, PluginConfig, Team, User
from posthog.models.instance_setting import override_instance_config
from posthog.models.team import util
from posthog.plugins.test.mock import mocked_plugin_requests_get

from .base import BaseTest

util.can_enable_actor_on_events = True


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
                    "type": "event",
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
                    "type": "event",
                }
            ],
        )

    def test_create_team_sets_primary_dashboard(self):
        team = Team.objects.create_with_data(organization=self.organization)
        self.assertIsInstance(team.primary_dashboard, Dashboard)

        # Ensure insights are created and linked
        self.assertEqual(DashboardTile.objects.filter(dashboard=team.primary_dashboard).count(), 6)

    @mock.patch("requests.get", side_effect=mocked_plugin_requests_get)
    def test_preinstalled_are_autoenabled(self, mock_get):
        with self.is_cloud(False):
            with self.settings(PLUGINS_PREINSTALLED_URLS=["https://github.com/PostHog/helloworldplugin/"]):
                _, _, new_team = Organization.objects.bootstrap(
                    self.user, plugins_access_level=Organization.PluginsAccessLevel.INSTALL
                )

        self.assertEqual(PluginConfig.objects.filter(team=new_team, enabled=True).count(), 1)
        self.assertEqual(PluginConfig.objects.filter(team=new_team, enabled=True).get().plugin.name, "helloworldplugin")
        self.assertEqual(mock_get.call_count, 2)

    @mock.patch("posthoganalytics.feature_enabled", return_value=True)
    def test_team_on_cloud_uses_feature_flag_to_determine_person_on_events(self, mock_feature_enabled):
        with self.is_cloud(True):
            with override_instance_config("PERSON_ON_EVENTS_ENABLED", False):
                team = Team.objects.create_with_data(organization=self.organization)
                self.assertTrue(team.person_on_events_querying_enabled)
                # called more than once when evaluating hogql
                mock_feature_enabled.assert_called_with(
                    "person-on-events-enabled",
                    str(team.uuid),
                    groups={"organization": str(self.organization.id)},
                    group_properties={
                        "organization": {
                            "id": str(self.organization.id),
                            "created_at": self.organization.created_at,
                        }
                    },
                    only_evaluate_locally=True,
                )

    @mock.patch("posthoganalytics.feature_enabled", return_value=False)
    def test_team_on_self_hosted_uses_instance_setting_to_determine_person_on_events(self, mock_feature_enabled):

        with self.is_cloud(False):
            with override_instance_config("PERSON_ON_EVENTS_ENABLED", True):
                team = Team.objects.create_with_data(organization=self.organization)
                self.assertTrue(team.person_on_events_querying_enabled)
                mock_feature_enabled.assert_not_called()

            with override_instance_config("PERSON_ON_EVENTS_ENABLED", False):
                team = Team.objects.create_with_data(organization=self.organization)
                self.assertFalse(team.person_on_events_querying_enabled)
                mock_feature_enabled.assert_not_called()
