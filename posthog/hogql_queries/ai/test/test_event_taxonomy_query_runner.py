from django.test import override_settings

from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.schema import EventTaxonomyQuery
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)


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
