from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    flush_persons_and_events,
    materialized,
)
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.property_access_types import RestrictedProperty
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.transforms.events_subquery_pushdown import EventsSubqueryPushdownTransform

from posthog.clickhouse.client.escape import substitute_params
from posthog.models import PropertyDefinition

from products.event_definitions.backend.models.property_definition import PropertyType

STAR_EVENTS = "(SELECT * FROM events)"


def _alias_chain(levels: int) -> str:
    aliases = ["event AS a0", *(f"concat(a{level - 1}, a{level - 1}) AS a{level}" for level in range(1, levels + 1))]
    return f"SELECT {', '.join(aliases)} FROM (SELECT event FROM events) WHERE a{levels} = 'x'"


def _modifiers(on: bool) -> HogQLQueryModifiers:
    return HogQLQueryModifiers(pushDownIntoEventsSubqueries=on, optimizeProjections=True)


class TestEventsSubqueryPushdown(BaseTest):
    maxDiff = None

    def _print(
        self, select: str, *, on: bool = True, native: bool = False, restricted: set[RestrictedProperty] | None = None
    ) -> str:
        context = HogQLContext(
            team_id=self.team.pk, enable_select_queries=True, modifiers=_modifiers(on), use_new_events_schema=native
        )
        if restricted is not None:
            context.restricted_properties = restricted
        query, _ = prepare_and_print_ast(parse_select(select), context, "clickhouse")
        return pretty_print_in_tests(substitute_params(query, context.values), self.team.pk)

    @parameterized.expand(
        [
            (
                "plain_columns",
                f"SELECT count() FROM {STAR_EVENTS} WHERE event = 'x' AND timestamp >= '2024-01-01'",
                "SELECT count() FROM (SELECT * FROM events WHERE event = 'x' AND timestamp >= '2024-01-01')",
            ),
            (
                "appends_to_inner_where",
                f"SELECT count() FROM (SELECT * FROM events WHERE distinct_id != '') WHERE event = 'x'",
                "SELECT count() FROM (SELECT * FROM events WHERE distinct_id != '' AND event = 'x')",
            ),
            (
                "property_predicate",
                f"SELECT count() FROM {STAR_EVENTS} WHERE properties.utm_campaign = 'c'",
                "SELECT count() FROM (SELECT * FROM events WHERE properties.utm_campaign = 'c')",
            ),
            (
                "select_alias_inlined",
                f"SELECT toString(event) AS ev FROM {STAR_EVENTS} WHERE ev = 'x'",
                "SELECT toString(event) AS ev FROM (SELECT * FROM events WHERE toString(event) = 'x')",
            ),
            (
                "nested_select_keeps_its_own_alias",
                f"SELECT event AS x FROM {STAR_EVENTS} WHERE distinct_id IN (SELECT distinct_id AS x FROM events WHERE x = 'u')",
                "SELECT event AS x FROM (SELECT * FROM events WHERE distinct_id IN (SELECT distinct_id AS x FROM events WHERE x = 'u'))",
            ),
            (
                "scalar_subquery_moves_with_the_conjunct",
                f"SELECT count() FROM {STAR_EVENTS} WHERE timestamp >= (SELECT min(timestamp) FROM events WHERE event = 'signup')",
                "SELECT count() FROM (SELECT * FROM events WHERE timestamp >= (SELECT min(timestamp) FROM events WHERE event = 'signup'))",
            ),
        ]
    )
    def test_pushes_outer_conjuncts_into_the_events_subquery(self, _name: str, outer: str, hand_pushed: str) -> None:
        assert self._print(outer) == self._print(hand_pushed)

    def test_disabled_keeps_the_outer_where(self) -> None:
        printed = self._print(f"SELECT count() FROM {STAR_EVENTS} WHERE event = 'x'", on=False)
        assert "equals(event, " in printed, printed
        assert "equals(events.event, " not in printed, printed

    @parameterized.expand(
        [
            ("inner_limit", "SELECT count() FROM (SELECT * FROM events LIMIT 10) WHERE event = 'x'"),
            ("inner_aggregate", "SELECT c FROM (SELECT count() AS c, event FROM events) WHERE event = 'x'"),
            ("inner_distinct", "SELECT count() FROM (SELECT DISTINCT event FROM events) WHERE event = 'x'"),
            (
                "inner_group_by",
                "SELECT count() FROM (SELECT event, count() FROM events GROUP BY event) WHERE event = 'x'",
            ),
            (
                "inner_union",
                "SELECT count() FROM (SELECT event FROM events UNION ALL SELECT event FROM events) WHERE event = 'x'",
            ),
            (
                "outer_right_join",
                f"SELECT e.event FROM {STAR_EVENTS} AS e RIGHT JOIN (SELECT event AS ev FROM events) AS s ON s.ev = e.event WHERE e.event = 'x'",
            ),
            (
                "expression_column",
                f"SELECT count() FROM {STAR_EVENTS} WHERE person_id = '00000000-0000-0000-0000-000000000001'",
            ),
            (
                "or_over_expression_column",
                f"SELECT count() FROM {STAR_EVENTS} WHERE event = 'x' OR person_id = '00000000-0000-0000-0000-000000000001'",
            ),
            (
                "array_join_behind_alias",
                "SELECT arrayJoin([event, 'x']) AS ev FROM (SELECT event FROM events) WHERE ev = 'x'",
            ),
            (
                "inner_stream_function",
                "SELECT event, n FROM (SELECT event, rowNumberInAllBlocks() AS n FROM events) WHERE event = 'y'",
            ),
            (
                "outer_stream_function",
                "SELECT rowNumberInAllBlocks() AS n FROM (SELECT event FROM events) WHERE event = 'y' AND rowNumberInAllBlocks() = 1",
            ),
            ("native_flag_map_read", f"SELECT properties.$feature_flags FROM {STAR_EVENTS}", True),
            (
                "inner_with_fill",
                "SELECT count() FROM (SELECT event, toDate(timestamp) AS d FROM events ORDER BY d WITH FILL) WHERE event = 'x'",
            ),
            ("alias_chain_over_budget", _alias_chain(12)),
        ]
    )
    def test_declines_when_the_rewrite_would_change_rows(self, _name: str, select: str, native: bool = False) -> None:
        assert self._print(select, native=native) == self._print(select, on=False, native=native)

    def test_mixed_where_moves_only_the_events_conjuncts(self) -> None:
        printed = self._print(
            f"SELECT count() FROM {STAR_EVENTS} WHERE event = 'x' AND person_id = '00000000-0000-0000-0000-000000000001'"
        )
        assert "equals(events.event, " in printed, printed
        assert "equals(person_id, " in printed, printed

    def test_hoists_key_reads_and_leaves_the_whole_blob_alone(self) -> None:
        printed = self._print(
            f"SELECT properties, properties.utm_source, properties.a.b FROM {STAR_EVENTS} ORDER BY properties.utm_source"
        )
        assert "JSONExtractRaw(properties," not in printed, printed
        assert (
            "SELECT properties AS properties, properties__utm_source AS utm_source, properties__a__b AS a__b" in printed
        ), printed
        assert " AS properties__utm_source" in printed and " AS properties__a__b" in printed, printed
        assert "ORDER BY properties__utm_source ASC" in printed, printed

    def test_native_hoisted_read_keeps_the_document_text(self) -> None:
        printed = self._print(f"SELECT properties.utm_source FROM {STAR_EVENTS}", native=True)
        assert "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(" in printed, printed
        assert "toString(events.properties.utm_source)" not in printed, printed
        assert "JSONExtractKeysAndValuesRaw" not in printed, printed

    def test_hoisted_read_keeps_the_string_value_under_a_string_parser(self) -> None:
        PropertyDefinition.objects.create(
            team=self.team, name="amount", property_type=PropertyType.Numeric, type=PropertyDefinition.Type.EVENT
        )
        printed = self._print(f"SELECT sum(toFloatOrZero(properties.amount)) FROM {STAR_EVENTS}")
        assert "toFloat64OrZero(properties__amount)" in printed, printed
        assert "'Float64'" not in printed, printed

    def test_hoisted_name_avoids_the_outer_columns(self) -> None:
        printed = self._print(f"SELECT concat(properties.utm_source, '!') AS properties__utm_source FROM {STAR_EVENTS}")
        assert "AS __hoisted_properties_0" in printed, printed
        assert printed.count(" AS properties__utm_source") == 1, printed

    @parameterized.expand([("legacy", False), ("native", True)])
    def test_hoisted_restricted_key_stays_masked(self, _name: str, native: bool) -> None:
        printed = self._print(
            f"SELECT properties.email, properties.utm_source FROM {STAR_EVENTS}",
            native=native,
            restricted={RestrictedProperty(name="email", property_type=PropertyDefinition.Type.EVENT)},
        )
        assert " AS properties__email" in printed, printed
        assert "properties.email" not in printed, printed
        assert "properties, 'email'" not in printed, printed

    def test_unexpected_internal_error_leaves_the_query_untouched(self) -> None:
        select = f"SELECT count() FROM {STAR_EVENTS} WHERE event = 'x'"
        with patch.object(EventsSubqueryPushdownTransform, "_rewrite", side_effect=RuntimeError("boom")):
            guarded = self._print(select)
        assert guarded == self._print(select, on=False)


class TestEventsSubqueryPushdownExecution(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PropertyDefinition.objects.create(
            team=self.team, name="amount", property_type=PropertyType.Numeric, type=PropertyDefinition.Type.EVENT
        )
        rows = [
            ("2024-01-02T10:00:00", "$pageview", {"utm_source": "google", "amount": 2}),
            ("2024-01-02T11:00:00", "$pageview", {"utm_source": "", "amount": "7.5"}),
            ("2024-01-03T10:00:00", "$pageview", {"amount": None}),
            ("2024-01-03T11:00:00", "signup", {"utm_source": "bing"}),
            ("2024-01-03T12:00:00", "signup", {"utm_source": 'say "hi"\\now'}),
            (
                "2024-01-03T13:00:00",
                "signup",
                {"$feature/test": "true", "$feature_flags": {"test": "true"}, "$active_feature_flags": ["test"]},
            ),
            ("2023-12-31T23:59:59", "$pageview", {"utm_source": "google", "amount": 100}),
        ]
        for index, (timestamp, event, properties) in enumerate(rows):
            _create_event(
                team=self.team, event=event, distinct_id=f"u{index}", timestamp=timestamp, properties=properties
            )
        flush_persons_and_events()

    def _assert_same_rows(self, select: str) -> None:
        on = execute_hogql_query(select, team=self.team, modifiers=_modifiers(True)).results
        off = execute_hogql_query(select, team=self.team, modifiers=_modifiers(False)).results
        assert on == off, f"on={on} off={off}"
        assert on, "the query must match some rows for the comparison to mean anything"

    @parameterized.expand(
        [
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
                "property_filter",
                f"SELECT count() FROM {STAR_EVENTS} WHERE properties.utm_source = 'google'",
            ),
            (
                "flag_map_read",
                f"SELECT count() FROM {STAR_EVENTS} WHERE properties.$feature_flags IS NULL",
            ),
            (
                "rebuilt_flag_reads",
                f"SELECT properties.`$feature/test`, properties.$active_feature_flags FROM {STAR_EVENTS} WHERE event = 'signup' ORDER BY 1, 2",
            ),
            (
                "colliding_alias_name",
                f"SELECT concat(coalesce(properties.utm_source, '-'), '!') AS properties__utm_source FROM {STAR_EVENTS} ORDER BY 1",
            ),
            (
                "residual_conjunct_and_left_join",
                f"SELECT e.event, s.n FROM {STAR_EVENTS} AS e LEFT JOIN (SELECT event AS ev, count() AS n FROM events GROUP BY ev) AS s ON s.ev = e.event "
                "WHERE e.timestamp >= '2024-01-01' AND s.n > 1 ORDER BY e.event",
            ),
            (
                "inner_with_fill",
                "SELECT d, event FROM (SELECT toDate(timestamp) AS d, event FROM events ORDER BY d WITH FILL) "
                "WHERE event = '$pageview' ORDER BY d, event",
            ),
            (
                "enclosing_query_over_the_rewritten_one",
                f"SELECT src, count() FROM (SELECT properties.utm_source AS src FROM {STAR_EVENTS} WHERE event = '$pageview') "
                "WHERE src != '' GROUP BY src ORDER BY src",
            ),
        ]
    )
    def test_rewrite_returns_the_same_rows(self, _name: str, select: str) -> None:
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
    def test_rewrite_ignores_a_materialized_column(
        self, _name: str, property_name: str, is_nullable: bool, column_type: str | None, select: str
    ) -> None:
        with materialized("events", property_name, is_nullable=is_nullable, column_type=column_type):
            self._assert_same_rows(select)
