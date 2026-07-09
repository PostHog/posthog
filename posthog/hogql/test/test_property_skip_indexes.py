"""Verify property_to_expr emits SQL that uses ClickHouse skip indexes.

Cross product of (operator) × (skip index type) × (materialization strategy) × (property scope), checked via ``EXPLAIN PLAN indexes=1``. We assert on the plan instead of diffing the printed SQL because the SQL can look fine but still defeat index selection — function wraps the planner can't see through, an ``ifNull(...)``, or the ``nullIf(nullIf(col, ''), 'null')`` sentinel scrub for non-nullable mat columns.
"""

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    cleanup_materialized_columns,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    HogQLQueryModifiers,
    MaterializationMode,
    PersonsOnEventsMode,
    PropertyGroupsMode,
    PropertyOperator,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.observability import HogQLTypeObservability
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import PropertyDefinition

from products.event_definitions.backend.models.property_definition import PropertyType

from ee.clickhouse.materialized_columns.columns import (
    get_bloom_filter_index_name,
    get_minmax_index_name,
    get_ngram_lower_index_name,
    materialize,
)

# Property key chosen to land in ``properties_group_custom`` — no ``$`` prefix and not in ``ignore_custom_properties`` (``token``, ``distinct_id``, ``utm_*``, ...).
EVENT_PROP_KEY = "test_prop"
PERSON_PROP_KEY = "test_prop"

# Numeric strings let us reuse the same key for BETWEEN, which validates operands with ``float()``.
SEED_VALUES = [str(i) for i in range(10)]
LONG_STRING_VALUE = "value_that_is_long_enough"


def _find_all_skip_indexes(plan_json: Any) -> set[str]:
    """Recursively walk a ClickHouse EXPLAIN PLAN JSON, return Skip-type index names."""
    out: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "Indexes" in obj and isinstance(obj["Indexes"], list):
                for idx in obj["Indexes"]:
                    if isinstance(idx, dict) and idx.get("Type") == "Skip" and isinstance(idx.get("Name"), str):
                        out.add(idx["Name"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(plan_json)
    return out


def _extract_persons_where_optimization_subquery(sql: str) -> str | None:
    """Pull the ``where_optimization`` IN-subquery out of a ``FROM persons`` query so we can EXPLAIN it standalone.

    The HogQL ``persons`` lazy table wraps reads in an argMax + ``IN (SELECT where_optimization.id ... WHERE <predicate>)`` dedup pattern. ClickHouse precomputes that IN-subquery as a separate ``CreatingSets`` pipeline whose index usage doesn't surface in the outer ``EXPLAIN PLAN`` — so to check predicate-level skip indexes we EXPLAIN the subquery body directly.

    Returns the subquery body or ``None`` for event-scope queries (no marker present).
    """
    marker = "SELECT where_optimization."
    start = sql.find(marker)
    if start == -1:
        return None
    # Already past the IN(...) subquery's opening paren, so paren depth starts at 1.
    depth = 1
    for i in range(start, len(sql)):
        c = sql[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return sql[start:i]
    return None


def _run_explain_and_get_skip_indexes(query: str, values: dict[str, Any]) -> set[str]:
    # For ``FROM persons`` queries, EXPLAIN the inner ``where_optimization`` subquery instead — see helper docstring for why.
    inner = _extract_persons_where_optimization_subquery(query)
    if inner is not None:
        query = inner
    # Apply the runtime ClickHouse settings (``transform_null_in`` etc.) — skip index selection diverges from real queries without them.
    settings = {
        k: "1" if v is True else "0" if v is False else str(v)
        for k, v in HogQLGlobalSettings().model_dump().items()
        if v is not None
    }
    [[raw]] = sync_execute(
        f"EXPLAIN indexes = 1, json = 1 {query}",
        values,
        settings=settings,
    )
    return _find_all_skip_indexes(json.loads(raw))


class _PropertySkipIndexTestBase(ClickhouseTestMixin, APIBaseTest):
    """Shared scaffolding. Subclasses fix a (scope, materialization, index) combination."""

    SCOPE: Literal["event", "person_on_events", "person"]
    PROPERTY_TO_EXPR_SCOPE: Literal["event", "person"]
    FILTER_TYPE: Literal["event", "person"]
    POE_MODE: PersonsOnEventsMode = PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS

    def setUp(self) -> None:
        super().setUp()
        cleanup_materialized_columns()
        self.addCleanup(cleanup_materialized_columns)

    def _seed(self) -> None:
        """Seed rows so ClickHouse doesn't compile the read to NullSource — EXPLAIN PLAN won't show index info if the planner already concluded the scan reads nothing."""
        if self.SCOPE == "event":
            for i, v in enumerate(SEED_VALUES):
                _create_event(team=self.team, distinct_id=f"d{i}", event="test_event", properties={EVENT_PROP_KEY: v})
            _create_event(
                team=self.team,
                distinct_id="d_long",
                event="test_event",
                properties={EVENT_PROP_KEY: LONG_STRING_VALUE},
            )
        elif self.SCOPE == "person_on_events":
            for i, v in enumerate(SEED_VALUES):
                _create_event(
                    team=self.team,
                    distinct_id=f"d{i}",
                    event="test_event",
                    person_properties={PERSON_PROP_KEY: v},
                )
            _create_event(
                team=self.team,
                distinct_id="d_long",
                event="test_event",
                person_properties={PERSON_PROP_KEY: LONG_STRING_VALUE},
            )
        elif self.SCOPE == "person":
            for i, v in enumerate(SEED_VALUES):
                _create_person(
                    team=self.team,
                    distinct_ids=[f"d{i}"],
                    properties={PERSON_PROP_KEY: v},
                    immediate=True,
                )
            _create_person(
                team=self.team,
                distinct_ids=["d_long"],
                properties={PERSON_PROP_KEY: LONG_STRING_VALUE},
                immediate=True,
            )
        flush_persons_and_events()

    def _filter_to_sql(
        self,
        property_filter: dict[str, Any],
        property_groups_mode: PropertyGroupsMode = PropertyGroupsMode.OPTIMIZED,
        materialization_mode: MaterializationMode = MaterializationMode.AUTO,
    ) -> tuple[str, dict[str, Any]]:
        expr = property_to_expr(property_filter, team=self.team, scope=self.PROPERTY_TO_EXPR_SCOPE)
        table = "persons" if self.SCOPE == "person" else "events"
        select_query = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=[table])),
            where=expr,
        )
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=HogQLQueryModifiers(
                materializationMode=materialization_mode,
                propertyGroupsMode=property_groups_mode,
                personsOnEventsMode=self.POE_MODE,
            ),
        )
        query, _ = prepare_and_print_ast(select_query, context, "clickhouse")
        return query, context.values

    def _assert_indexes(
        self,
        property_filter: dict[str, Any],
        *,
        expected_used: Iterable[str] = (),
        expected_not_used: Iterable[str] = (),
        property_groups_mode: PropertyGroupsMode = PropertyGroupsMode.OPTIMIZED,
        materialization_mode: MaterializationMode = MaterializationMode.AUTO,
    ) -> None:
        query, values = self._filter_to_sql(
            property_filter,
            property_groups_mode=property_groups_mode,
            materialization_mode=materialization_mode,
        )
        # Execute so ``@snapshot_clickhouse_queries`` captures this SELECT (EXPLAIN below doesn't match the SELECT/WITH-prefix filter). Result discarded.
        sync_execute(query, values)
        used = _run_explain_and_get_skip_indexes(query, values)
        expected_used_set = set(expected_used)
        expected_not_used_set = set(expected_not_used)
        if not expected_used_set.issubset(used):
            missing = expected_used_set - used
            raise AssertionError(
                f"Expected skip indexes {sorted(missing)} to be used, but ClickHouse picked {sorted(used)}.\n"
                f"Filter: {property_filter}\nSQL: {query}"
            )
        if expected_not_used_set & used:
            unwanted = expected_not_used_set & used
            raise AssertionError(
                f"Did not expect skip indexes {sorted(unwanted)} to be used, but ClickHouse picked them.\n"
                f"Filter: {property_filter}\nSQL: {query}"
            )

    @property
    def _mat_table(self) -> Literal["events", "person"]:
        return "person" if self.SCOPE == "person" else "events"

    @property
    def _mat_table_column(self) -> Literal["properties", "person_properties"]:
        return "person_properties" if self.SCOPE == "person_on_events" else "properties"

    @property
    def _mat_property_key(self) -> str:
        return EVENT_PROP_KEY if self.SCOPE == "event" else PERSON_PROP_KEY

    def _materialize_with(
        self,
        *,
        is_nullable: bool,
        column_type: str | None = None,
        create_minmax_index: bool = False,
        create_bloom_filter_index: bool = False,
        create_ngram_lower_index: bool = False,
    ):
        return materialize(
            self._mat_table,
            self._mat_property_key,
            table_column=self._mat_table_column,
            is_nullable=is_nullable,
            column_type=column_type,
            create_minmax_index=create_minmax_index,
            create_bloom_filter_index=create_bloom_filter_index,
            create_ngram_lower_index=create_ngram_lower_index,
        )

    def _filter(self, operator: PropertyOperator, value: Any) -> dict[str, Any]:
        return {
            "type": self.FILTER_TYPE,
            "key": self._mat_property_key,
            "operator": operator.value,
            "value": value,
        }


# ============================================================================
# Event properties (events.properties)
# ============================================================================


@snapshot_clickhouse_queries
class TestEventPropertySkipIndexes(_PropertySkipIndexTestBase):
    SCOPE = "event"
    PROPERTY_TO_EXPR_SCOPE = "event"
    FILTER_TYPE = "event"

    # ----- baseline: raw JSON (no materialization) --------------------------
    # No per-property column to index, so no Skip indexes can fire on `properties`.

    @parameterized.expand(
        [
            ("eq", PropertyOperator.EXACT, "0"),
            ("neq", PropertyOperator.IS_NOT, "0"),
            ("lt", PropertyOperator.LT, "5"),
            ("gt", PropertyOperator.GT, "5"),
            ("icontains", PropertyOperator.ICONTAINS, "0"),
            ("is_set", PropertyOperator.IS_SET, None),
            ("is_not_set", PropertyOperator.IS_NOT_SET, None),
            ("in_multi", PropertyOperator.IN_, ["0", "1"]),
        ]
    )
    def test_json_only__no_skip_indexes_used(self, _name: str, operator: PropertyOperator, value: Any) -> None:
        self._seed()
        self._assert_indexes(
            self._filter(operator, value),
            property_groups_mode=PropertyGroupsMode.DISABLED,
            materialization_mode=MaterializationMode.DISABLED,
            expected_used=set(),
            expected_not_used={
                "properties_group_custom_keys_bf",
                "properties_group_custom_values_bf",
            },
        )

    # ----- mat col, NULLABLE, minmax index ----------------------------------

    @parameterized.expand(
        [
            # ``equals(col, 'v')`` fires the minmax range probe.
            ("eq", PropertyOperator.EXACT, "5", True),
            # ``notEquals`` can't be range-pruned by minmax.
            ("neq", PropertyOperator.IS_NOT, "5", False),
            # Range ops fire minmax via the printer's range-comparison rewrite (``ifNull(less(col, x), 0)`` → ``(less(col, x) AND col IS NOT NULL)``).
            ("lt", PropertyOperator.LT, "5", True),
            ("gt", PropertyOperator.GT, "5", True),
            ("lte", PropertyOperator.LTE, "5", True),
            ("gte", PropertyOperator.GTE, "5", True),
            # Multi-value IN uses the printer's ``has([values], col)`` optimized path — minmax prunes granules out of range.
            ("in_multi", PropertyOperator.IN_, ["2", "5"], True),
            # ILIKE can't use minmax on its own, but the printer's combined form with ``col IS NOT NULL`` does get minmax considered (entirely-NULL granules pruneable).
            ("icontains_with_isnotnull", PropertyOperator.ICONTAINS, "5", True),
            # Regex stays wrapped in ``ifNull(match(...), 0)`` — no minmax.
            ("regex", PropertyOperator.REGEX, "[0-9]", False),
            # is_set / is_not_set (``col IS NOT NULL`` / ``col IS NULL``) — whether minmax is considered is ClickHouse-version-dependent (CH 26.3 yes, 25.12 no), so we don't assert it.
        ]
    )
    def test_mat_col_nullable_minmax(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_minmax_index=True)
        index = get_minmax_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    # ----- mat col, NON-NULLABLE, minmax index ------------------------------
    # Non-nullable mat cols store JSON ``null`` / missing values as sentinel strings ``''`` / ``'null'``; the printer normally scrubs them via ``nullIf(nullIf(col, ''), 'null')``, which hides the column from minmax.

    @parameterized.expand(
        [
            ("eq", PropertyOperator.EXACT, "5", True),
            # Range ops use minmax via the rewrite — sentinel exclusion is inlined as extra ``notEquals`` clauses so the comparison itself stays bare.
            ("lt", PropertyOperator.LT, "5", True),
            ("gt", PropertyOperator.GT, "5", True),
            # Multi-value IN: ``has([...], col)`` via the printer's optimized path.
            ("in_multi", PropertyOperator.IN_, ["2", "5"], True),
            # No ``IS NOT NULL`` companion clause here (column is already non-nullable), so minmax has no leverage.
            ("icontains_no_isnotnull", PropertyOperator.ICONTAINS, "5", False),
            ("regex", PropertyOperator.REGEX, "[0-9]", False),
        ]
    )
    def test_mat_col_non_nullable_minmax(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=False, create_minmax_index=True)
        index = get_minmax_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    # ----- mat col, NULLABLE, minmax index — `<` against various constant TYPES ----
    # Mat columns are ``Nullable(String)`` / ``String``; the rewrite doesn't coerce — ClickHouse decides whether to accept the comparison.

    @parameterized.expand(
        [
            # String constants — lexical compare against the String column; minmax fires for every flavor.
            ("string_pure_alpha", "apple"),
            ("string_numeric_looking", "5"),
            ("string_date_looking", "2024-01-15"),
            ("string_iso_datetime_looking", "2024-01-15T10:30:00Z"),
        ]
    )
    def test_mat_col_nullable_minmax_lt_string_constant_flavors(self, _name: str, value: str) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_minmax_index=True)
        index = get_minmax_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(PropertyOperator.LT, value),
            expected_used={index},
        )

    def test_mat_col_nullable_minmax_lt_numeric_looking_strings_compare_lexically(self) -> None:
        # Byte-wise: ``'1000' < '500'`` is true (``'1' < '5'``), ``'200' < '500'`` is true (``'2' < '5'``), ``'900' < '500'`` is false (``'9' > '5'``). Numeric compare would match only ``'200'``, so seeding ``d_1000`` makes the lexical behavior load-bearing.
        # Fix in production: declare ``property_type=Numeric`` (PropertySwapper then wraps in ``toFloat``, but the wrap hides the column from minmax — see ``test_mat_col_lt_typed_numeric_property``).
        _create_event(team=self.team, distinct_id="d_200", event="test_event", properties={EVENT_PROP_KEY: "200"})
        _create_event(team=self.team, distinct_id="d_900", event="test_event", properties={EVENT_PROP_KEY: "900"})
        _create_event(team=self.team, distinct_id="d_1000", event="test_event", properties={EVENT_PROP_KEY: "1000"})
        flush_persons_and_events()

        self._materialize_with(is_nullable=True, create_minmax_index=True)

        result = execute_hogql_query(
            team=self.team,
            query="SELECT distinct_id FROM events WHERE properties.test_prop < '500' ORDER BY distinct_id",
        )
        # Lexical: ``'1000'`` (1 < 5) and ``'200'`` (2 < 5) both match; ``'900'`` (9 > 5) is excluded. Numeric would match only ``'200'``.
        self.assertEqual(result.results, [("d_1000",), ("d_200",)])

    @parameterized.expand(
        [
            # Non-string Python constants — printer emits the constant raw (``less(col, 5)`` or ``less(col, toDateTime64('2024-01-15 ...'))``) and ClickHouse refuses ``String < UInt8 / Float64 / DateTime64`` at execution. (Same behavior as the existing equality / IN rewrites — none of them gate on constant type. For numeric/datetime compare, declare ``property_type`` on the PropertyDefinition; see ``test_mat_col_lt_typed_*``.)
            ("int", 5),
            ("float", 5.5),
            ("datetime", datetime(2024, 1, 15, 10, 30)),
        ]
    )
    def test_mat_col_nullable_minmax_lt_non_string_constant_against_string_column_errors(
        self, _name: str, value: Any
    ) -> None:
        self._seed()
        self._materialize_with(is_nullable=True, create_minmax_index=True)
        query, values = self._filter_to_sql(self._filter(PropertyOperator.LT, value))
        with self.assertRaises(Exception) as ctx:
            sync_execute(query, values)
        # ClickHouse: ``No supertype for types String, UInt8`` or ``No operation less between String and DateTime64``.
        message = str(ctx.exception).lower()
        assert "supertype" in message or "no operation" in message, (
            f"Expected a type-mismatch error from ClickHouse, got: {ctx.exception}"
        )

    def test_mat_col_lt_typed_numeric_property(self) -> None:
        # ``property_type=Numeric`` → PropertySwapper wraps in ``toFloat(col)`` — comparison works (``less(toFloat(col), 5)``) but the Call hides the column from minmax.
        self._seed()
        PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name=EVENT_PROP_KEY,
            property_type=PropertyType.Numeric,
            type=PropertyDefinition.Type.EVENT,
        )
        mat_col = self._materialize_with(is_nullable=True, create_minmax_index=True)
        index = get_minmax_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(PropertyOperator.LT, 5),
            expected_used=set(),
            expected_not_used={index},
        )

    def test_mat_col_lt_typed_datetime_property(self) -> None:
        # ``property_type=DateTime`` → ``toDateTime(col)`` wrap, same minmax-hiding shape as the Numeric case above. Seed with datetime-parsable strings so execution succeeds.
        DT_PROP = "lt_datetime_prop"
        for i in range(10):
            _create_event(
                team=self.team,
                distinct_id=f"d{i}",
                event="test_event",
                properties={DT_PROP: f"2024-01-{i + 1:02d}"},
            )
        flush_persons_and_events()

        PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name=DT_PROP,
            property_type=PropertyType.Datetime,
            type=PropertyDefinition.Type.EVENT,
        )
        mat_col = materialize("events", DT_PROP, table_column="properties", is_nullable=True, create_minmax_index=True)
        index = get_minmax_index_name(mat_col.name)
        self._assert_indexes(
            {
                "type": "event",
                "key": DT_PROP,
                "operator": PropertyOperator.LT.value,
                "value": datetime(2024, 1, 15, 10, 30),
            },
            expected_used=set(),
            expected_not_used={index},
        )

    def test_typed_numeric_mat_col_uses_minmax_index(self) -> None:
        property_key = "typed_numeric_prop"
        for i in range(10):
            _create_event(
                team=self.team,
                distinct_id=f"d{i}",
                event="test_event",
                properties={property_key: i + 0.5},
            )
        flush_persons_and_events()

        PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name=property_key,
            property_type=PropertyType.Numeric,
            type=PropertyDefinition.Type.EVENT,
        )
        mat_col = materialize(
            "events",
            property_key,
            table_column="properties",
            is_nullable=True,
            column_type="Nullable(Float64)",
            create_minmax_index=True,
        )
        index = get_minmax_index_name(mat_col.name)

        query, _ = self._filter_to_sql(
            {
                "type": "event",
                "key": property_key,
                "operator": PropertyOperator.LT.value,
                "value": 5,
            }
        )
        assert f"less(events.{mat_col.name}, 5)" in query
        assert "accurateCastOrNull" not in query
        self._assert_indexes(
            {
                "type": "event",
                "key": property_key,
                "operator": PropertyOperator.LT.value,
                "value": 5,
            },
            expected_used={index},
        )

    def test_typed_datetime_mat_col_uses_minmax_index(self) -> None:
        property_key = "typed_datetime_prop"
        for i in range(10):
            _create_event(
                team=self.team,
                distinct_id=f"d{i}",
                event="test_event",
                properties={property_key: f"2024-01-{i + 1:02d} 10:30:00"},
            )
        flush_persons_and_events()

        PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name=property_key,
            property_type=PropertyType.Datetime,
            type=PropertyDefinition.Type.EVENT,
        )
        mat_col = materialize(
            "events",
            property_key,
            table_column="properties",
            is_nullable=True,
            column_type="Nullable(DateTime64(6, 'UTC'))",
            create_minmax_index=True,
        )
        index = get_minmax_index_name(mat_col.name)

        query, _ = self._filter_to_sql(
            {
                "type": "event",
                "key": property_key,
                "operator": PropertyOperator.LT.value,
                "value": "2024-01-05 00:00:00",
            }
        )
        assert f"less(events.{mat_col.name}, toDateTime64(" in query
        assert "parseDateTime64BestEffortOrNull" not in query
        self._assert_indexes(
            {
                "type": "event",
                "key": property_key,
                "operator": PropertyOperator.LT.value,
                "value": "2024-01-05 00:00:00",
            },
            expected_used={index},
        )

    # ----- mat col, NULLABLE, bloom_filter index ----------------------------
    # bloom_filter is built for membership: ``=`` and IN over string sets.

    @parameterized.expand(
        [
            ("eq", PropertyOperator.EXACT, "5", True),
            ("in_multi", PropertyOperator.IN_, ["2", "5"], True),
            ("neq", PropertyOperator.IS_NOT, "5", False),
            ("not_in", PropertyOperator.NOT_IN, ["2", "5"], False),
            ("lt", PropertyOperator.LT, "5", False),
            ("gt", PropertyOperator.GT, "5", False),
            ("icontains", PropertyOperator.ICONTAINS, "5", False),
            # is_set lowers to ``col IS NOT NULL`` — bloom filter doesn't help here.
            ("is_set", PropertyOperator.IS_SET, None, False),
        ]
    )
    def test_mat_col_nullable_bloom_filter(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_bloom_filter_index=True)
        index = get_bloom_filter_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    # ----- mat col, NON-NULLABLE, bloom_filter index ------------------------

    @parameterized.expand(
        [
            ("eq", PropertyOperator.EXACT, "5", True),
            ("in_multi", PropertyOperator.IN_, ["2", "5"], True),
            # Sentinel-aware IN path bails when ``''`` / ``'null'`` is in the value set (non-nullable mat cols store both as sentinels), so the bloom filter doesn't fire.
            ("in_with_sentinel", PropertyOperator.IN_, ["5", ""], False),
            # Range rewrite emits ``less(col, '5') AND notEquals(col, '') AND notEquals(col, 'null')``; ClickHouse considers each AND-ed clause against every applicable index — minmax fires on ``less``, bloom filter fires on the sentinel ``notEquals`` clauses (granules with no ``''`` / ``'null'`` rows trivially satisfy them).
            ("lt", PropertyOperator.LT, "5", True),
        ]
    )
    def test_mat_col_non_nullable_bloom_filter(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=False, create_bloom_filter_index=True)
        index = get_bloom_filter_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    # ----- mat col, NULLABLE, ngrambf_v1 lower index ------------------------
    # ngram bloom filter on ``lower(col)`` powers case-insensitive substring search.

    @parameterized.expand(
        [
            ("icontains_long", PropertyOperator.ICONTAINS, LONG_STRING_VALUE, True),
            # NOT_ICONTAINS can't be pruned by an ngram bloom filter — proving n-gram absence is what we'd need, and bloom filters can't.
            ("not_icontains", PropertyOperator.NOT_ICONTAINS, "abc", False),
            ("eq", PropertyOperator.EXACT, "5", False),
            ("lt", PropertyOperator.LT, "5", False),
            # property_to_expr / the printer don't decompose regex into n-gram probes.
            ("regex", PropertyOperator.REGEX, LONG_STRING_VALUE, False),
        ]
    )
    def test_mat_col_nullable_ngrambf_lower(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_ngram_lower_index=True)
        index = get_ngram_lower_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    # ----- mat col, NON-NULLABLE, ngrambf_v1 lower index --------------------

    @parameterized.expand(
        [
            ("icontains_long", PropertyOperator.ICONTAINS, LONG_STRING_VALUE, True),
            # Sentinel patterns (matching ``''`` / ``'null'``) bail out of the ILIKE optimization on non-nullable cols to preserve null semantics, so the ngram index doesn't fire.
            ("icontains_null_sentinel", PropertyOperator.ICONTAINS, "null", False),
        ]
    )
    def test_mat_col_non_nullable_ngrambf_lower(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=False, create_ngram_lower_index=True)
        index = get_ngram_lower_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    # ----- property group map column ----------------------------------------
    # ``properties_group_custom`` is a ``Map(String, String)`` with bloom filters on ``mapKeys`` (``..._keys_bf``) and ``mapValues`` (``..._values_bf``).

    PG_KEYS_INDEX = "properties_group_custom_keys_bf"
    PG_VALUES_INDEX = "properties_group_custom_values_bf"

    @parameterized.expand(
        [
            # ``equals(map[key], 'v')`` — both keys and values bloom filters apply.
            ("eq_string", PropertyOperator.EXACT, "5", {PG_KEYS_INDEX, PG_VALUES_INDEX}, set()),
            # is_set → ``has(map, key)`` — keys bloom filter applies.
            ("is_set", PropertyOperator.IS_SET, None, {PG_KEYS_INDEX}, {PG_VALUES_INDEX}),
            # is_not_set → ``not(has(map, key))`` — keys bloom filter still applies (proves granules where the key is definitely absent).
            ("is_not_set", PropertyOperator.IS_NOT_SET, None, {PG_KEYS_INDEX}, {PG_VALUES_INDEX}),
            # Multi-value IN → ``and(has(map, key), in(map[key], tuple(...)))`` — keys only; ``transform_null_in`` defaults break a direct values-bloom probe.
            ("in_multi", PropertyOperator.IN_, ["2", "5"], {PG_KEYS_INDEX}, {PG_VALUES_INDEX}),
            # Range ops fall back to the unoptimized ``has(map, key) ? map[key] : null`` form — no bloom filter applies.
            ("lt", PropertyOperator.LT, "5", set(), {PG_KEYS_INDEX, PG_VALUES_INDEX}),
            # ILIKE on a map value isn't decomposed into ngram or key probes.
            ("icontains", PropertyOperator.ICONTAINS, "5", set(), {PG_KEYS_INDEX, PG_VALUES_INDEX}),
        ]
    )
    def test_property_group_optimized(
        self,
        _name: str,
        operator: PropertyOperator,
        value: Any,
        expected_used: set[str],
        expected_not_used: set[str],
    ) -> None:
        self._seed()
        self._assert_indexes(
            self._filter(operator, value),
            property_groups_mode=PropertyGroupsMode.OPTIMIZED,
            expected_used=expected_used,
            expected_not_used=expected_not_used,
        )

    # ----- observability ------------------------------------------------------

    def test_observability_records_property_usage_and_range_rewrite(self) -> None:
        self._seed()
        self._materialize_with(is_nullable=True, create_minmax_index=True)

        stats = HogQLTypeObservability(dialect="clickhouse", source="unknown")
        with patch("posthog.hogql.printer.utils.create_hogql_type_observability", return_value=stats):
            self._filter_to_sql(self._filter(PropertyOperator.LT, "5"))

        # The column is nullable, so the bare comparison is guarded by isNotNull(col): a "fired_if_null" outcome.
        assert stats.materialized_range_rewrite["fired_if_null"] >= 1
        assert stats.materialized_property_usage["materialized_column"] >= 1

    def test_observability_records_json_property_usage(self) -> None:
        self._seed()

        stats = HogQLTypeObservability(dialect="clickhouse", source="unknown")
        with patch("posthog.hogql.printer.utils.create_hogql_type_observability", return_value=stats):
            self._filter_to_sql(
                self._filter(PropertyOperator.EXACT, "5"),
                property_groups_mode=PropertyGroupsMode.DISABLED,
                materialization_mode=MaterializationMode.DISABLED,
            )

        assert stats.materialized_property_usage["json"] >= 1
        assert stats.materialized_property_usage["materialized_column"] == 0


# ============================================================================
# Person-on-Events (events.person_properties)
# ============================================================================


@snapshot_clickhouse_queries
class TestPersonOnEventsPropertySkipIndexes(_PropertySkipIndexTestBase):
    SCOPE = "person_on_events"
    PROPERTY_TO_EXPR_SCOPE = "event"
    FILTER_TYPE = "person"
    POE_MODE = PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS

    @parameterized.expand(
        [
            ("eq", PropertyOperator.EXACT, "5", True),
            # Range ops use minmax via the printer's range-comparison rewrite.
            ("lt", PropertyOperator.LT, "5", True),
            ("gt", PropertyOperator.GT, "5", True),
            ("in_multi", PropertyOperator.IN_, ["2", "5"], True),
            ("icontains_with_isnotnull", PropertyOperator.ICONTAINS, "5", True),
            # is_set omitted — minmax usage for ``col IS NOT NULL`` is ClickHouse-version-dependent (CH 26.3 yes, 25.12 no).
        ]
    )
    def test_mat_col_nullable_minmax(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_minmax_index=True)
        index = get_minmax_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    @parameterized.expand(
        [
            ("eq", PropertyOperator.EXACT, "5", True),
            ("in_multi", PropertyOperator.IN_, ["2", "5"], True),
            ("not_in", PropertyOperator.NOT_IN, ["2", "5"], False),
            ("lt", PropertyOperator.LT, "5", False),
        ]
    )
    def test_mat_col_nullable_bloom_filter(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_bloom_filter_index=True)
        index = get_bloom_filter_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    @parameterized.expand(
        [
            ("icontains_long", PropertyOperator.ICONTAINS, LONG_STRING_VALUE, True),
            ("eq", PropertyOperator.EXACT, "5", False),
        ]
    )
    def test_mat_col_nullable_ngrambf_lower(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_ngram_lower_index=True)
        index = get_ngram_lower_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    # ----- property group: person_properties_map_custom ---------------------

    PG_KEYS_INDEX = "person_properties_map_custom_keys_bf"
    PG_VALUES_INDEX = "person_properties_map_custom_values_bf"

    @parameterized.expand(
        [
            ("eq_string", PropertyOperator.EXACT, "5", {PG_KEYS_INDEX, PG_VALUES_INDEX}, set()),
            ("is_set", PropertyOperator.IS_SET, None, {PG_KEYS_INDEX}, {PG_VALUES_INDEX}),
            ("in_multi", PropertyOperator.IN_, ["2", "5"], {PG_KEYS_INDEX}, {PG_VALUES_INDEX}),
            ("lt", PropertyOperator.LT, "5", set(), {PG_KEYS_INDEX, PG_VALUES_INDEX}),
        ]
    )
    def test_property_group_optimized(
        self,
        _name: str,
        operator: PropertyOperator,
        value: Any,
        expected_used: set[str],
        expected_not_used: set[str],
    ) -> None:
        self._seed()
        self._assert_indexes(
            self._filter(operator, value),
            property_groups_mode=PropertyGroupsMode.OPTIMIZED,
            expected_used=expected_used,
            expected_not_used=expected_not_used,
        )


# ============================================================================
# Person scope (persons.properties — queried directly via ``FROM persons``)
# ============================================================================


@snapshot_clickhouse_queries
class TestPersonPropertySkipIndexes(_PropertySkipIndexTestBase):
    """Person properties via ``FROM persons``. The persons table has no built-in property-group map columns, so the only way to get a skip index is by materializing a column on the persons table directly."""

    SCOPE = "person"
    PROPERTY_TO_EXPR_SCOPE = "person"
    FILTER_TYPE = "person"

    @parameterized.expand(
        [
            ("eq", PropertyOperator.EXACT, "5", True),
            # Range ops use minmax via the printer's range-comparison rewrite.
            ("lt", PropertyOperator.LT, "5", True),
            ("gt", PropertyOperator.GT, "5", True),
            ("icontains_with_isnotnull", PropertyOperator.ICONTAINS, "5", True),
            # is_set omitted — minmax usage for ``col IS NOT NULL`` is ClickHouse-version-dependent (CH 26.3 yes, 25.12 no).
        ]
    )
    def test_mat_col_nullable_minmax(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_minmax_index=True)
        index = get_minmax_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    @parameterized.expand(
        [
            ("eq", PropertyOperator.EXACT, "5", True),
            ("in_multi", PropertyOperator.IN_, ["2", "5"], True),
            ("lt", PropertyOperator.LT, "5", False),
        ]
    )
    def test_mat_col_nullable_bloom_filter(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_bloom_filter_index=True)
        index = get_bloom_filter_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )

    @parameterized.expand(
        [
            ("icontains_long", PropertyOperator.ICONTAINS, LONG_STRING_VALUE, True),
            ("eq", PropertyOperator.EXACT, "5", False),
        ]
    )
    def test_mat_col_nullable_ngrambf_lower(
        self, _name: str, operator: PropertyOperator, value: Any, should_use: bool
    ) -> None:
        self._seed()
        mat_col = self._materialize_with(is_nullable=True, create_ngram_lower_index=True)
        index = get_ngram_lower_index_name(mat_col.name)
        self._assert_indexes(
            self._filter(operator, value),
            expected_used={index} if should_use else set(),
            expected_not_used=set() if should_use else {index},
        )
