from typing import Union, List

from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.web_analytics_query_runner import _sample_rate_from_count
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.schema import (
    DateRange,
    WebStatsTableQuery,
    WebStatsBreakdown,
    WebOverviewQuery,
    EventPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    SamplingRate,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestWebStatsTableQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="$pageview"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "test" else {}),
                        },
                    )
                )
            for timestamp, session_id, pathname in timestamps:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={"$session_id": session_id, "$pathname": pathname},
                )
        return person_result

    def _create_web_stats_table_query(self, date_from, date_to, properties, breakdown_by=WebStatsBreakdown.Page):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to), properties=properties, breakdownBy=breakdown_by
        )
        return WebStatsTableQueryRunner(team=self.team, query=query)

    def _create__web_overview_query(self, date_from, date_to, properties):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties,
        )
        return WebOverviewQueryRunner(team=self.team, query=query)

    def test_sample_rate_cache_key_is_same_across_subclasses(self):
        properties: List[Union[EventPropertyFilter, PersonPropertyFilter]] = [
            EventPropertyFilter(key="$current_url", value="/a", operator=PropertyOperator.is_not),
            PersonPropertyFilter(key="$initial_utm_source", value="google", operator=PropertyOperator.is_not),
        ]
        date_from = "2023-12-08"
        date_to = "2023-12-15"

        stats_key = self._create_web_stats_table_query(date_from, date_to, properties)._sample_rate_cache_key()
        overview_key = self._create__web_overview_query(date_from, date_to, properties)._sample_rate_cache_key()

        self.assertEqual(stats_key, overview_key)

    def test_sample_rate_cache_key_is_same_with_different_properties(self):
        properties_a: List[Union[EventPropertyFilter, PersonPropertyFilter]] = [
            EventPropertyFilter(key="$current_url", value="/a", operator=PropertyOperator.is_not),
        ]
        properties_b: List[Union[EventPropertyFilter, PersonPropertyFilter]] = [
            EventPropertyFilter(key="$current_url", value="/b", operator=PropertyOperator.is_not),
        ]
        date_from = "2023-12-08"
        date_to = "2023-12-15"

        key_a = self._create_web_stats_table_query(date_from, date_to, properties_a)._sample_rate_cache_key()
        key_b = self._create_web_stats_table_query(date_from, date_to, properties_b)._sample_rate_cache_key()

        self.assertEqual(key_a, key_b)

    def test_sample_rate_cache_key_changes_with_date_range(self):
        properties: List[Union[EventPropertyFilter, PersonPropertyFilter]] = [
            EventPropertyFilter(key="$current_url", value="/a", operator=PropertyOperator.is_not),
        ]
        date_from_a = "2023-12-08"
        date_from_b = "2023-12-09"
        date_to = "2023-12-15"

        key_a = self._create_web_stats_table_query(date_from_a, date_to, properties)._sample_rate_cache_key()
        key_b = self._create_web_stats_table_query(date_from_b, date_to, properties)._sample_rate_cache_key()

        self.assertNotEquals(key_a, key_b)

    def test_sample_rate_from_count(self):
        self.assertEqual(SamplingRate(numerator=1), _sample_rate_from_count(0))
        self.assertEqual(SamplingRate(numerator=1), _sample_rate_from_count(1_000))
        self.assertEqual(SamplingRate(numerator=1), _sample_rate_from_count(10_000))
        self.assertEqual(SamplingRate(numerator=1, denominator=10), _sample_rate_from_count(100_000))
        self.assertEqual(SamplingRate(numerator=1, denominator=10), _sample_rate_from_count(999_999))
        self.assertEqual(SamplingRate(numerator=1, denominator=100), _sample_rate_from_count(1_000_000))
        self.assertEqual(SamplingRate(numerator=1, denominator=100), _sample_rate_from_count(9_999_999))
        self.assertEqual(SamplingRate(numerator=1, denominator=1000), _sample_rate_from_count(10_000_000))
        self.assertEqual(SamplingRate(numerator=1, denominator=1000), _sample_rate_from_count(99_999_999))
