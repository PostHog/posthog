import random
from typing import Callable

from freezegun import freeze_time

from posthog.demo import create_demo_team
from posthog.models import Event, Insight, Organization, Team
from posthog.models.event_definition import EventDefinition
from posthog.models.property_definition import PropertyDefinition
from posthog.tasks.calculate_event_property_usage import calculate_event_property_usage_for_team
from posthog.test.base import BaseTest


def calculate_event_property_usage_test_factory(create_event: Callable) -> Callable:
    class Test(BaseTest):
        def test_updating_team_events_or_related_updates_event_definitions(self) -> None:
            random.seed(900)  # ensure random data is consistent
            org = Organization.objects.create(name="Demo Org")
            team = create_demo_team(org, None, None)

            expected_events = [
                "watched_movie",
                "installed_app",
                "rated_app",
                "purchase",
                "entered_free_trial",
                "$pageview",
            ]

            self.assertEqual(EventDefinition.objects.filter(team=team).count(), len(expected_events))

            for obj in EventDefinition.objects.filter(team=team):
                self.assertIn(obj.name, expected_events)
                self.assertEqual(obj.volume_30_day, None)
                self.assertEqual(obj.query_usage_30_day, None)

            Insight.objects.create(team=team, filters={"events": [{"id": "$pageview"}]})
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

        def test_updating_event_properties_or_related_updates_property_definitions(self) -> None:
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

            Insight.objects.create(team=team, filters={"properties": [{"key": "$browser", "value": "Safari"}]})
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

        def test_calculate_usage(self) -> None:
            EventDefinition.objects.create(team=self.team, name="$pageview")
            EventDefinition.objects.create(team=self.team, name="custom event")
            PropertyDefinition.objects.create(team=self.team, name="$current_url")
            PropertyDefinition.objects.create(team=self.team, name="team_id")
            PropertyDefinition.objects.create(team=self.team, name="value")
            team2 = Organization.objects.bootstrap(None)[2]
            with freeze_time("2020-08-01"):
                # ignore stuff older than 30 days
                Insight.objects.create(
                    team=self.team,
                    filters={
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$current_url", "value": "https://posthog.com"}],
                    },
                )
                create_event(
                    distinct_id="test",
                    team=self.team,
                    event="$pageview",
                    properties={"$current_url": "https://posthog.com"},
                )
            with freeze_time("2020-10-01"):
                Insight.objects.create(
                    team=self.team,
                    filters={
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$current_url", "value": "https://posthog.com"}],
                    },
                )
                Insight.objects.create(
                    team=self.team,
                    filters={
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$current_url", "value": "https://posthog2.com"}],
                    },
                )
                Insight.objects.create(
                    team=self.team,
                    filters={"events": [{"id": "custom event"}], "properties": [{"key": "team_id", "value": "3"}]},
                )
                Insight.objects.create(team=self.team, filters={"events": [{"id": "event that doesnt exist"}]})
                # broken dashboard item
                Insight.objects.create(team=self.team, filters={})
                create_event(
                    distinct_id="test",
                    team=self.team,
                    event="$pageview",
                    properties={"$current_url": "https://posthog.com"},
                )
                create_event(
                    distinct_id="test",
                    team=self.team,
                    event="$pageview",
                    properties={"$current_url": "https://posthog2.com"},
                )
                create_event(distinct_id="test", team=self.team, event="custom event", properties={"team_id": "3"})

                # team leakage
                create_event(
                    distinct_id="test",
                    team=team2,
                    event="$pageview",
                    properties={"$current_url": "https://posthog.com"},
                )
                Insight.objects.create(
                    team=team2,
                    filters={
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$current_url", "value": "https://posthog.com"}],
                    },
                )

                calculate_event_property_usage_for_team(self.team.pk)
            self.assertEqual(2, EventDefinition.objects.get(team=self.team, name="$pageview").query_usage_30_day)
            self.assertEqual(2, EventDefinition.objects.get(team=self.team, name="$pageview").volume_30_day)

            self.assertEqual(1, EventDefinition.objects.get(team=self.team, name="custom event").query_usage_30_day)
            self.assertEqual(1, EventDefinition.objects.get(team=self.team, name="custom event").volume_30_day)

            self.assertEqual(2, PropertyDefinition.objects.get(team=self.team, name="$current_url").query_usage_30_day)
            self.assertEqual(1, PropertyDefinition.objects.get(team=self.team, name="team_id").query_usage_30_day)
            self.assertEqual(0, PropertyDefinition.objects.get(team=self.team, name="value").query_usage_30_day)

    return Test


class Test(calculate_event_property_usage_test_factory(Event.objects.create)):  # type: ignore
    pass
