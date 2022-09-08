import random
from unittest.mock import MagicMock, call, patch

from freezegun import freeze_time

from posthog.models import EventDefinition, EventProperty, Insight, Organization, PropertyDefinition, Team
from posthog.tasks.calculate_event_property_usage import (
    calculate_event_property_usage,
    calculate_event_property_usage_for_team,
)
from posthog.test.base import BaseTest, ClickhouseTestMixin
from posthog.test.base import _create_event as create_event
from posthog.test.base import _create_person as create_person
from posthog.test.base import flush_persons_and_events


class TestCalculateEventPropertyUsage(ClickhouseTestMixin, BaseTest):
    def test_updating_team_events_or_related_updates_event_definitions(self) -> None:
        random.seed(900)  # ensure random data is consistent

        create_event(event="watched_movie", team=self.team, distinct_id="user1")
        create_event(event="$pageview", team=self.team, distinct_id="user1")
        create_event(event="$pageview", team=self.team, distinct_id="user1")
        expected_events = ["watched_movie", "$pageview"]
        EventDefinition.objects.create(name="watched_movie", team=self.team)
        EventDefinition.objects.create(name="$pageview", team=self.team)

        for obj in EventDefinition.objects.filter(team=self.team):
            self.assertIn(obj.name, expected_events)
            self.assertEqual(obj.volume_30_day, None)
            self.assertEqual(obj.query_usage_30_day, None)

        Insight.objects.create(team=self.team, filters={"events": [{"id": "$pageview"}]})
        # Test events with usage
        expected_event_definitions = [
            {"name": "$pageview", "volume_30_day": 2, "query_usage_30_day": 1},
            {"name": "watched_movie", "volume_30_day": 1, "query_usage_30_day": 0},
        ]
        calculate_event_property_usage_for_team(self.team.pk)

        self.assertEqual(EventDefinition.objects.filter(team=self.team).count(), len(expected_event_definitions))
        for item in expected_event_definitions:
            instance = EventDefinition.objects.get(name=item["name"], team=self.team)
            self.assertEqual(instance.volume_30_day, item["volume_30_day"], item)
            self.assertEqual(instance.query_usage_30_day, item["query_usage_30_day"], item)

    def test_updating_event_properties_or_related_updates_property_definitions(self) -> None:
        random.seed(900)
        org = Organization.objects.create(name="Demo Org")
        team = Team.objects.create(organization=org)

        create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user1",
            properties={"$current_url": "http://test.com", "$browser": "Safari"},
        )
        create_event(
            event="$pageview",
            team=self.team,
            distinct_id="user1",
            properties={"$current_url": "http://test.com", "$browser": "Safari"},
        )
        create_event(event="watched_movie", team=self.team, distinct_id="user1", properties={"app_rating": 5})

        PropertyDefinition.objects.create(name="$current_url", team=team)
        PropertyDefinition.objects.create(name="$browser", team=team)
        PropertyDefinition.objects.create(name="app_rating", team=team, is_numerical=True)

        Insight.objects.create(team=team, filters={"properties": [{"key": "$browser", "value": "Safari"}]})
        # Test events with usage
        expected_property_definitions = [
            {"name": "$current_url", "query_usage_30_day": 0, "is_numerical": False},
            {"name": "app_rating", "query_usage_30_day": 0, "is_numerical": True},
            {"name": "$browser", "query_usage_30_day": 1, "is_numerical": False},
        ]
        calculate_event_property_usage_for_team(team.pk)

        self.assertEqual(PropertyDefinition.objects.filter(team=team).count(), len(expected_property_definitions))
        for item in expected_property_definitions:
            instance = PropertyDefinition.objects.get(name=item["name"], team=team)
            self.assertEqual(instance.query_usage_30_day, item["query_usage_30_day"], item)
            self.assertEqual(instance.is_numerical, item["is_numerical"], item)

    @patch("posthog.tasks.calculate_event_property_usage.calculate_event_property_usage_for_team")
    def test_recency_check_makes_subsequent_run_do_nothing(self, patched_calculate_for_team: MagicMock) -> None:
        org = Organization.objects.create(name="Demo Org")
        team = Team.objects.create(organization=org)
        team_two = Team.objects.create(organization=org)

        calculate_event_property_usage()

        # mock will have had two calls, one for team one, one for team two
        self.assertEqual(
            patched_calculate_for_team.call_args_list,
            [call(team_id=self.team.id), call(team_id=team.id), call(team_id=team_two.id)],
        )
        patched_calculate_for_team.reset_mock()

        team_created_after_first_run = Team.objects.create(organization=org)

        calculate_event_property_usage()  # new team isn't in recency check and will run

        # mock will only have had one call, for team_created_after_first_run
        self.assertEqual(patched_calculate_for_team.call_args_list, [call(team_id=team_created_after_first_run.id)])

    def test_calculate_usage(self) -> None:
        EventDefinition.objects.create(team=self.team, name="$pageview")
        EventDefinition.objects.create(team=self.team, name="custom event")
        PropertyDefinition.objects.create(team=self.team, name="$current_url")
        PropertyDefinition.objects.create(team=self.team, name="team_id")
        PropertyDefinition.objects.create(team=self.team, name="used property")
        PropertyDefinition.objects.create(team=self.team, name="unused property")
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
            # with property group
            Insight.objects.create(
                team=self.team,
                filters={
                    "events": [{"id": "$pageview"}],
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$current_url",
                                        "value": "https://posthog.com",
                                        "operator": "exact",
                                        "type": "event",
                                    },
                                    {
                                        "key": "$current_url",
                                        "value": "https://posthog2.com",
                                        "operator": "exact",
                                        "type": "event",
                                    },
                                ],
                            },
                            {
                                "type": "OR",
                                "values": [{"key": "used property", "value": 1, "operator": "gt", "type": "event"}],
                            },
                        ],
                    },
                },
            )

            series_with_properties = [
                {
                    "id": "$pageview",
                    "name": "$pageview",
                    "type": "events",
                    "order": 0,
                    "properties": [
                        {"key": "used property", "value": "series-filter", "operator": "icontains", "type": "event"}
                    ],
                }
            ]

            # with properties queried in events
            Insight.objects.create(
                team=self.team,
                filters={
                    "events": series_with_properties,
                    "properties": [{"key": "$current_url", "value": "https://posthog2.com"}],
                },
            )

            # with non group style properties
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
                distinct_id="test", team=team2, event="$pageview", properties={"$current_url": "https://posthog.com"}
            )
            Insight.objects.create(
                team=team2,
                filters={
                    "events": [{"id": "$pageview"}],
                    "properties": [{"key": "$current_url", "value": "https://posthog.com"}],
                },
            )

            calculate_event_property_usage_for_team(self.team.pk)

        self.assertEqual(3, EventDefinition.objects.get(team=self.team, name="$pageview").query_usage_30_day)
        self.assertEqual(2, EventDefinition.objects.get(team=self.team, name="$pageview").volume_30_day)

        self.assertEqual(1, EventDefinition.objects.get(team=self.team, name="custom event").query_usage_30_day)
        self.assertEqual(1, EventDefinition.objects.get(team=self.team, name="custom event").volume_30_day)

        self.assertEqual(4, PropertyDefinition.objects.get(team=self.team, name="$current_url").query_usage_30_day)
        self.assertEqual(1, PropertyDefinition.objects.get(team=self.team, name="team_id").query_usage_30_day)
        self.assertEqual(
            2, PropertyDefinition.objects.get(team=self.team, name="used property").query_usage_30_day
        )  # in a property group and in an events series filter
        self.assertEqual(0, PropertyDefinition.objects.get(team=self.team, name="unused property").query_usage_30_day)

    def test_complete_inference(self) -> None:
        assert EventDefinition.objects.count() == 0
        assert PropertyDefinition.objects.count() == 0
        assert EventProperty.objects.count() == 0

        create_person(distinct_ids=["xyz"], team=self.team, properties={"surname": "Rutherford"})
        create_event(
            distinct_id="xyz",
            team=self.team,
            event="element_discovered",
            properties={"symbol": "He", "atomic_number": 2},
        )
        create_event(
            distinct_id="xyz",
            team=self.team,
            event="element_discovered",
            properties={"symbol": "U", "atomic_number": 92},
        )
        flush_persons_and_events()
        Insight.objects.create(
            team=self.team,
            filters={"events": [{"id": "element_discovered"}], "properties": [{"key": "atomic_number", "value": "2"}]},
        )

        calculate_event_property_usage_for_team(self.team.pk, complete_inference=True)

        event_definitions = EventDefinition.objects.order_by("name").all()
        property_definitions = PropertyDefinition.objects.order_by("name").all()
        event_properties = EventProperty.objects.order_by("event", "property").all()

        assert event_definitions.count() == 1
        assert property_definitions.count() == 3
        assert event_properties.count() == 2

        assert event_definitions[0].name == "element_discovered"
        assert event_definitions[0].query_usage_30_day == 1

        assert property_definitions[0].name == "atomic_number"
        assert property_definitions[0].query_usage_30_day == 1
        assert property_definitions[0].is_numerical is True

        assert property_definitions[1].name == "surname"
        assert property_definitions[1].query_usage_30_day == 0
        assert property_definitions[1].is_numerical is False

        assert property_definitions[2].name == "symbol"
        assert property_definitions[2].query_usage_30_day == 0
        assert property_definitions[2].is_numerical is False

        assert event_properties[0].event == "element_discovered"
        assert event_properties[0].property == "atomic_number"

        assert event_properties[1].event == "element_discovered"
        assert event_properties[1].property == "symbol"
