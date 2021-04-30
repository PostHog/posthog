import random

from posthog.demo import create_demo_team
from posthog.models import EventDefinition, Organization, Team, User
from posthog.models.property_definition import PropertyDefinition
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

    # TODO: #4070 Temporary test until relevant attributes are migrated from `Team` model
    def test_updating_team_events_or_related_updates_event_definitions(self):
        random.seed(900)
        org = Organization.objects.create(name="Demo Org")
        team = create_demo_team(org, None, None)

        expected_events = ["watched_movie", "installed_app", "rated_app", "purchase", "entered_free_trial"]

        self.assertEqual(EventDefinition.objects.filter(team=team).count(), len(expected_events))

        for obj in EventDefinition.objects.filter(team=team):
            self.assertIn(obj.name, expected_events)
            self.assertEqual(obj.volume_30_day, None)
            self.assertEqual(obj.query_usage_30_day, None)

        # Test adding and removing one event
        team.event_names.pop(0)
        team.event_names.append("uninstalled_app")
        team.save()
        expected_events = ["installed_app", "rated_app", "purchase", "entered_free_trial", "uninstalled_app"]
        self.assertEqual(
            list(EventDefinition.objects.filter(team=team).values_list("name", flat=True)).sort(),
            expected_events.sort(),
        )

        # Test events with usage
        expected_event_definitions = [
            {"name": "installed_app", "volume_30_day": 100, "query_usage_30_day": 0},
            {"name": "rated_app", "volume_30_day": 73, "query_usage_30_day": 0},
            {"name": "purchase", "volume_30_day": 16, "query_usage_30_day": 0},
            {"name": "entered_free_trial", "volume_30_day": 0, "query_usage_30_day": 0},
            {"name": "uninstalled_app", "volume_30_day": 0, "query_usage_30_day": 0},
            {"name": "$pageview", "volume_30_day": 1822, "query_usage_30_day": 19292},
        ]
        calculate_event_property_usage_for_team(team.pk)
        team.refresh_from_db()
        team.event_names.append("$pageview")
        team.event_names_with_usage.append({"event": "$pageview", "volume": 1822, "usage_count": 19292})
        team.save()

        self.assertEqual(EventDefinition.objects.filter(team=team).count(), len(expected_event_definitions))
        for item in expected_event_definitions:
            instance = EventDefinition.objects.get(name=item["name"], team=team)
            self.assertEqual(instance.volume_30_day, item["volume_30_day"])
            self.assertEqual(instance.query_usage_30_day, item["query_usage_30_day"])

    # TODO: #4070 Temporary test until relevant attributes are migrated from `Team` model
    def test_updating_event_properties_or_related_updates_property_definitions(self):
        random.seed(900)
        org = Organization.objects.create(name="Demo Org")
        team = create_demo_team(org, None, None)

        expected_properties = [
            "purchase",
            "$current_url",
            "is_first_movie",
            "app_rating",
            "plan",
            "first_visit",
            "purchase_value",
        ]
        numerical_properties = ["purchase", "app_rating", "purchase_value"]

        self.assertEqual(PropertyDefinition.objects.filter(team=team).count(), len(expected_properties))

        for obj in PropertyDefinition.objects.filter(team=team):
            self.assertIn(obj.name, expected_properties)
            self.assertEqual(obj.volume_30_day, None)
            self.assertEqual(obj.query_usage_30_day, None)
            self.assertEqual(obj.is_numerical, obj.name in numerical_properties)

        # Test adding and removing one event
        team.event_properties.pop(-1)
        team.event_properties.append("paid_tier")
        team.save()
        expected_properties = [
            "purchase",
            "$current_url",
            "is_first_movie",
            "app_rating",
            "plan",
            "first_visit",
            "paid_tier",
        ]
        self.assertEqual(
            list(PropertyDefinition.objects.filter(team=team).values_list("name", flat=True)).sort(),
            expected_properties.sort(),
        )

        # Test events with usage
        expected_property_definitions = [
            {"name": "$current_url", "volume_30_day": 264, "query_usage_30_day": 0, "is_numerical": False},
            {"name": "is_first_movie", "volume_30_day": 87, "query_usage_30_day": 0, "is_numerical": False},
            {"name": "app_rating", "volume_30_day": 73, "query_usage_30_day": 0, "is_numerical": True},
            {"name": "plan", "volume_30_day": 14, "query_usage_30_day": 0, "is_numerical": False},
            {"name": "purchase", "volume_30_day": 0, "query_usage_30_day": 0, "is_numerical": True},
            {"name": "paid_tier", "volume_30_day": 0, "query_usage_30_day": 0, "is_numerical": False},
            {"name": "first_visit", "volume_30_day": 0, "query_usage_30_day": 0, "is_numerical": False},
            {"name": "$browser", "volume_30_day": 166, "query_usage_30_day": 349, "is_numerical": True},
        ]
        calculate_event_property_usage_for_team(team.pk)
        team.refresh_from_db()
        team.event_properties.append("$browser")
        team.event_properties_numerical.append("$browser")
        team.event_properties_with_usage.append({"key": "$browser", "volume": 166, "usage_count": 349})
        team.save()

        self.assertEqual(PropertyDefinition.objects.filter(team=team).count(), len(expected_property_definitions))
        for item in expected_property_definitions:
            instance = PropertyDefinition.objects.get(name=item["name"], team=team)
            self.assertEqual(instance.volume_30_day, item["volume_30_day"])
            self.assertEqual(instance.query_usage_30_day, item["query_usage_30_day"])
            self.assertEqual(instance.is_numerical, item["is_numerical"])
