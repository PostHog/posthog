import os
import re
import sys
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    _create_person,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, InCohortVia, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import StringDatabaseField
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast, print_prepared_ast
from posthog.hogql.query import HogQLQueryExecutor, execute_hogql_query
from posthog.hogql.transforms import flag_calls_union_preaggregation as preaggregation
from posthog.hogql.transforms.flag_calls_from_flag_evaluations import SyntaxVisitor
from posthog.hogql.transforms.test.test_flag_calls_union import (
    MIXED,
    ONLY,
    READ,
    _enabled_flags,
    _readable_chains,
    _set_mode,
)

from posthog.clickhouse.client import sync_execute
from posthog.models.instance_setting import override_instance_config

from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode

WINDOW = "timestamp >= now() - INTERVAL 120 DAY"
WHERE = f"WHERE {MIXED} AND {WINDOW}"
ON_EVENTS = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
NO_OVERRIDE = PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS
DISABLED = PersonsOnEventsMode.DISABLED
REWRITTEN = re.compile(r"\w+Merge\(__flag_calls_state_\d|GROUP BY\s+__flag_calls_key_\d")
# Aggregation states drop LowCardinality from their argument types.
_WITHOUT_LOW_CARDINALITY = re.compile(r"LowCardinality\(([^()]*)\)")

SCHEMAS = [(READ, False), (ONLY, False), (ONLY, True)]


def _doubling_aliases(depth: int) -> str:
    expr = "event AS a0"
    for n in range(1, depth + 1):
        expr = f"concat(({expr}), a{n - 1}) AS a{n}"
    return f"SELECT sum(length({expr})) AS total"


def _cases(queries: list[tuple[str, str, dict[str, Any]]]) -> list[tuple[str, str, FlagEvaluationsMode, bool, dict]]:
    return [
        (f"{name}_{mode.name.lower()}_{'events_json' if new_schema else 'events'}", query, mode, new_schema, modifiers)
        for name, query, modifiers in queries
        for mode, new_schema in SCHEMAS
    ]


REWRITTEN_QUERIES: list[tuple[str, str, dict[str, Any]]] = [
    (
        "count_by_day",
        f"SELECT toStartOfDay(timestamp) AS day, count() FROM events {WHERE} GROUP BY day ORDER BY day",
        {},
    ),
    (
        "positional_key_having_order",
        f"SELECT properties.$browser, count(), uniq(distinct_id) FROM events {WHERE} "
        "GROUP BY 1 HAVING count() > 0 ORDER BY count() DESC, 1",
        {},
    ),
    (
        "every_aggregate_without_group_by",
        "SELECT count(), sum(toFloat(properties.num)), avg(toFloat(properties.num)), min(timestamp), max(timestamp), "
        "countIf(event = '$feature_flag_called'), sumIf(toFloat(properties.num), distinct_id = 'a'), "
        "uniqIf(distinct_id, event = '$pageview'), count(DISTINCT distinct_id), uniqExact(distinct_id), "
        "avgIf(toFloat(properties.num), distinct_id = 'a'), minIf(timestamp, event = '$pageview'), "
        "maxIf(toFloat(properties.num), event = '$pageview'), uniqExactIf(distinct_id, event = '$pageview'), "
        "uniqIf(distinct_id, event, event = '$pageview'), uniqExact(distinct_id, event) "
        f"FROM events {WHERE}",
        {},
    ),
    (
        "no_rows_without_group_by",
        "SELECT count(), sum(toFloat(properties.num)), avg(toFloat(properties.num)), min(timestamp), "
        "max(toFloat(properties.num)), countIf(event = '$pageview'), sumIf(toFloat(properties.num), 1), "
        "avgIf(toFloat(properties.num), 1), minIf(timestamp, 1), maxIf(toFloat(properties.num), 1), "
        "uniqIf(distinct_id, 1), uniqExactIf(distinct_id, 1) "
        f"FROM events {WHERE} AND distinct_id = 'nobody'",
        {},
    ),
    ("key_inside_expression", f"SELECT lower(event) AS e, count() FROM events {WHERE} GROUP BY event ORDER BY e", {}),
    ("group_by_without_aggregate", f"SELECT distinct_id FROM events {WHERE} GROUP BY distinct_id ORDER BY 1", {}),
    (
        "person_property_on_events",
        f"SELECT person.properties.email AS email, count() FROM events {WHERE} GROUP BY email ORDER BY email",
        {},
    ),
    (
        "inside_a_subquery",
        f"SELECT sum(c) FROM (SELECT distinct_id, count() AS c FROM events {WHERE} GROUP BY distinct_id)",
        {},
    ),
    ("constant_key", f"SELECT 'all' AS k, count() FROM events {WHERE} GROUP BY 'all'", {}),
    (
        "integer_constant_key",
        f"SELECT event, 2 AS two, count(), uniq(distinct_id) FROM events {WHERE} GROUP BY event, two ORDER BY event",
        {},
    ),
    ("boolean_constant_key", f"SELECT true AS t, count() FROM events {WHERE} GROUP BY t", {}),
    ("percent_in_column_name", f"SELECT countIf(event LIKE '%view') FROM events {WHERE}", {}),
    (
        "alias_inside_an_aggregate_read_elsewhere",
        f"SELECT uniq(lower(event) AS lowered), countIf(lowered = '$pageview') FROM events {WHERE}",
        {},
    ),
    # Each row still passes through such a filter once, inside its branch.
    ("random_filter", f"SELECT count() FROM events {WHERE} AND rand() % 1 = 0", {}),
    ("now_in_block_filter", f"SELECT count() FROM events {WHERE} AND timestamp < nowInBlock('UTC')", {}),
    ("person_id_without_override", f"SELECT uniq(person_id) FROM events {WHERE}", {"personsOnEventsMode": NO_OVERRIDE}),
]

DECLINED_QUERIES: list[tuple[str, str, dict[str, Any]]] = [
    ("override_join", f"SELECT uniq(person_id) FROM events {WHERE}", {}),
    (
        "persons_join_with_person_id_pushdown",
        f"SELECT person.properties.email AS email, count() FROM events {WHERE} GROUP BY email ORDER BY email",
        {"personsOnEventsMode": DISABLED, "personIdPushdown": True},
    ),
    (
        "window_function",
        f"SELECT event, count(), row_number() OVER (ORDER BY event) AS n FROM events {WHERE} GROUP BY event "
        "ORDER BY event",
        {},
    ),
    ("array_join", f"SELECT count() FROM events ARRAY JOIN [1, 2] AS x {WHERE}", {}),
    (
        "limit_by",
        f"SELECT event, distinct_id, count() FROM events {WHERE} GROUP BY event, distinct_id "
        "ORDER BY event, distinct_id LIMIT 1 BY event",
        {},
    ),
    ("distinct", f"SELECT DISTINCT event, count() FROM events {WHERE} GROUP BY event ORDER BY event", {}),
    # HogQL drops `WITH ROLLUP` and `WITH TOTALS` when it parses a query.
    ("rollup", f"SELECT event, count() FROM events {WHERE} GROUP BY ROLLUP(event) ORDER BY event", {}),
    ("cube", f"SELECT event, count() FROM events {WHERE} GROUP BY CUBE(event) ORDER BY event", {}),
    ("sample", f"SELECT count() FROM events SAMPLE 1/2 {WHERE}", {}),
    (
        "order_dependent_aggregate",
        f"SELECT arraySort(groupArray(distinct_id)), argMax(event, timestamp) FROM events {WHERE}",
        {},
    ),
    # HogQL can print `medianState` and `medianMerge`. A merged reservoir sample can differ from one sample.
    ("approximate_aggregate", f"SELECT median(toFloat(properties.num)) AS m FROM events {WHERE}", {}),
    (
        "join_read_only_in_its_constraint",
        f"SELECT count() FROM events INNER JOIN (SELECT 'a' AS d) AS x ON events.distinct_id = x.d {WHERE}",
        {},
    ),
    ("distinct_sum", f"SELECT sum(DISTINCT toFloat(properties.num)) FROM events {WHERE}", {}),
    ("subquery_in_filter", f"SELECT count() FROM events {WHERE} AND distinct_id IN (SELECT 'a')", {}),
    ("row_position_function", f"SELECT sum(rowNumberInAllBlocks() >= 0) FROM events {WHERE}", {}),
    (
        "alias_nested_in_a_kept_expression_uses_a_generated_name",
        f"SELECT concat(event AS __flag_calls_state_0, '!') AS e, count() FROM events {WHERE} GROUP BY event "
        "ORDER BY event",
        {},
    ),
    ("alias_chain_too_long_to_inline", f"{_doubling_aliases(12)}, count() FROM events {WHERE}", {}),
    ("not_aggregating", f"SELECT 1 FROM events {WHERE}", {}),
    (
        "generated_name_taken_by_a_later_alias",
        f"SELECT count(), count() AS n, 1 AS `count()` FROM events {WHERE}",
        {},
    ),
    # ClickHouse reads an aggregate of NULL as a plain value. Its Merge form cannot read that value.
    ("count_of_null", f"SELECT count(NULL) FROM events {WHERE}", {}),
    ("count_of_lower_null", f"SELECT count(lower(NULL)) FROM events {WHERE}", {}),
    ("uniq_exact_of_lower_null", f"SELECT uniqExact(lower(NULL)) FROM events {WHERE}", {}),
    ("count_of_null_through_an_alias", f"SELECT lower(NULL) AS x, count(x) FROM events {WHERE}", {}),
    ("sum_of_null", f"SELECT sum(NULL) FROM events {WHERE}", {}),
    ("uniq_if_of_null", f"SELECT uniqIf(NULL, 1) FROM events {WHERE}", {}),
    ("group_by_true", f"SELECT count() FROM events {WHERE} GROUP BY true", {}),
    ("group_by_position_zero", f"SELECT count() FROM events {WHERE} GROUP BY 0", {}),
    ("group_by_negative_position", f"SELECT count() FROM events {WHERE} GROUP BY -1", {}),
    (
        "where_alias_read_in_order_by",
        f"SELECT event, count() FROM events {WHERE} AND (lower(event) AS le) != '' GROUP BY event ORDER BY le",
        {},
    ),
    (
        "aggregate_argument_alias_read_outside",
        f"SELECT event, uniqIf(distinct_id, (event = '$pageview') AS is_pv) AS u, is_pv FROM events {WHERE} "
        "GROUP BY event ORDER BY event",
        {},
    ),
    ("array_join_function", f"SELECT arrayJoin([1, 2]) AS x, count() FROM events {WHERE} GROUP BY x ORDER BY x", {}),
    ("filter_clause", f"SELECT count() FILTER (WHERE event = '$pageview') FROM events {WHERE}", {}),
    ("multi_argument_uniq", f"SELECT uniq(distinct_id, event) FROM events {WHERE}", {}),
    ("unaliased_non_call_column", f"SELECT count() + 1 FROM events {WHERE}", {}),
    ("named_window", f"SELECT event, count() FROM events {WHERE} GROUP BY event WINDOW w AS (ORDER BY event)", {}),
    (
        "with_fill",
        f"SELECT toStartOfDay(timestamp) AS day, count() FROM events {WHERE} GROUP BY day ORDER BY day WITH FILL",
        {},
    ),
    ("column_cte", f"WITH 'a' AS d SELECT count() FROM events {WHERE} AND distinct_id = d", {}),
    (
        "serializes_a_wrapped_union_column",
        f"SELECT JSONExtractString(toJSONString(ifNull(properties, '')), 'num') AS n, count() FROM events {WHERE} "
        "GROUP BY n ORDER BY n",
        {},
    ),
    ("repeated_column_name", f"SELECT uniq(distinct_id) AS `count()`, count() FROM events {WHERE}", {}),
    (
        "alias_uses_a_generated_name",
        f"SELECT count() AS __flag_calls_key_0, event FROM events {WHERE} GROUP BY event ORDER BY event",
        {},
    ),
    (
        "serializes_a_union_column",
        f"SELECT JSONExtractString(toJSONString(properties), 'num') AS n, count() FROM events {WHERE} "
        "GROUP BY n ORDER BY n",
        {},
    ),
    ("reads_the_type_of_a_union_column", f"SELECT countIf(toTypeName(event) = 'String') FROM events {WHERE}", {}),
    (
        "reads_the_type_of_a_wrapped_union_column",
        f"SELECT countIf(toTypeName(lower(event)) = 'String') FROM events {WHERE}",
        {},
    ),
    ("limit_reads_an_alias_defined_in_where", f"SELECT count() FROM events {WHERE} AND (2 AS n) > 0 LIMIT n", {}),
    (
        "offset_reads_an_alias_defined_in_where",
        f"SELECT count() FROM events {WHERE} AND (0 AS n) = 0 LIMIT 5 OFFSET n",
        {},
    ),
    (
        "lambda_parameter_named_like_an_alias",
        f"SELECT 4 AS x, sum(arraySum(arrayMap(x -> x, [1, 2]))) AS total FROM events {WHERE}",
        {},
    ),
    (
        "visible_alias_shadows_a_hidden_alias",
        f"SELECT e.event, e.distinct_id AS event, count() FROM events AS e "
        f"WHERE e.event IN ('$pageview', '$feature_flag_called') AND {WINDOW} GROUP BY e.event, e.distinct_id",
        {},
    ),
]


class _UnionFinder(SyntaxVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.unions: list[ast.SelectSetQuery] = []

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.unions.append(node)
        super().visit_select_set_query(node)


def _modifiers(new_events_schema: bool, **modifiers: Any) -> HogQLQueryModifiers:
    modifiers.setdefault("personsOnEventsMode", ON_EVENTS)
    return HogQLQueryModifiers(useNewEventsSchema=new_events_schema, **modifiers)


class TestFlagCallsUnionPreaggregation(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        with override_settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True):
            self._create_rows()

    def _create_rows(self):
        now = datetime.now(UTC)
        person_a = _create_person(distinct_ids=["a"], team_id=self.team.pk, properties={"email": "a@x.com"})
        person_b = _create_person(distinct_ids=["b"], team_id=self.team.pk, properties={"email": "b@x.com"})
        for distinct_id, person, days_ago, browser, num in (
            ("a", person_a, 1, "Chrome", "3"),
            ("a", person_a, 2, "Chrome", "5"),
            ("b", person_b, 3, "Firefox", "7"),
        ):
            _create_event(
                event="$pageview",
                distinct_id=distinct_id,
                person_id=person.uuid,
                person_properties=person.properties,
                team=self.team,
                timestamp=now - timedelta(days=days_ago),
                properties={"$browser": browser, "num": num, "obj": {"browser": browser}},
            )
        _create_event(
            event="$autocapture",
            distinct_id="a",
            team=self.team,
            timestamp=now - timedelta(days=1),
            elements_chain='label.c:nth-child="1"nth-of-type="1";textarea.d:nth-child="1"nth-of-type="1";'
            'select.e:nth-child="1"nth-of-type="1"',
        )
        _create_event(
            event="$feature_flag_called",
            distinct_id="a",
            person_id=person_a.uuid,
            team=self.team,
            timestamp=now - timedelta(days=2),
            properties={"$feature_flag": "f", "num": "11"},
        )
        for distinct_id, person, days_ago in (("a", person_a, 2), ("b", person_b, 1)):
            _create_flag_evaluations(
                self.team.pk,
                "f",
                timestamp=now - timedelta(days=days_ago),
                distinct_id=distinct_id,
                person_id=person.uuid,
                person_properties=person.properties,
                properties={"num": "11", "$browser": "Safari"},
            )
        _create_event(
            event="$feature_flag_called",
            distinct_id="b",
            person_id=person_b.uuid,
            team=self.team,
            timestamp=now - timedelta(days=100),
            properties={"$feature_flag": "f", "num": "13"},
        )
        _create_event(event="$feature_flag_called", distinct_id="c", team=self.team, timestamp=now - timedelta(days=1))
        flush_persons_and_events()

    def _run(self, query: str, mode: FlagEvaluationsMode, new_events_schema: bool, **modifiers: Any):
        _set_mode(self.organization, mode)
        with _enabled_flags(union=True):
            return execute_hogql_query(query, team=self.team, modifiers=_modifiers(new_events_schema, **modifiers))

    @parameterized.expand(_cases(REWRITTEN_QUERIES))
    def test_aggregating_query_aggregates_in_each_branch_and_returns_the_same_rows(
        self, _name: str, query: str, mode: FlagEvaluationsMode, new_schema: bool, modifiers: dict[str, Any]
    ):
        rewritten = self._run(query, mode, new_schema, **modifiers)
        with override_instance_config("HOGQL_FLAG_CALLS_UNION_PREAGGREGATION_ENABLED", False):
            plain = self._run(query, mode, new_schema, **modifiers)

        assert plain.clickhouse is not None and "UNION ALL" in plain.clickhouse
        assert not REWRITTEN.search(plain.clickhouse)
        assert rewritten.clickhouse is not None and REWRITTEN.search(rewritten.clickhouse)
        assert ") AS events" not in rewritten.clickhouse
        assert (rewritten.columns, rewritten.types, rewritten.results) == (plain.columns, plain.types, plain.results)

    @parameterized.expand([(f"{mode.name.lower()}", mode) for mode in (READ, ONLY)])
    def test_key_that_reads_no_union_column_is_evaluated_once_per_row(self, _name: str, mode: FlagEvaluationsMode):
        query = f"SELECT rand() % 2 AS k, count() AS c FROM events {WHERE} GROUP BY k"
        with override_instance_config("HOGQL_FLAG_CALLS_UNION_PREAGGREGATION_ENABLED", False):
            total = sum(row[1] for row in self._run(query, mode, False).results)

        for _ in range(10):
            rewritten = self._run(query, mode, False)
            assert rewritten.clickhouse is not None and REWRITTEN.search(rewritten.clickhouse)
            # Only the branches evaluate the key. An outer `rand()` would draw a second value for each group.
            assert rewritten.clickhouse.count("rand(") == rewritten.clickhouse.count("countState(")
            keys = [row[0] for row in rewritten.results]
            assert len(keys) == len(set(keys))
            assert sum(row[1] for row in rewritten.results) == total

    @parameterized.expand([(f"{mode.name.lower()}", mode) for mode in (READ, ONLY)])
    def test_user_written_union_with_branch_limits_keeps_its_rows(self, _name: str, mode: FlagEvaluationsMode):
        query = (
            "SELECT count() AS c FROM (SELECT event FROM "
            "(SELECT event AS event FROM events LIMIT 1 UNION ALL SELECT event AS event FROM events LIMIT 1) AS u) AS w "
            f"UNION ALL SELECT count() AS c FROM events {WHERE}"
        )
        rewritten = self._run(query, mode, False)
        with override_instance_config("HOGQL_FLAG_CALLS_UNION_PREAGGREGATION_ENABLED", False):
            plain = self._run(query, mode, False)

        assert rewritten.clickhouse is not None and REWRITTEN.search(rewritten.clickhouse)
        # UNION ALL returns its parts in no fixed order.
        assert sorted(rewritten.results) == sorted(plain.results)
        assert min(row[0] for row in rewritten.results) == 2

    @parameterized.expand([(f"{mode.name.lower()}", mode) for mode in (READ, ONLY)])
    def test_key_on_a_column_typed_differently_in_each_branch_returns_the_same_rows(
        self, _name: str, mode: FlagEvaluationsMode
    ):
        # `events` stores element names as an Enum8 array. The union converts them to strings.
        query = (
            "SELECT arraySort(elements_chain_elements) AS k, count() AS c FROM events "
            f"WHERE event IN ('$autocapture', '$feature_flag_called') AND {WINDOW} GROUP BY k ORDER BY k"
        )
        rewritten = self._run(query, mode, False)
        with override_instance_config("HOGQL_FLAG_CALLS_UNION_PREAGGREGATION_ENABLED", False):
            plain = self._run(query, mode, False)

        assert rewritten.results == plain.results
        assert any(row[0] for row in plain.results)

    def test_filter_on_a_column_typed_differently_in_each_branch_returns_the_same_rows(self):
        # `events` stores element names as an Enum8 array. The union converts them to strings before the filter runs.
        query = (
            "SELECT count() AS c FROM events "
            f"WHERE event IN ('$autocapture', '$feature_flag_called') AND {WINDOW} "
            "AND arraySort(elements_chain_elements)[1] = 'label'"
        )
        rewritten = self._run(query, ONLY, False)
        with override_instance_config("HOGQL_FLAG_CALLS_UNION_PREAGGREGATION_ENABLED", False):
            plain = self._run(query, ONLY, False)

        assert rewritten.results == plain.results

    def test_read_outside_every_key_and_aggregate_fails_as_it_does_without_the_rewrite(self):
        query = f"SELECT distinct_id, count() FROM events {WHERE} GROUP BY event"

        with self.assertRaises(Exception) as rewritten:
            self._run(query, ONLY, False)
        with override_instance_config("HOGQL_FLAG_CALLS_UNION_PREAGGREGATION_ENABLED", False):
            with self.assertRaises(Exception) as plain:
                self._run(query, ONLY, False)

        assert type(rewritten.exception) is type(plain.exception)
        assert type(rewritten.exception).__name__ == "CHQueryErrorNotAnAggregate"


class TestFlagCallsUnionPreaggregationDeclines(APIBaseTest):
    def _sql(self, query: str, mode: FlagEvaluationsMode, new_events_schema: bool, **modifiers: Any) -> str:
        _set_mode(self.organization, mode)
        with _enabled_flags(union=True):
            sql, _ = HogQLQueryExecutor(
                query=query, team=self.team, modifiers=_modifiers(new_events_schema, **modifiers)
            ).generate_clickhouse_sql()
        return sql

    def _assert_declined(self, query: str, mode: FlagEvaluationsMode, new_events_schema: bool, **modifiers: Any):
        with patch.object(preaggregation.logger, "warning") as warning:
            sql = self._sql(query, mode, new_events_schema, **modifiers)
        warning.assert_not_called()
        with override_instance_config("HOGQL_FLAG_CALLS_UNION_PREAGGREGATION_ENABLED", False):
            plain = self._sql(query, mode, new_events_schema, **modifiers)

        assert "UNION ALL" in plain
        assert sql == plain

    @parameterized.expand(_cases(DECLINED_QUERIES))
    def test_query_the_rewrite_cannot_read_keeps_the_union(
        self, _name: str, query: str, mode: FlagEvaluationsMode, new_schema: bool, modifiers: dict[str, Any]
    ):
        self._assert_declined(query, mode, new_schema, **modifiers)

    def test_unexpected_error_in_the_rewrite_keeps_the_union(self):
        query = f"SELECT count() FROM events {WHERE}"
        with patch.object(preaggregation, "_branch_query", side_effect=RuntimeError):
            sql = self._sql(query, ONLY, False)
        with override_instance_config("HOGQL_FLAG_CALLS_UNION_PREAGGREGATION_ENABLED", False):
            plain = self._sql(query, ONLY, False)

        assert sql == plain

    def test_in_cohort_keeps_the_union(self):
        cohort = Cohort.objects.create(team=self.team, name="a", is_static=True)

        self._assert_declined(
            f"SELECT count() FROM events {WHERE} AND person_id IN COHORT {cohort.pk}",
            ONLY,
            False,
            personsOnEventsMode=NO_OVERRIDE,
            inCohortVia=InCohortVia.LEFTJOIN,
        )

    def test_argument_with_a_different_type_in_each_branch_keeps_the_union(self):
        create_for = Database.create_for

        def with_nullable_distinct_id(*args: Any, **kwargs: Any) -> Database:
            database = create_for(*args, **kwargs)
            table = database.get_table(["posthog", "flag_evaluations"])
            table.fields["distinct_id"] = StringDatabaseField(name="distinct_id", nullable=True)
            return database

        with patch.object(Database, "create_for", side_effect=with_nullable_distinct_id):
            self._assert_declined(f"SELECT uniq(distinct_id) FROM events {WHERE}", ONLY, False)


class TestFlagCallsUnionPreaggregationImport(SimpleTestCase):
    def test_transform_imports_in_a_fresh_interpreter(self):
        result = subprocess.run(
            [sys.executable, "-c", "import posthog.hogql.transforms.flag_calls_union_preaggregation"],
            capture_output=True,
            text=True,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "posthog.settings"},
        )

        assert result.returncode == 0, result.stderr


class TestFlagCallsUnionBranchTypes(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            (f"{mode.name.lower()}_{'events_json' if new_schema else 'events'}", mode, new_schema)
            for mode, new_schema in SCHEMAS
        ]
    )
    def test_equal_hogql_types_in_every_branch_mean_equal_clickhouse_types(
        self, _name: str, mode: FlagEvaluationsMode, new_schema: bool
    ):
        _set_mode(self.organization, mode)
        modifiers = _modifiers(new_schema)
        with _enabled_flags(union=True):
            database = Database.create_for(team=self.team, modifiers=modifiers)

        def prepare(names: list[str]) -> tuple[ast.AST | None, HogQLContext]:
            context = HogQLContext(
                team_id=self.team.pk, team=self.team, database=database, modifiers=modifiers, enable_select_queries=True
            )
            query = parse_select(f"SELECT {', '.join(names)} FROM events {WHERE}")
            return prepare_and_print_ast(query, context, "clickhouse")[1], context

        readable = []
        for chain in _readable_chains(database):
            name = ".".join(f"`{part}`" for part in chain)
            try:
                prepare([name])
            except QueryError:
                continue
            readable.append(name)

        checked = 0
        # One query per few fields keeps each union within the memory of a local ClickHouse.
        for batch in (readable[i : i + 8] for i in range(0, len(readable), 8)):
            prepared, context = prepare(batch)
            finder = _UnionFinder()
            finder.visit(prepared)
            for union in finder.unions:
                branches = [branch for branch in union.select_queries() if isinstance(branch, ast.SelectQuery)]
                described = [
                    {
                        row[0]: _WITHOUT_LOW_CARDINALITY.sub(r"\1", row[1])
                        for row in sync_execute(
                            f"DESCRIBE TABLE ({print_prepared_ast(branch, context, 'clickhouse')})", context.values
                        )
                    }
                    for branch in branches
                ]
                for column in branches[0].select:
                    assert isinstance(column, ast.Alias)
                    hogql_types = [
                        next(
                            c.expr.type.resolve_constant_type(context) if c.expr.type else None
                            for c in branch.select
                            if isinstance(c, ast.Alias) and c.alias == column.alias
                        )
                        for branch in branches
                    ]
                    if all(hogql_type is not None and hogql_type == hogql_types[0] for hogql_type in hogql_types):
                        checked += 1
                        assert len({types[column.alias] for types in described}) == 1, (column.alias, described)
        assert checked > 20
