from datetime import datetime, timedelta

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.hogql_queries.property_values_query_runner import (
    PROPERTY_VALUES_TABLE_FLAG,
    CachedPropertyValuesQueryResponse,
    PropertyType,
    PropertyValueItem,
    PropertyValuesQuery,
    PropertyValuesQueryRunner,
)
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Organization, Team

from products.access_control.backend.facade.testing import create_access_control
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def variant_filters(*keys: str) -> dict:
    return {
        "groups": [{"rollout_percentage": 100}],
        "multivariate": {"variants": [{"key": key, "rollout_percentage": 100 // len(keys)} for key in keys]},
    }


def string_flag_filters(default_value: str, *rule_values: str) -> dict:
    rules = [
        {"id": f"rule-{value}", "rule_type": "targeted_release", "targeting": {"properties": []}, "value": value}
        for value in rule_values
    ]
    return {"version": 2, "return_type": "string", "default_value": default_value, "rules": rules}


MULTIVARIATE_FILTERS = {
    "groups": [{"rollout_percentage": 100}],
    "multivariate": {
        "variants": [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
    },
}


class TestPropertyValuesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _run(self, query: PropertyValuesQuery) -> list[PropertyValueItem]:
        runner = PropertyValuesQueryRunner(team=self.team, query=query)
        return runner.calculate().results

    def _run_cached(self, query: PropertyValuesQuery) -> list[PropertyValueItem]:
        runner = PropertyValuesQueryRunner(team=self.team, query=query)
        response = runner.run(ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS)
        assert isinstance(response, CachedPropertyValuesQueryResponse)
        return response.results

    def test_event_property_values_basic(self):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        _create_event(event="$pageview", distinct_id="u2", team=self.team, properties={"browser": "Firefox"})
        _create_event(event="$pageview", distinct_id="u3", team=self.team, properties={"browser": "Chrome"})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        names = {r.name for r in results}
        assert names == {"Chrome", "Firefox"}

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_event_property_values_new_schema_uses_json_subcolumn(self):
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "Chrome"})
        flush_persons_and_events()

        runner = PropertyValuesQueryRunner(
            team=self.team,
            query=PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"),
        )
        response = runner.calculate()
        physical_query = execute_hogql_query(runner.to_query(), team=self.team)

        assert {r.name for r in response.results} == {"Chrome"}
        assert physical_query.clickhouse is not None
        assert "events_json" in physical_query.clickhouse
        assert "events.properties.browser" in physical_query.clickhouse
        assert "events.properties.^browser" in physical_query.clickhouse
        assert "JSONExtractRaw" not in physical_query.clickhouse
        assert "toJSONString" in physical_query.clickhouse
        assert "toString(events.properties)" not in physical_query.clickhouse

    @override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True)
    def test_event_property_values_new_schema_includes_object_values(self):
        _create_event(
            event="$pageview",
            distinct_id="u1",
            team=self.team,
            properties={"profile": {"first_name": "Mary", "last_name": "Smith"}},
        )
        _create_event(event="$pageview", distinct_id="u2", team=self.team, properties={"profile": "plain"})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="profile"))

        names: set[str] = set()
        for result in results:
            assert isinstance(result.name, str)
            names.add(result.name.replace(" ", ""))
        assert names == {'{"first_name":"Mary","last_name":"Smith"}', "plain"}

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

    @parameterized.expand(
        [
            ("boolean_flag", {"groups": [{"rollout_percentage": 100}]}, None, ["true", "false"]),
            ("multivariate_flag", MULTIVARIATE_FILTERS, None, ["control", "test", "true", "false"]),
            ("search_is_case_insensitive", MULTIVARIATE_FILTERS, "TES", ["test"]),
            ("variant_named_true", variant_filters("true", "off"), None, ["true", "off", "false"]),
            (
                "holdout",
                {**MULTIVARIATE_FILTERS, "holdout": {"id": 42, "exclusion_percentage": 10}},
                None,
                ["control", "test", "holdout-42", "true", "false"],
            ),
            ("deleted_flag", MULTIVARIATE_FILTERS, None, ["control", "test", "true", "false"], "kept_key"),
            (
                "deleted_flag_with_tombstoned_key",
                MULTIVARIATE_FILTERS,
                None,
                ["control", "test", "true", "false"],
                "tombstoned_key",
            ),
        ]
    )
    def test_feature_flag_property_values_come_from_the_flag(
        self, _name, filters, search_value, expected_names, deletion=None
    ):
        flag = FeatureFlag.objects.create(
            team=self.team, key="beta", created_by=self.user, filters=filters, deleted=deletion is not None
        )
        if deletion == "tombstoned_key":
            flag.key = flag.tombstoned_key()
            flag.save()
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"$feature/beta": "retired"})
        flush_persons_and_events()

        results = self._run(
            PropertyValuesQuery(
                property_type=PropertyType.EVENT, property_key="$feature/beta", search_value=search_value
            )
        )
        assert [r.name for r in results] == expected_names

    @parameterized.expand(
        [
            (
                "variants",
                MULTIVARIATE_FILTERS,
                variant_filters("redesign", "control"),
                variant_filters("fresh", "control"),
                ["control", "false", "fresh", "redesign", "test", "true"],
            ),
            (
                "string_flag",
                string_flag_filters("compact"),
                string_flag_filters("wide", "dense"),
                string_flag_filters("standard"),
                ["compact", "dense", "false", "standard", "true", "wide"],
            ),
            (
                "holdout",
                {**MULTIVARIATE_FILTERS, "holdout": {"id": 42, "exclusion_percentage": 10}},
                MULTIVARIATE_FILTERS,
                MULTIVARIATE_FILTERS,
                ["control", "false", "holdout-42", "test", "true"],
            ),
        ]
    )
    def test_feature_flag_property_values_keep_values_from_earlier_flags_with_the_key(
        self, _name, first_filters, edited_filters, current_filters, expected_names
    ):
        earlier = FeatureFlag.objects.create(team=self.team, key="beta", created_by=self.user, filters=first_filters)
        earlier.filters = edited_filters
        earlier.save()
        earlier.delete()
        FeatureFlag.objects.create(team=self.team, key="beta", created_by=self.user, filters=current_filters)

        results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="$feature/beta"))
        assert sorted(str(r.name) for r in results) == expected_names

    def test_feature_flag_property_values_skip_history_of_flags_hidden_from_any_member(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        hidden = FeatureFlag.objects.create(
            team=self.team, key="beta", created_by=self.user, filters=MULTIVARIATE_FILTERS
        )
        hidden.filters = variant_filters("secret")
        hidden.save()
        hidden.key = "gamma"
        hidden.save()
        FeatureFlag.objects.create(team=self.team, key="beta", created_by=self.user, filters=variant_filters("fresh"))
        query = PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="$feature/beta")
        self._run_cached(query)
        create_access_control(
            team_id=self.team.id, resource="feature_flag", access_level="none", resource_id=str(hidden.id)
        )

        assert [r.name for r in self._run_cached(query)] == ["fresh", "true", "false"]

    def test_feature_flag_property_without_a_flag_in_the_project_uses_events_scan(self):
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"))
        FeatureFlag.objects.create(team=other_team, key="beta", filters=MULTIVARIATE_FILTERS)
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"$feature/beta": "retired"})

        results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="$feature/beta"))
        assert [r.name for r in results] == ["retired"]

    @parameterized.expand(
        [
            ("rule_on_the_flag", "beta", ["retired"]),
            ("rule_on_every_flag", None, ["retired"]),
            ("rule_on_another_flag", "other", ["control", "test", "true", "false"]),
        ]
    )
    def test_feature_flag_access_rule_added_after_caching_decides_the_source(
        self, _name, restricted_key, expected_names
    ):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        flags = {
            key: FeatureFlag.objects.create(team=self.team, key=key, created_by=self.user, filters=MULTIVARIATE_FILTERS)
            for key in ("beta", "other")
        }
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"$feature/beta": "retired"})
        flush_persons_and_events()
        query = PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="$feature/beta")
        self._run_cached(query)
        create_access_control(
            team_id=self.team.id,
            resource="feature_flag",
            access_level="none",
            resource_id=str(flags[restricted_key].id) if restricted_key else None,
        )

        assert [r.name for r in self._run_cached(query)] == expected_names

    def test_restricted_feature_flag_property_is_not_served(self):
        FeatureFlag.objects.create(team=self.team, key="beta", created_by=self.user, filters=MULTIVARIATE_FILTERS)

        with patch(
            "posthog.hogql_queries.property_values_query_runner.get_restricted_property_names",
            return_value={"$feature/beta"},
        ):
            results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="$feature/beta"))
        assert results == []

    @snapshot_clickhouse_queries
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

    @snapshot_clickhouse_queries
    def test_person_property_values_distinct_id_suggestions(self):
        _create_person(distinct_ids=["alice", "alice-alias"], team=self.team, properties={})
        _create_person(distinct_ids=["bob"], team=self.team, properties={})
        _create_person(distinct_ids=["carol"], team=self.team, properties={})
        flush_persons_and_events()

        results = self._run(PropertyValuesQuery(property_type=PropertyType.PERSON, property_key="distinct_id"))
        assert {r.name for r in results} == {"alice", "alice-alias", "bob", "carol"}

    @parameterized.expand(
        [
            ("no_filter", None, {"alice", "bob", "carol"}),
            ("matching_filter", "al", {"alice"}),
            ("non_matching_filter", "zzz", set()),
        ]
    )
    def test_person_property_values_distinct_id_search(self, _name, search_value, expected_names):
        for did in ["alice", "bob", "carol"]:
            _create_person(distinct_ids=[did], team=self.team, properties={})
        flush_persons_and_events()

        results = self._run(
            PropertyValuesQuery(
                property_type=PropertyType.PERSON, property_key="distinct_id", search_value=search_value
            )
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
    def test_execution_mode_recorded_in_slo_started_event(self, _name, execution_mode, expected_value):
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

        mock_capture.assert_called()
        slo_started_calls = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "slo_operation_started"]
        assert len(slo_started_calls) == 1
        captured_props = slo_started_calls[0].kwargs["properties"]
        assert captured_props["execution_mode"] == expected_value


class TestPropertyValuesQueryRunnerAggregatedTable(ClickhouseTestMixin, APIBaseTest):
    def _run(self, query: PropertyValuesQuery) -> list[PropertyValueItem]:
        runner = PropertyValuesQueryRunner(team=self.team, query=query)
        return runner.calculate().results

    def _flag_on(self):
        return patch(
            "posthog.hogql_queries.property_values_query_runner.posthoganalytics.feature_enabled",
            side_effect=lambda flag, *args, **kwargs: flag == PROPERTY_VALUES_TABLE_FLAG,
        )

    def _insert_rows(self, rows: list[tuple]) -> None:
        sync_execute(
            "INSERT INTO property_values (team_id, property_type, property_key, property_value, property_count, last_seen) VALUES",
            rows,
        )

    def test_returns_distinct_values(self):
        now = datetime.now()
        self._insert_rows(
            [
                (self.team.pk, "event", "browser", "Chrome", 3, now),
                (self.team.pk, "event", "browser", "Chrome", 4, now),
                (self.team.pk, "event", "browser", "Firefox", 2, now),
            ]
        )

        with self._flag_on():
            results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        assert {r.name for r in results} == {"Chrome", "Firefox"}
        assert results[0].count is None

    @parameterized.expand(
        [
            ("lowercase_needle", "chr", {"Chrome"}),
            ("uppercase_needle", "FIRE", {"Firefox"}),
            ("non_matching", "edge", set()),
            ("percent_wildcard", "%", set()),
            ("underscore_wildcard", "chr_me", set()),
        ]
    )
    def test_search_is_case_insensitive_and_escapes_wildcards(self, _name, search_value, expected_names):
        now = datetime.now()
        self._insert_rows(
            [
                (self.team.pk, "event", "browser", "Chrome", 3, now),
                (self.team.pk, "event", "browser", "Firefox", 2, now),
            ]
        )

        with self._flag_on():
            results = self._run(
                PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser", search_value=search_value)
            )
        assert {r.name for r in results} == expected_names

    def test_values_not_seen_in_seven_days_are_excluded(self):
        self._insert_rows(
            [
                (self.team.pk, "event", "browser", "Chrome", 3, datetime.now()),
                (self.team.pk, "event", "browser", "Netscape", 100, datetime.now() - timedelta(days=10)),
            ]
        )

        with self._flag_on():
            results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        assert {r.name for r in results} == {"Chrome"}

    def test_other_team_values_are_excluded(self):
        self._insert_rows([(self.team.pk + 999999, "event", "browser", "Chrome", 3, datetime.now())])

        with self._flag_on():
            results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        assert results == []

    def test_person_type_rows_are_excluded(self):
        self._insert_rows(
            [
                (self.team.pk, "event", "browser", "Chrome", 3, datetime.now()),
                (self.team.pk, "person", "browser", "PersonChrome", 3, datetime.now()),
            ]
        )

        with self._flag_on():
            results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        assert {r.name for r in results} == {"Chrome"}

    def test_json_array_value_is_flattened(self):
        self._insert_rows([(self.team.pk, "event", "tags", '["python", "django"]', 3, datetime.now())])

        with self._flag_on():
            results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="tags"))
        assert {r.name for r in results} == {"python", "django"}

    def test_event_scoped_request_is_served_unscoped_from_table(self):
        self._insert_rows([(self.team.pk, "event", "browser", "TableValue", 3, datetime.now())])
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "EventScopedValue"})

        with self._flag_on():
            results = self._run(
                PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser", event_names=["$pageview"])
            )
        assert {r.name for r in results} == {"TableValue"}

    def test_restricted_property_key_is_not_served(self):
        self._insert_rows([(self.team.pk, "event", "browser", "TableOnly", 3, datetime.now())])
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={"browser": "EventOnly"})
        flush_persons_and_events()

        with (
            self._flag_on(),
            patch(
                "posthog.hogql_queries.property_values_query_runner.get_restricted_property_names",
                return_value={"browser"},
            ),
        ):
            results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))

        assert {result.name for result in results} == set()

    def test_is_column_uses_events_scan(self):
        self._insert_rows([(self.team.pk, "event", "event", "TableOnly", 3, datetime.now())])
        _create_event(event="$pageview", distinct_id="u1", team=self.team, properties={})

        with self._flag_on():
            results = self._run(
                PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="event", is_column=True)
            )
        assert {r.name for r in results} == {"$pageview"}

    @parameterized.expand([("virtual_key", "$virt_initial_channel_type"), ("feature_flag_key", "$feature/beta")])
    def test_key_the_table_may_lack_uses_events_scan(self, _name, property_key):
        runner = PropertyValuesQueryRunner(
            team=self.team,
            query=PropertyValuesQuery(property_type=PropertyType.EVENT, property_key=property_key),
        )
        with self._flag_on():
            assert runner._use_property_values_table is False

    def test_flag_off_uses_events_scan(self):
        self._insert_rows([(self.team.pk, "event", "browser", "TableOnly", 3, datetime.now())])

        with patch(
            "posthog.hogql_queries.property_values_query_runner.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            results = self._run(PropertyValuesQuery(property_type=PropertyType.EVENT, property_key="browser"))
        assert results == []
