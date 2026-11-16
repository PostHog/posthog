from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events,
    materialized,
)

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.escape import substitute_params
from posthog.models import PropertyDefinition
from posthog.models.instance_setting import override_instance_config

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.event_definitions.backend.models.property_definition import PropertyType

STAR_EVENTS = "(SELECT * FROM events)"
EMAIL_MAP = "map('email', JSONExtractRaw(events.properties, 'email'))"


def _modifiers(pruning: bool) -> HogQLQueryModifiers:
    return HogQLQueryModifiers(optimizeProjections=pruning)


class TestExportedProperties(BaseTest):
    maxDiff = None

    def _print(
        self,
        select: str,
        *,
        native: bool = False,
        pruning: bool = True,
        restricted: set[RestrictedProperty] | None = None,
        dialect: HogQLDialect = "clickhouse",
    ) -> str:
        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=_modifiers(pruning),
            use_new_events_schema=native,
        )
        if restricted is not None:
            context.restricted_properties = restricted
        query, _ = prepare_and_print_ast(parse_select(select), context, dialect)
        return substitute_params(query, context.values).replace(f"team_id, {self.team.pk})", "team_id, 420)")

    @parameterized.expand(
        [
            (
                "one_level",
                f"SELECT properties.email FROM {STAR_EVENTS}",
                f"{EMAIL_MAP} AS properties",
                "JSONExtractRaw(properties['email'])",
            ),
            (
                "passed_through_two_levels",
                f"SELECT properties.email FROM (SELECT * FROM {STAR_EVENTS})",
                f"SELECT properties AS properties FROM (SELECT {EMAIL_MAP} AS properties",
                "JSONExtractRaw(properties['email'])",
            ),
            (
                "aliased_passthrough",
                "SELECT p.email FROM (SELECT properties AS p FROM events)",
                f"{EMAIL_MAP} AS p",
                "JSONExtractRaw(p['email'])",
            ),
            (
                "cte",
                f"WITH e AS {STAR_EVENTS} SELECT properties.email FROM e",
                f"WITH e AS (SELECT {EMAIL_MAP} AS properties",
                "JSONExtractRaw(e.properties['email'])",
            ),
            (
                "union_branches",
                "SELECT properties.email FROM (SELECT properties FROM events UNION ALL SELECT properties FROM events)",
                f"{EMAIL_MAP} AS properties FROM events WHERE equals(events.team_id, 420) UNION ALL SELECT {EMAIL_MAP} AS properties",
                "JSONExtractRaw(properties['email'])",
            ),
            (
                "keys_read_at_two_levels",
                f"SELECT properties.email FROM (SELECT * FROM {STAR_EVENTS} WHERE properties.utm_source = 'g')",
                "map('email', JSONExtractRaw(events.properties, 'email'), 'utm_source', JSONExtractRaw(events.properties, 'utm_source')) AS properties",
                "JSONExtractRaw(properties['utm_source'])",
            ),
            (
                "nested_key",
                "SELECT properties.a.b FROM (SELECT properties FROM events)",
                "map('a', JSONExtractRaw(events.properties, 'a')) AS properties",
                "JSONExtractRaw(properties['a'], 'b')",
            ),
            (
                "left_join_on_the_subquery",
                f"SELECT e.properties.email, s.n FROM {STAR_EVENTS} AS e LEFT JOIN (SELECT event AS ev, count() AS n FROM events GROUP BY ev) AS s ON s.ev = e.event",
                f"{EMAIL_MAP} AS properties",
                "JSONExtractRaw(e.properties['email'])",
            ),
            (
                "read_inside_a_lambda",
                "SELECT arrayMap(x -> properties.email, [1]) FROM (SELECT properties FROM events)",
                f"{EMAIL_MAP} AS properties",
                "x -> replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties['email'])",
            ),
            (
                "unread_blob",
                "SELECT count() FROM (SELECT properties FROM events)",
                "accurateCast(map(), 'Map(String, Nullable(String))') AS properties",
                "count()",
            ),
            (
                "eight_chained_ctes",
                f"WITH c1 AS {STAR_EVENTS}, "
                + ", ".join(f"c{n} AS (SELECT * FROM c{n - 1})" for n in range(2, 9))
                + " SELECT properties.email FROM c8",
                f"WITH c1 AS (SELECT {EMAIL_MAP} AS properties",
                "JSONExtractRaw(c8.properties['email'])",
            ),
        ]
    )
    def test_exports_only_the_keys_read(self, _name: str, select: str, exported: str, read: str) -> None:
        printed = self._print(select)
        assert exported in printed, printed
        assert read in printed, printed
        assert "events.properties AS properties" not in printed, printed

    @parameterized.expand(
        [
            ("blob_and_key", "SELECT properties, properties.email FROM (SELECT properties FROM events)"),
            ("json_function_on_the_blob", "SELECT JSONHas(properties, 'x') FROM (SELECT properties FROM events)"),
            ("distinct_inner", "SELECT properties.email FROM (SELECT DISTINCT properties FROM events)"),
            ("inner_order_by_alias", "SELECT p.email FROM (SELECT properties AS p FROM events ORDER BY p)"),
            (
                "union_distinct",
                "SELECT properties.email FROM (SELECT properties FROM events UNION DISTINCT SELECT properties FROM events)",
            ),
            (
                "intersect",
                "SELECT properties.email FROM (SELECT properties FROM events INTERSECT SELECT properties FROM events)",
            ),
            (
                "distinct_asterisk_between_the_levels",
                "SELECT properties.email FROM (SELECT DISTINCT * FROM (SELECT properties FROM events))",
            ),
            (
                "union_branch_that_cannot_narrow",
                "SELECT properties.email FROM (SELECT properties FROM (SELECT properties FROM events) UNION ALL SELECT DISTINCT properties FROM events)",
            ),
            (
                "positional_order_by_on_a_passthrough",
                "SELECT properties.email FROM (SELECT properties, event FROM (SELECT properties, event FROM events) ORDER BY 1 LIMIT 1)",
            ),
            (
                "positional_order_by_at_the_events_level",
                "SELECT p.email FROM (SELECT properties AS p, event FROM events ORDER BY 1 LIMIT 1)",
            ),
            (
                "second_alias_of_the_column_feeds_a_blob_branch",
                "SELECT x.a.email, x.e FROM (SELECT a, b.email AS e FROM (SELECT properties AS a, properties AS b FROM (SELECT properties FROM events)) "
                "UNION ALL SELECT DISTINCT properties AS a, '' AS e FROM events) AS x",
            ),
            (
                "union_branch_column_matched_by_name_at_another_position",
                "SELECT a.email FROM (SELECT properties AS a, properties AS b FROM events UNION ALL SELECT properties AS b, properties AS a FROM events)",
            ),
            ("query_output", "SELECT properties FROM (SELECT properties FROM events)"),
            ("read_by_position", f"SELECT properties.arr[1] FROM {STAR_EVENTS}"),
            ("native_flag_map", "SELECT properties.$feature_flags FROM (SELECT properties FROM events)", True),
        ]
    )
    def test_keeps_the_blob_when_a_reader_needs_it(self, _name: str, select: str, native: bool = False) -> None:
        printed = self._print(select, native=native)
        assert "map(" not in printed, printed

    def test_saved_view_exports_only_the_keys_read(self) -> None:
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="pageviews",
            query={"query": "SELECT event, properties FROM events WHERE event = '$pageview'"},
            columns={
                "event": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "properties": {"clickhouse": "String", "hogql": "StringJSONDatabaseField"},
            },
        )
        printed = self._print("SELECT properties.email FROM pageviews")
        assert f"{EMAIL_MAP} AS properties" in printed, printed
        assert "JSONExtractRaw(pageviews.properties['email'])" in printed, printed

    @parameterized.expand([("legacy", False), ("native", True)])
    def test_global_kill_switch_overrides_query_modifier(self, _name: str, native: bool) -> None:
        select = f"SELECT properties.email FROM {STAR_EVENTS}"
        unoptimized = self._print(select, native=native, pruning=False)
        with override_instance_config("HOGQL_PROJECTION_OPTIMIZATION_ENABLED", False):
            assert self._print(select, native=native) == unoptimized
        with override_instance_config("HOGQL_PROJECTION_OPTIMIZATION_ENABLED", True):
            optimized = self._print(select, native=native)
            assert "map('email', " in optimized, optimized
            assert "events.distinct_id AS distinct_id" not in optimized, optimized
            assert self._print(select, native=native, pruning=False) == unoptimized

    @parameterized.expand([("legacy", False), ("native", True)])
    def test_narrowing_kill_switch_keeps_the_blob_and_the_pruning(self, _name: str, native: bool) -> None:
        select = f"SELECT properties.email FROM {STAR_EVENTS}"
        with override_instance_config("HOGQL_PROPERTIES_NARROWING_ENABLED", False):
            printed = self._print(select, native=native)
        assert "map('email', " not in printed, printed
        assert "events.distinct_id AS distinct_id" not in printed, printed
        with override_instance_config("HOGQL_PROPERTIES_NARROWING_ENABLED", True):
            assert "map('email', " in self._print(select, native=native)

    def test_native_export_reads_one_subcolumn(self) -> None:
        printed = self._print(f"SELECT properties.utm_source FROM {STAR_EVENTS}", native=True)
        assert "map('utm_source', " in printed, printed
        assert "toJSONString(events.properties.utm_source)" in printed, printed
        assert "JSONExtractKeysAndValuesRaw" not in printed, printed

    @parameterized.expand(
        [
            ("legacy_key", False, "email", "properties.email", True),
            ("legacy_nested", False, "obj.secret", "properties.obj.visible", True),
            ("native_key", True, "email", "properties.email", False),
            ("native_nested", True, "obj.secret", "properties.obj.visible", False),
        ]
    )
    def test_restricted_path_reads_the_masked_blob(
        self, _name: str, native: bool, restricted: str, read: str, narrowed: bool
    ) -> None:
        printed = self._print(
            f"SELECT {read}, properties.utm_source FROM {STAR_EVENTS}",
            native=native,
            restricted={RestrictedProperty(name=restricted, property_type=PropertyDefinition.Type.EVENT)},
        )
        first_key = read.split(".")[1]
        assert ("map(" in printed) is narrowed, printed
        assert "JSONDropKeysPool(" in printed, printed
        assert f"JSONExtractRaw(events.properties, '{first_key}')" not in printed, printed

    def test_string_parser_still_gets_the_text(self) -> None:
        PropertyDefinition.objects.create(
            team=self.team, name="amount", property_type=PropertyType.Numeric, type=PropertyDefinition.Type.EVENT
        )
        printed = self._print(f"SELECT sum(toFloatOrZero(properties.amount)) FROM {STAR_EVENTS}")
        assert "toFloat64OrZero(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties['amount'])" in printed, printed
        assert "'Float64'" not in printed, printed

    def test_hogql_dialect_keeps_the_blob(self) -> None:
        printed = self._print(f"SELECT properties.email FROM {STAR_EVENTS}", dialect="hogql")
        assert "map(" not in printed, printed


class TestExportedPropertiesExecution(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PropertyDefinition.objects.create(
            team=self.team, name="amount", property_type=PropertyType.Numeric, type=PropertyDefinition.Type.EVENT
        )
        rows = [
            ("2024-01-02T10:00:00", "$pageview", {"utm_source": "google", "amount": 2, "email": "a@example.com"}),
            ("2024-01-02T11:00:00", "$pageview", {"utm_source": "", "amount": "7.5", "email": None}),
            ("2024-01-03T10:00:00", "$pageview", {"amount": None, "nested": {"a": {"b": "deep"}}}),
            ("2024-01-03T11:00:00", "signup", {"utm_source": "bing", "n": 1.50, "t": True}),
            ("2024-01-03T12:00:00", "signup", {"utm_source": 'say "hi"\\now', "email": "b@example.com"}),
            (
                "2024-01-03T13:00:00",
                "signup",
                {"$feature/test": "true", "$feature_flags": {"test": "true"}, "$active_feature_flags": ["test"]},
            ),
            ("2023-12-31T23:59:59", "$pageview", {"utm_source": "google", "amount": 100, "a.b": "dotted"}),
            ("2024-01-04T10:00:00", "$pageview", {}),
        ]
        for index, (timestamp, event, properties) in enumerate(rows):
            _create_event(
                team=self.team, event=event, distinct_id=f"u{index}", timestamp=timestamp, properties=properties
            )
        flush_persons_and_events()

    def _assert_same_rows(self, select: str) -> None:
        narrowed = execute_hogql_query(select, team=self.team, modifiers=_modifiers(True)).results
        plain = execute_hogql_query(select, team=self.team, modifiers=_modifiers(False)).results
        assert narrowed == plain, f"narrowed={narrowed} plain={plain}"
        assert narrowed, "the query must match some rows for the comparison to mean anything"

    @parameterized.expand(
        [
            (
                "keys_and_filter",
                f"SELECT properties.email, event FROM {STAR_EVENTS} WHERE properties.utm_source = 'google' ORDER BY 1, 2",
            ),
            (
                "counts_and_key_reads",
                f"SELECT count(), countIf(coalesce(properties.utm_source, '') != ''), uniq(person_id) FROM {STAR_EVENTS} "
                "WHERE event = '$pageview' AND timestamp >= '2024-01-01'",
            ),
            (
                "grouped_key_read",
                f"SELECT properties.utm_source AS src, count() FROM {STAR_EVENTS} WHERE timestamp >= '2024-01-01' GROUP BY src ORDER BY src",
            ),
            (
                "string_parser_on_numeric_property",
                f"SELECT sum(toFloatOrZero(properties.amount)), arraySort(groupArray(properties.amount)) FROM {STAR_EVENTS} WHERE event = '$pageview'",
            ),
            (
                "escaped_string_value",
                f"SELECT properties.utm_source FROM {STAR_EVENTS} WHERE event = 'signup' ORDER BY 1",
            ),
            (
                "empty_null_number_and_bool_values",
                f"SELECT properties.utm_source, properties.email, properties.n, properties.t FROM {STAR_EVENTS} ORDER BY 1, 2, 3, 4",
            ),
            (
                "nested_and_dotted_keys",
                f"SELECT properties.nested.a.b, properties.`a.b` FROM {STAR_EVENTS} WHERE event = '$pageview' ORDER BY 1, 2",
            ),
            (
                "passed_through_two_levels",
                f"SELECT properties.email FROM (SELECT * FROM {STAR_EVENTS} WHERE properties.utm_source = 'google') ORDER BY 1",
            ),
            (
                "aliased_passthrough",
                "SELECT p.email FROM (SELECT properties AS p FROM events) ORDER BY 1",
            ),
            (
                "cte",
                f"WITH e AS {STAR_EVENTS} SELECT properties.email FROM e ORDER BY 1",
            ),
            (
                "union_branches",
                "SELECT properties.email FROM (SELECT properties FROM events UNION ALL SELECT properties FROM events) ORDER BY 1",
            ),
            (
                "left_join_on_the_subquery",
                f"SELECT e.properties.email, s.n FROM {STAR_EVENTS} AS e LEFT JOIN (SELECT event AS ev, count() AS n FROM events GROUP BY ev) AS s ON s.ev = e.event ORDER BY 1, 2",
            ),
            (
                "unread_blob",
                "SELECT count() FROM (SELECT properties FROM events)",
            ),
            (
                "rebuilt_flag_reads",
                f"SELECT properties.`$feature/test`, properties.$active_feature_flags FROM {STAR_EVENTS} WHERE event = 'signup' ORDER BY 1, 2",
            ),
            (
                "flag_map_read",
                f"SELECT count() FROM {STAR_EVENTS} WHERE properties.$feature_flags IS NULL",
            ),
            (
                "enclosing_query_over_the_narrowed_one",
                f"SELECT src, count() FROM (SELECT properties.utm_source AS src FROM {STAR_EVENTS} WHERE event = '$pageview') "
                "WHERE src != '' GROUP BY src ORDER BY src",
            ),
            (
                "filled_rows_read_as_missing",
                "SELECT d, event, properties.email FROM (SELECT toDate(timestamp) AS d, event, properties FROM events ORDER BY d WITH FILL) "
                "WHERE event = '$pageview' ORDER BY d, event, 3",
            ),
        ]
    )
    def test_narrowing_returns_the_same_rows(self, _name: str, select: str) -> None:
        self._assert_same_rows(select)

    @parameterized.expand(
        [
            (
                "string_empty_value",
                "utm_source",
                False,
                None,
                f"SELECT count() FROM {STAR_EVENTS} WHERE properties.utm_source = ''",
            ),
            (
                "nullable_string_escapes",
                "utm_source",
                True,
                None,
                f"SELECT properties.utm_source FROM {STAR_EVENTS} WHERE event = 'signup' ORDER BY 1",
            ),
            (
                "float_under_a_string_parser",
                "amount",
                False,
                "Float64",
                f"SELECT sum(toFloatOrZero(properties.amount)), arraySort(groupArray(properties.amount)) FROM {STAR_EVENTS} WHERE event = '$pageview'",
            ),
        ]
    )
    def test_narrowing_ignores_a_materialized_column(
        self, _name: str, property_name: str, is_nullable: bool, column_type: str | None, select: str
    ) -> None:
        with materialized("events", property_name, is_nullable=is_nullable, column_type=column_type):
            self._assert_same_rows(select)
