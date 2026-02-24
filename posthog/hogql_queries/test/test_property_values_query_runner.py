from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.hogql_queries.property_values_query_runner import (
    CachedPropertyValuesQueryResponse,
    PropertyType,
    PropertyValueItem,
    PropertyValuesQuery,
    PropertyValuesQueryRunner,
)
from posthog.hogql_queries.query_runner import ExecutionMode


class TestPropertyValuesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _run(self, query: PropertyValuesQuery) -> list[PropertyValueItem]:
        runner = PropertyValuesQueryRunner(team=self.team, query=query)
        return runner.calculate().results

    def test_event_property_values_basic(self):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        _create_event(event="$pageview", distinct_id="u2", team=self.team, properties={"browser": "Firefox"})
        _create_event(event="$pageview", distinct_id="u3", team=self.team, properties={"browser": "Chrome"})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        names = {r.name for r in results}
        assert names == {"Chrome", "Firefox"}

    def test_event_property_values_excludes_null(self):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        _create_event(event="$pageview", distinct_id="u2", team=self.team, properties={})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        assert len(results) == 1
        assert results[0].name == "Chrome"

    @parameterized.expand(
        [
            ("no_filter", None, {"Chrome", "Firefox", "Safari"}),
            ("matching_filter", "Chr", {"Chrome"}),
            ("non_matching_filter", "Edge", set()),
        ]
    )
    def test_event_property_values_search(self, _name, search_value, expected_names):
        for browser in ["Chrome", "Firefox", "Safari"]:
            _create_event(
                event="$pageview", distinct_id=f"u_{browser}", team=self.team, properties={"browser": browser}
            )
        flush_persons_and_events()

        results = self._run(
            PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser", search_value=search_value)
        )
        assert {r.name for r in results} == expected_names

    @parameterized.expand(
        [
            ("single_event", ["$pageview"], {"Chrome"}),
            ("multiple_events", ["$pageview", "$click"], {"Chrome", "Firefox"}),
        ]
    )
    def test_event_property_values_filtered_by_event_name(self, _name, event_names, expected_names):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        _create_event(event="$click", distinct_id="u1", team=self.team, properties={"browser": "Firefox"})
        _create_event(event="$identify", distinct_id="u1", team=self.team, properties={"browser": "Safari"})
        flush_persons_and_events()

        results = self._run(
            PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser", event_names=event_names)
        )
        assert {r.name for r in results} == expected_names

    def test_event_property_values_is_column(self):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={})
        _create_event(event="$click", distinct_id="u2", team=self.team, properties={})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="event", is_column=True))
        assert {r.name for r in results} == {"$pageview", "$click"}

    def test_event_property_count_is_absent(self):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        assert results[0].count is None

    def test_person_property_values_basic(self):
        _create_person(distinct_ids=["u1"], team=self.team, properties={"country": "US"})
        _create_person(distinct_ids=["u2"], team=self.team, properties={"country": "UK"})
        _create_person(distinct_ids=["u3"], team=self.team, properties={"country": "US"})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.PERSON, property_key="country"))
        names = {r.name for r in results}
        assert names == {"US", "UK"}

    def test_person_property_values_excludes_empty(self):
        _create_person(distinct_ids=["u1"], team=self.team, properties={"country": "US"})
        _create_person(distinct_ids=["u2"], team=self.team, properties={"country": ""})
        _create_person(distinct_ids=["u3"], team=self.team, properties={})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.PERSON, property_key="country"))
        assert len(results) == 1
        assert results[0].name == "US"

    def test_person_property_values_includes_count(self):
        _create_person(distinct_ids=["u1"], team=self.team, properties={"country": "US"})
        _create_person(distinct_ids=["u2"], team=self.team, properties={"country": "US"})
        _create_person(distinct_ids=["u3"], team=self.team, properties={"country": "UK"})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.PERSON, property_key="country"))
        by_name = {r.name: r.count for r in results}
        assert by_name["US"] == 2
        assert by_name["UK"] == 1

    @parameterized.expand(
        [
            ("no_filter", None, {"US", "UK", "DE"}),
            ("matching_filter", "U", {"US", "UK"}),
            ("non_matching_filter", "FR", set()),
        ]
    )
    def test_person_property_values_search(self, _name, search_value, expected_names):
        for country in ["US", "UK", "DE"]:
            _create_person(distinct_ids=[f"u_{country}"], team=self.team, properties={"country": country})
        flush_persons_and_events()

        results = self._run(
            PropertyValuesQuery(property_type=PropertyType.PERSON, property_key="country", search_value=search_value)
        )
        assert {r.name for r in results} == expected_names

    def test_result_is_cached_on_second_call(self):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        flush_persons_and_events()

        runner = PropertyValuesQueryRunner(
            team=self.team,
            query=PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"),
        )
        first = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        assert isinstance(first, CachedPropertyValuesQueryResponse)
        second = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)
        assert isinstance(second, CachedPropertyValuesQueryResponse)
        assert second.is_cached is True
        assert [r.name for r in second.results] == [r.name for r in first.results]
