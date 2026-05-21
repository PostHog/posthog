"""Verify property_to_expr emits SQL that uses ClickHouse skip indexes.

For each combination of:
  - comparison operator (=, !=, <, <=, >, >=, BETWEEN, ILIKE, IS_SET, IN, regex)
  - skip index type (minmax, bloom_filter, ngrambf_v1 lower, property-group keys_bf/values_bf)
  - materialization strategy (raw JSON, mat col nullable, mat col non-nullable, dmat, property group map)
  - property scope (event, person-on-events, person)

verify whether ClickHouse's EXPLAIN PLAN actually selects the expected skip indexes.

We check the plan instead of just diffing the printed SQL because the SQL can look fine but
still defeat index selection — wrapping the column in a non-monotonic function, an ``ifNull(...)``
that the planner can't see through, or a ``nullIf(nullIf(col, ''), 'null')`` sentinel scrub for
non-nullable mat columns.

Each row in the matrix below carries an explicit ``expected_used`` flag. Where the current behavior
is sub-optimal (an index that *could* fire doesn't, because of how property_to_expr or the printer
wraps the comparison), the row's docstring/comment calls it out so future fixes can flip the flag
rather than discover the gap from scratch.
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
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property import property_to_expr

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition

from products.event_definitions.backend.models.property_definition import PropertyType

from ee.clickhouse.materialized_columns.columns import (
    get_bloom_filter_index_name,
    get_minmax_index_name,
    get_ngram_lower_index_name,
    materialize,
)

# A property key that:
#  - does NOT start with `$` (so it falls into `properties_group_custom`, not feature_flags/ai)
#  - is not in `ignore_custom_properties` (token, distinct_id, utm_*, ...)
# These two together place the key in the ``custom`` property group.
EVENT_PROP_KEY = "test_prop"
PERSON_PROP_KEY = "test_prop"

# Seed values. Numeric strings let us reuse the same key for BETWEEN, which
# validates operands with ``float()``.
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
    """Pull the ``where_optimization`` IN-subquery out of a ``FROM persons`` HogQL query.

    The HogQL ``persons`` lazy table wraps every read in an argMax + IN-subquery for
    version dedup, producing SQL shaped like::

        FROM person WHERE id IN (
            SELECT where_optimization.id AS id FROM person AS where_optimization
            WHERE <our property predicate>
        )

    ClickHouse's ``EXPLAIN PLAN indexes=1`` precomputes the IN-subquery as a separate
    pipeline (``CreatingSets``) and does not surface its index usage in the outer
    plan. To see whether the predicate actually triggers a skip index, we have to
    EXPLAIN that subquery on its own. This helper finds and returns it as a
    standalone SELECT, balancing parens to handle nested ``and(...)`` expressions.

    Returns the inner ``SELECT where_optimization.id ...`` body, or ``None`` if
    the marker isn't present (event-scope queries don't have it).
    """
    marker = "SELECT where_optimization."
    start = sql.find(marker)
    if start == -1:
        return None
    # We're already past the IN(...) subquery's opening paren, so paren depth starts at 1.
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
    # If the query is a ``FROM persons`` HogQL wrapper, EXPLAIN the inner
    # ``where_optimization`` subquery instead — see helper docstring for why.
    inner = _extract_persons_where_optimization_subquery(query)
    if inner is not None:
        query = inner
    # Apply the same ClickHouse settings the runtime uses (transform_null_in etc.).
    # Skip index selection diverges from real queries without these.
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
        """Seed rows so ClickHouse doesn't compile the read to NullSource.

        EXPLAIN PLAN won't show index info if the planner already concluded
        the scan reads nothing.
        """
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
        # Execute the actual SELECT so the @snapshot_clickhouse_queries class decorator picks it
        # up via capture_select_queries. EXPLAIN below doesn't match that filter, so only the
        # real SELECT lands in the snapshot. Result is discarded; we only care about the printed
        # SQL and the EXPLAIN plan.
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
        create_minmax_index: bool = False,
        create_bloom_filter_index: bool = False,
        create_ngram_lower_index: bool = False,
    ):
        return materialize(
            self._mat_table,
            self._mat_property_key,
            table_column=self._mat_table_column,
            is_nullable=is_nullable,
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
    # Cases marked "current limitation" are gaps where property_to_expr emits
    # an ``ifNull(less(col, x), 0)`` wrapper that defeats the minmax index.
    # Lifting that wrapper (or letting the printer unwrap it on minmax-friendly
    # ops) would let these fire.

    @parameterized.expand(
        [
            # ``equals(col, 'v')`` fires the minmax range probe.
            ("eq", PropertyOperator.EXACT, "5", True),
            # ``notEquals`` can't be range-pruned by minmax.
            ("neq", PropertyOperator.IS_NOT, "5", False),
            # Range ops fire minmax via the printer's
            # ``_get_optimized_materialized_column_range_operation`` rewrite, which replaces
            # ``ifNull(less(col, x), 0)`` with ``(less(col, x) AND col IS NOT NULL)``.
            ("lt", PropertyOperator.LT, "5", True),
            ("gt", PropertyOperator.GT, "5", True),
            ("lte", PropertyOperator.LTE, "5", True),
            ("gte", PropertyOperator.GTE, "5", True),
            # Multi-value IN goes through the printer's optimized path which uses
            # ``has([values], col)`` — minmax can prune granules where no value is in range.
            ("in_multi", PropertyOperator.IN_, ["2", "5"], True),
            # icontains itself can't use minmax, but the optimized printer path
            # adds ``col IS NOT NULL`` next to the ILIKE, which minmax CAN prune
            # (granules that are entirely NULL).
            ("icontains_with_isnotnull", PropertyOperator.ICONTAINS, "5", True),
            # Regex stays wrapped in ``ifNull(match(...), 0)`` — no minmax.
            ("regex", PropertyOperator.REGEX, "[0-9]", False),
            # is_set lowers to ``col IS NOT NULL``, which minmax prunes.
            ("is_set", PropertyOperator.IS_SET, None, True),
            # is_not_set lowers to ``col IS NULL``. ClickHouse can pick up the minmax
            # for the inverse, marking granules where the value is always set as skippable.
            ("is_not_set", PropertyOperator.IS_NOT_SET, None, True),
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
    # Non-nullable mat columns store JSON ``null`` and missing values as the
    # string ``'null'`` / ``''``. The printer scrubs both via
    # ``nullIf(nullIf(col, ''), 'null')``, which makes the planner unable to
    # see through to the underlying column for range ops.

    @parameterized.expand(
        [
            ("eq", PropertyOperator.EXACT, "5", True),
            # Range ops use minmax via the printer's range-comparison rewrite. For non-nullable
            # mat cols the sentinel exclusion is inlined as extra AND clauses so the comparison
            # itself stays bare and minmax-friendly.
            ("lt", PropertyOperator.LT, "5", True),
            ("gt", PropertyOperator.GT, "5", True),
            # Multi-value IN goes through the optimized printer path: ``has([...], col)``.
            ("in_multi", PropertyOperator.IN_, ["2", "5"], True),
            # Unlike the nullable case the printer doesn't emit an ``IS NOT NULL`` companion
            # clause here (the column type is already non-nullable), so minmax has no leverage.
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
    # Documents what happens when the filter value's Python type doesn't line up
    # with the materialized column's String storage. Mat columns are typed
    # ``Nullable(String)`` (or ``String``); the printer hands the constant to
    # ClickHouse as-is. There's no type coercion in our rewrite — that's left
    # to ClickHouse, which refuses to compare mismatched types.

    @parameterized.expand(
        [
            # String constants — compared lexically against the String column.
            # All flavors of string (alphabetic, digit-like, datetime-like) work and minmax fires.
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

    @parameterized.expand(
        [
            # Numeric and datetime Python constants — the printer emits the constant raw
            # (e.g. ``less(events.mat_test_prop, 5)`` or
            # ``less(events.mat_test_prop, toDateTime64('2024-01-15 ...'))``).
            # ClickHouse refuses to compare String to UInt8 / Float64 / DateTime64 and the
            # query fails to execute. The rewrite is what the existing equality / IN rewrites
            # do too — none of them gate on constant type. If you mean a numeric/datetime
            # comparison, define the property's ``property_type`` so PropertySwapper coerces
            # the column appropriately (see ``test_mat_col_lt_typed_*`` below).
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
        # ClickHouse: ``No supertype for types String, UInt8`` or
        # ``No operation less between String and DateTime64``.
        message = str(ctx.exception).lower()
        assert "supertype" in message or "no operation" in message, (
            f"Expected a type-mismatch error from ClickHouse, got: {ctx.exception}"
        )

    def test_mat_col_lt_typed_numeric_property(self) -> None:
        # PropertyDefinition.property_type=Numeric tells PropertySwapper to wrap the
        # column in ``toFloat(...)``. That coerces the stored String to a Float and lets
        # ``less(toFloat(col), 5)`` evaluate, but the ``toFloat`` Call hides the column
        # from minmax — the index doesn't fire.
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
        # PropertyDefinition.property_type=DateTime triggers a ``toDateTime(col)`` wrap.
        # Same shape as the Numeric case — the column is hidden behind a Call so minmax
        # never fires. We don't execute the query here because the seed values aren't
        # datetime-parsable; the EXPLAIN plan still tells us what we need.
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
            # The sentinel-aware optimized path bails for empty-string/null in the value set
            # (non-nullable mat columns store both as the string ``''`` or ``'null'``), so the
            # bloom filter doesn't fire here.
            ("in_with_sentinel", PropertyOperator.IN_, ["5", ""], False),
            # The range-comparison rewrite emits ``less(col, '5') AND notEquals(col, '')
            # AND notEquals(col, 'null')``. ClickHouse considers each AND-ed clause against
            # every applicable index — minmax fires on the ``less`` half (range pruning),
            # and the bloom filter fires on the ``notEquals`` halves (granules with no ``''``
            # / ``'null'`` rows trivially satisfy the sentinel checks).
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
            # NOT_ICONTAINS can't be pruned by an ngram bloom filter — absence
            # of an n-gram is what we'd need, and bloom filters can't prove that.
            ("not_icontains", PropertyOperator.NOT_ICONTAINS, "abc", False),
            ("eq", PropertyOperator.EXACT, "5", False),
            ("lt", PropertyOperator.LT, "5", False),
            # Regex isn't decomposed into n-gram probes by property_to_expr / the printer.
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
            # Sentinel patterns (matching '' or 'null') bail out of the ILIKE
            # optimization on non-nullable columns to preserve null semantics,
            # so the ngram index doesn't fire.
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
    # ``properties_group_custom`` is a ``Map(String, String)`` with bloom filters on
    # ``mapKeys`` (``..._keys_bf``) and ``mapValues`` (``..._values_bf``).

    PG_KEYS_INDEX = "properties_group_custom_keys_bf"
    PG_VALUES_INDEX = "properties_group_custom_values_bf"

    @parameterized.expand(
        [
            # ``equals(map[key], 'v')`` — both keys and values bloom filters apply.
            ("eq_string", PropertyOperator.EXACT, "5", {PG_KEYS_INDEX, PG_VALUES_INDEX}, set()),
            # is_set → ``has(map, key)`` — keys bloom filter applies.
            ("is_set", PropertyOperator.IS_SET, None, {PG_KEYS_INDEX}, {PG_VALUES_INDEX}),
            # is_not_set → ``not(has(map, key))``. ClickHouse still picks up the keys bloom filter
            # here (the planner can use it to confirm granules where the key is definitely absent).
            ("is_not_set", PropertyOperator.IS_NOT_SET, None, {PG_KEYS_INDEX}, {PG_VALUES_INDEX}),
            # Multi-value IN → ``and(has(map, key), in(map[key], tuple(...)))`` — keys only;
            # transform_null_in defaults break a direct values-bloom probe.
            ("in_multi", PropertyOperator.IN_, ["2", "5"], {PG_KEYS_INDEX}, {PG_VALUES_INDEX}),
            # Range ops fall back to the unoptimized path (``has(map, key) ? map[key] : null``
            # compared with a constant) and the bloom filters don't apply.
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

    # ----- dmat (dynamic materialized column) -------------------------------
    # dmat columns have no skip indexes attached today, but the printer should
    # route the property to the dmat column instead of JSON extraction.

    def test_dmat_string_no_skip_indexes(self) -> None:
        self._seed()
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name=EVENT_PROP_KEY,
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

        query, _ = self._filter_to_sql(self._filter(PropertyOperator.EXACT, "5"))
        assert "dmat_string_0" in query, f"Expected dmat_string_0 in SQL, got: {query}"
        # No skip indexes are configured on dmat columns today.
        self._assert_indexes(self._filter(PropertyOperator.EXACT, "5"), expected_used=set())


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
            ("is_set", PropertyOperator.IS_SET, None, True),
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
    """Person properties on the persons table, queried via ``FROM persons``.

    The persons table has no built-in property-group map columns, so the only
    way to get a skip index here is by materializing a column on the persons
    table directly.
    """

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
            ("is_set", PropertyOperator.IS_SET, None, True),
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
