from django.test import override_settings

from posthog.hogql_queries.ai.event_taxonomy_query_runner import EventTaxonomyQueryRunner
from posthog.schema import EventTaxonomyQuery
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


@override_settings(IN_UNIT_TESTING=True)
class TestEventTaxonomyQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def test_taxonomy_query_runner(self):
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

        results = EventTaxonomyQueryRunner(team=self.team, query=EventTaxonomyQuery(event="event1")).calculate()
        self.assertEqual(len(results.results), 2)
        self.assertEqual(results.results[0].property, "$browser")
        self.assertEqual(
            results.results[0].sample_values,
            [
                "Mobile Chrome",
                "Netscape",
                "Mobile Safari",
                "Firefox",
                "Safari",
            ],
        )
        self.assertEqual(results.results[0].sample_count, 6)
        self.assertEqual(results.results[1].property, "$country")
        self.assertEqual(results.results[1].sample_values, ["UK", "US"])
        self.assertEqual(results.results[1].sample_count, 2)
