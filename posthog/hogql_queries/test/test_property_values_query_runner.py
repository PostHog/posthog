from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

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

    def test_event_property_values_is_column_none_behaves_like_false(self):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        flush_persons_and_events()

        results_default = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        results_none = self._run(
            PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser", is_column=None)
        )
        assert [r.name for r in results_default] == [r.name for r in results_none]

    def test_event_property_values_empty_event_names_list_is_ignored(self):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        _create_event(event="$click", distinct_id="u2", team=self.team, properties={"browser": "Firefox"})
        flush_persons_and_events()

        results = self._run(
            PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser", event_names=[])
        )
        assert {r.name for r in results} == {"Chrome", "Firefox"}

    def test_event_property_values_json_array_property_is_flattened(self):
        _create_event(
            event="$pageview",
            distinct_id="u1",
            team=self.team,
            properties={"tags": '["python", "django"]'},
        )
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="tags"))
        assert {r.name for r in results} == {"python", "django"}

    @parameterized.expand(
        [
            ("percent_wildcard", "%", set()),
            ("underscore_wildcard", "Chr_me", set()),
        ]
    )
    def test_event_property_values_search_escapes_ilike_wildcards(self, _name, search_value, expected_names):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        _create_event(event="$pageview", distinct_id="u2", team=self.team, properties={"browser": "Firefox"})
        flush_persons_and_events()

        results = self._run(
            PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser", search_value=search_value)
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

    @parameterized.expand(
        [
            ("normal", ExecutionMode.CALCULATE_BLOCKING_ALWAYS, "force_blocking"),
            ("poll", ExecutionMode.CACHE_ONLY_NEVER_CALCULATE, "force_cache"),
        ]
    )
    def test_execution_mode_recorded_in_query_executed_event(self, _name, execution_mode, expected_value):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        flush_persons_and_events()

        runner = PropertyValuesQueryRunner(
            team=self.team,
            query=PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"),
        )
        # Prime the cache so CACHE_ONLY_NEVER_CALCULATE has something to return
        runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        with patch("posthog.hogql_queries.query_runner.posthoganalytics.capture") as mock_capture:
            runner.run(execution_mode)

        mock_capture.assert_called_once()
        captured_props = mock_capture.call_args.kwargs["properties"]
        assert captured_props["execution_mode"] == expected_value
