import random

from posthog.demo import create_demo_team
from posthog.models import EventDefinition, Organization, Team, User
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
            list(EventDefinition.objects.filter(team=team).values_list("name", flat=True)), expected_events,
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
