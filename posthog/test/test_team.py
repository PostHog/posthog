import random
from unittest import mock

from django.conf import settings

from posthog.demo import create_demo_team
from posthog.models import EventDefinition, Organization, PluginConfig, PropertyDefinition, Team, User
from posthog.models.dashboard_item import DashboardItem
from posthog.plugins.test.mock import mocked_plugin_requests_get
from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage_for_team

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

    def test_updating_team_events_or_related_updates_event_definitions(self):
        random.seed(900)  # ensure random data is consistent
        org = Organization.objects.create(name="Demo Org")
        team = create_demo_team(org, None, None)

        expected_events = ["watched_movie", "installed_app", "rated_app", "purchase", "entered_free_trial", "$pageview"]

        self.assertEqual(EventDefinition.objects.filter(team=team).count(), len(expected_events))

        for obj in EventDefinition.objects.filter(team=team):
            self.assertIn(obj.name, expected_events)
            self.assertEqual(obj.volume_30_day, None)
            self.assertEqual(obj.query_usage_30_day, None)

        DashboardItem.objects.create(team=team, filters={"events": [{"id": "$pageview"}]})
        # Test events with usage
        expected_event_definitions = [
            {"name": "installed_app", "volume_30_day": 100, "query_usage_30_day": 0},
            {"name": "rated_app", "volume_30_day": 73, "query_usage_30_day": 0},
            {"name": "purchase", "volume_30_day": 16, "query_usage_30_day": 0},
            {"name": "entered_free_trial", "volume_30_day": 0, "query_usage_30_day": 0},
            {"name": "watched_movie", "volume_30_day": 87, "query_usage_30_day": 0},
            {"name": "$pageview", "volume_30_day": 327, "query_usage_30_day": 1},
        ]
        calculate_event_property_usage_for_team(team.pk)

        self.assertEqual(EventDefinition.objects.filter(team=team).count(), len(expected_event_definitions))
        for item in expected_event_definitions:
            instance = EventDefinition.objects.get(name=item["name"], team=team)
            self.assertEqual(instance.volume_30_day, item["volume_30_day"], item)
            self.assertEqual(instance.query_usage_30_day, item["query_usage_30_day"], item)

    def test_updating_event_properties_or_related_updates_property_definitions(self):
        random.seed(900)
        org = Organization.objects.create(name="Demo Org")
        team = create_demo_team(org, None, None)

        expected_properties = [
            "purchase",
            "$current_url",
            "$browser",
            "is_first_movie",
            "app_rating",
            "plan",
            "first_visit",
            "purchase_value",
        ]
        numerical_properties = ["purchase", "app_rating", "purchase_value"]

        self.assertCountEqual(
            PropertyDefinition.objects.filter(team=team).values_list("name", flat=True),
            expected_properties,
            PropertyDefinition.objects.filter(team=team).values("name"),
        )

        for obj in PropertyDefinition.objects.filter(team=team):
            self.assertIn(obj.name, expected_properties)
            self.assertEqual(obj.volume_30_day, None)
            self.assertEqual(obj.query_usage_30_day, None)
            self.assertEqual(obj.is_numerical, obj.name in numerical_properties)

        DashboardItem.objects.create(team=team, filters={"properties": [{"key": "$browser", "value": "Safari"}]})
        # Test events with usage
        expected_property_definitions = [
            {"name": "$current_url", "query_usage_30_day": 0, "is_numerical": False},
            {"name": "is_first_movie", "query_usage_30_day": 0, "is_numerical": False},
            {"name": "app_rating", "query_usage_30_day": 0, "is_numerical": True},
            {"name": "plan", "query_usage_30_day": 0, "is_numerical": False},
            {"name": "purchase", "query_usage_30_day": 0, "is_numerical": True},
            {"name": "purchase_value", "query_usage_30_day": 0, "is_numerical": True},
            {"name": "first_visit", "query_usage_30_day": 0, "is_numerical": False},
            {"name": "$browser", "query_usage_30_day": 1, "is_numerical": False},
        ]
        calculate_event_property_usage_for_team(team.pk)

        self.assertEqual(PropertyDefinition.objects.filter(team=team).count(), len(expected_property_definitions))
        for item in expected_property_definitions:
            instance = PropertyDefinition.objects.get(name=item["name"], team=team)
            self.assertEqual(instance.query_usage_30_day, item["query_usage_30_day"], item)
            self.assertEqual(instance.is_numerical, item["is_numerical"], item)

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
