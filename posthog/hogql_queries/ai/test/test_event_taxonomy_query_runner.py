from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from django.test import override_settings
from django.utils import timezone

from posthog.schema import CachedEventTaxonomyQueryResponse, EventTaxonomyQuery

from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.models import Action, PropertyDefinition
from posthog.models.property_definition import PropertyType


@override_settings(IN_UNIT_TESTING=True)
class TestEventTaxonomyQueryRunner(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_event_taxonomy_query_runner(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Safari", "$country": "UK"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Firefox", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Mobile Safari", "$country": "UK"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Netscape", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Mobile Chrome", "$country": "UK"},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1")).calculate()
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.results[0].property, "$browser")
        self.assertEqual(
            response.results[0].sample_values,
            [
                "Mobile Chrome",
                "Netscape",
                "Mobile Safari",
                "Firefox",
                "Safari",
            ],
        )
        self.assertEqual(response.results[0].sample_count, 6)
        self.assertEqual(response.results[1].property, "$country")
        self.assertEqual(response.results[1].sample_values, ["UK", "US"])
        self.assertEqual(response.results[1].sample_count, 2)

    def test_event_taxonomy_query_filters_by_event(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "UK"},
            team=self.team,
        )
        _create_event(
            event="event2",
            distinct_id="person1",
            properties={"$browser": "Safari", "$country": "UK"},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1")).calculate()
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.results[0].property, "$country")
        self.assertEqual(response.results[0].sample_values, ["UK", "US"])
        self.assertEqual(response.results[0].sample_count, 2)
        self.assertEqual(response.results[1].property, "$browser")
        self.assertEqual(response.results[1].sample_values, ["Chrome"])
        self.assertEqual(response.results[1].sample_count, 1)

    def test_event_taxonomy_query_excludes_properties(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser__name": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$set": "data", "$set_once": "data"},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1")).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].property, "$country")
        self.assertEqual(response.results[0].sample_values, ["US"])
        self.assertEqual(response.results[0].sample_count, 1)

    def test_event_taxonomy_includes_properties_from_multiple_persons(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person2"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person2",
            properties={"$browser": "Chrome", "$screen": "1024x768"},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1")).calculate()
        results = sorted(response.results, key=lambda x: x.property)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].property, "$browser")
        self.assertEqual(results[0].sample_values, ["Chrome"])
        self.assertEqual(results[0].sample_count, 1)
        self.assertEqual(results[1].property, "$country")
        self.assertEqual(results[1].sample_values, ["US"])
        self.assertEqual(results[1].sample_count, 1)
        self.assertEqual(results[2].property, "$screen")
        self.assertEqual(results[2].sample_values, ["1024x768"])
        self.assertEqual(results[2].sample_count, 1)

    def test_caching(self):
        now = timezone.now()

        with freeze_time(now):
            _create_person(
                distinct_ids=["person1"],
                properties={"email": "person1@example.com"},
                team=self.team,
            )
            _create_event(
                event="event1",
                distinct_id="person1",
                team=self.team,
            )

            runner = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1"))
            response = runner.run()

            assert isinstance(response, CachedEventTaxonomyQueryResponse)
            self.assertEqual(len(response.results), 0)

            key = response.cache_key
            _create_event(
                event="event1",
                distinct_id="person1",
                properties={"$browser": "Chrome"},
                team=self.team,
            )
            flush_persons_and_events()

            runner = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1"))
            response = runner.run()

            assert isinstance(response, CachedEventTaxonomyQueryResponse)
            self.assertEqual(response.cache_key, key)
            self.assertEqual(len(response.results), 0)

        with freeze_time(now + timedelta(minutes=59)):
            runner = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1"))
            response = runner.run()

            assert isinstance(response, CachedEventTaxonomyQueryResponse)
            self.assertEqual(len(response.results), 0)

        with freeze_time(now + timedelta(minutes=61)):
            runner = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1"))
            response = runner.run()

            assert isinstance(response, CachedEventTaxonomyQueryResponse)
            self.assertEqual(len(response.results), 1)

    def test_limit(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        for i in range(100):
            _create_event(
                event="event1",
                distinct_id="person1",
                properties={
                    f"prop_{i + 10}": "value",
                    f"prop_{i + 100}": "value",
                    f"prop_{i + 1000}": "value",
                    f"prop_{i + 10000}": "value",
                    f"prop_{i + 100000}": "value",
                    f"prop_{i + 1000000}": "value",
                },
                team=self.team,
            )

        response = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1")).calculate()
        self.assertEqual(len(response.results), 500)

    def test_property_taxonomy_returns_unique_values_for_specified_property(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person2"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$host": "us.posthog.com"},
            team=self.team,
        )

        for _ in range(10):
            _create_event(
                event="event1",
                distinct_id="person1",
                properties={"$host": "posthog.com"},
                team=self.team,
            )

        for _ in range(3):
            _create_event(
                event="event1",
                distinct_id="person2",
                properties={"$host": "eu.posthog.com"},
                team=self.team,
            )

        response = EventTaxonomyQueryRunner(
            team=self.team, query=EventTaxonomyQuery(event="event1", properties=["$host"])
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].property, "$host")
        self.assertEqual(response.results[0].sample_values, ["posthog.com", "eu.posthog.com", "us.posthog.com"])
        self.assertEqual(response.results[0].sample_count, 3)

    def test_property_taxonomy_filters_events_by_event_name(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person2"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$host": "us.posthog.com", "$browser": "Chrome"},
            team=self.team,
        )

        for _ in range(10):
            _create_event(
                event="event2",
                distinct_id="person1",
                properties={"$host": "posthog.com", "prop": 10},
                team=self.team,
            )

        for _ in range(3):
            _create_event(
                event="event1",
                distinct_id="person2",
                team=self.team,
            )

        response = EventTaxonomyQueryRunner(
            team=self.team, query=EventTaxonomyQuery(event="event1", properties=["$host"])
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].property, "$host")
        self.assertEqual(response.results[0].sample_values, ["us.posthog.com"])
        self.assertEqual(response.results[0].sample_count, 1)

    def test_property_taxonomy_handles_multiple_properties_in_query(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_person(
            distinct_ids=["person2"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$host": "us.posthog.com", "$browser": "Chrome"},
            team=self.team,
        )

        for _ in range(5):
            _create_event(
                event="event1",
                distinct_id="person1",
                properties={"$host": "posthog.com", "prop": 10},
                team=self.team,
            )

        for _ in range(3):
            _create_event(
                event="event1",
                distinct_id="person2",
                team=self.team,
            )

        response = EventTaxonomyQueryRunner(
            team=self.team, query=EventTaxonomyQuery(event="event1", properties=["$host", "prop"])
        ).calculate()
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.results[0].property, "prop")
        self.assertEqual(response.results[0].sample_values, ["10"])
        self.assertEqual(response.results[0].sample_count, 1)
        self.assertEqual(response.results[1].property, "$host")
        self.assertEqual(response.results[1].sample_values, ["posthog.com", "us.posthog.com"])
        self.assertEqual(response.results[1].sample_count, 2)

    def test_property_taxonomy_includes_events_with_partial_property_matches(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$host": "us.posthog.com"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person2",
            properties={"prop": 10},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(
            team=self.team, query=EventTaxonomyQuery(event="event1", properties=["$host", "prop"])
        ).calculate()
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.results[0].property, "prop")
        self.assertEqual(response.results[0].sample_values, ["10"])
        self.assertEqual(response.results[0].sample_count, 1)
        self.assertEqual(response.results[1].property, "$host")
        self.assertEqual(response.results[1].sample_values, ["us.posthog.com"])
        self.assertEqual(response.results[1].sample_count, 1)

    def test_query_count(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"prop": "1"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person2",
            properties={"prop": "2"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person2",
            properties={"prop": "3"},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(
            team=self.team, query=EventTaxonomyQuery(event="event1", properties=["prop"], maxPropertyValues=1)
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].property, "prop")
        self.assertEqual(response.results[0].sample_count, 3)
        self.assertEqual(len(response.results[0].sample_values), 1)

    def test_feature_flags_properties_are_omitted(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$feature/ai": "1"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person2",
            properties={"prop": "2"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person2",
            properties={"prop": "3", "$feature/dashboard": "0"},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1")).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].property, "prop")
        self.assertEqual(response.results[0].sample_count, 2)

    @snapshot_clickhouse_queries
    def test_retrieves_action_properties(self):
        action = Action.objects.create(
            team=self.team,
            name="action1",
            steps_json=[{"event": "$pageview"}],
        )
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            properties={"ai": "true"},
            team=self.team,
        )
        _create_event(
            event="$pageview",
            distinct_id="person1",
            properties={"dashboard": "true"},
            team=self.team,
        )
        _create_event(
            event="event",
            distinct_id="person1",
            properties={"prop": "3", "$feature/dashboard": "0"},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(actionId=action.id)).calculate()
        self.assertEqual(len(response.results), 2)
        self.assertListEqual([item.property for item in response.results], ["ai", "dashboard"])

    @snapshot_clickhouse_queries
    def test_property_taxonomy_handles_numeric_property_values(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        # Create numeric property definition
        PropertyDefinition.objects.create(
            project=self.team.project,
            team=self.team,
            name="zero_duration_recording_count_in_period",
            type=PropertyDefinition.Type.EVENT,
            property_type=PropertyType.Numeric,
        )

        # Numeric property value event
        _create_event(
            event="organization usage report",
            distinct_id="person1",
            properties={"organization_id": "org123", "zero_duration_recording_count_in_period": 0},
            team=self.team,
        )
        _create_event(
            event="organization usage report",
            distinct_id="person1",
            properties={"organization_id": "org456", "zero_duration_recording_count_in_period": 10},
            team=self.team,
        )
        _create_event(
            event="organization usage report",
            distinct_id="person1",
            properties={"organization_id": "org789", "zero_duration_recording_count_in_period": 100},
            team=self.team,
        )
        # Empty string value for numeric property event
        _create_event(
            event="organization usage report",
            distinct_id="person1",
            properties={"organization_id": "org000", "zero_duration_recording_count_in_period": ""},
            team=self.team,
        )
        # Missing numeric property event
        _create_event(
            event="organization usage report",
            distinct_id="person1",
            properties={"organization_id": "org999"},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(
            team=self.team,
            query=EventTaxonomyQuery(
                event="organization usage report", properties=["zero_duration_recording_count_in_period"]
            ),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].property, "zero_duration_recording_count_in_period")
        self.assertEqual(response.results[0].sample_count, 3)
        self.assertIn("0", response.results[0].sample_values)
        self.assertIn("10", response.results[0].sample_values)
        self.assertIn("100", response.results[0].sample_values)
        self.assertNotIn('""', response.results[0].sample_values)

    def test_property_taxonomy_handles_empty_string_values(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        # Empty string value for numeric property event
        _create_event(
            event="organization usage report",
            distinct_id="person1",
            properties={"organization_id": "org000", "zero_duration_recording_count_in_period": ""},
            team=self.team,
        )

        response = EventTaxonomyQueryRunner(
            team=self.team,
            query=EventTaxonomyQuery(
                event="organization usage report", properties=["zero_duration_recording_count_in_period"]
            ),
        ).calculate()

        self.assertEqual(len(response.results), 0)
