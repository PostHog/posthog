"""Unit tests for the dormant ClickHouse physical optimization pass (PRINTER_REARCHITECTURE.md §4.5, §12.3).

The pass is built + tested in isolation this round (it is NOT wired into the print pipeline). To exercise it we reproduce
the ClickHouse prep pipeline manually:

    prepared = prepare_ast_for_printing(query, dialect="clickhouse")   # resolve + swap (PropertyType reads remain)
    lowered  = lower_property_access(prepared, context)                 # PropertyType -> JSONFieldAccess (gate on)
    physical = clickhouse_physical_passes(lowered, context)             # JSONFieldAccess -> mat columns + skip-index forms
    sql      = print_prepared_ast(physical, context, dialect="clickhouse")

The correctness gate is **result-equivalence**, not byte-identical SQL (doc §8.7): the master printer string-builds `? :`
ternaries, chained `AND`, `col IS NOT NULL`, and inline constants no AST reproduces; the lowered AST prints differently but
executes identically and keeps the same skip-index eligibility. So every test compares against the **master oracle** — the
same query printed *without* the gate (`lower_property_access` off, no physical pass) — and asserts (a) identical executed
rows and (b) identical skip-index usage via `EXPLAIN`. SQL text is deliberately not asserted.

Covered: value read; equals/range/in/like/ilike; is-set over-match (§12.7 — master reads the scrubbed mat column under
`isNull`); `$ai_*` no-nullIf; dmat; property groups (OPTIMIZED); restricted (declines onto the JSONDropKeys blob); person
properties on-events and joined (the §8.1 ClickHouse-table-name case).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    cleanup_materialized_columns,
    flush_persons_and_events,
    get_index_from_explain,
    materialized,
)

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, MaterializationMode, PersonsOnEventsMode, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.transforms.clickhouse_physical_passes import (
    clickhouse_physical_passes,
    resolve_materialized_property_source,
)
from posthog.hogql.transforms.logical_property_lowering import lower_property_access
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition

from products.event_definitions.backend.models.property_definition import PropertyType

from ee.clickhouse.materialized_columns.columns import get_minmax_index_name, materialize


class _PhysicalPassTestBase(ClickhouseTestMixin, APIBaseTest):
    """Shared scaffolding: print a query via the master path vs the lowered + physical-pass path, and compare."""

    maxDiff = None

    def setUp(self) -> None:
        super().setUp()
        cleanup_materialized_columns()
        self.addCleanup(cleanup_materialized_columns)

    def _modifiers(
        self,
        *,
        materialization_mode: MaterializationMode = MaterializationMode.AUTO,
        property_groups_mode: PropertyGroupsMode = PropertyGroupsMode.DISABLED,
        poe_mode: PersonsOnEventsMode = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
    ) -> HogQLQueryModifiers:
        return HogQLQueryModifiers(
            materializationMode=materialization_mode,
            propertyGroupsMode=property_groups_mode,
            personsOnEventsMode=poe_mode,
        )

    def _context(self, *, lower: bool, modifiers: HogQLQueryModifiers) -> HogQLContext:
        return HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            lower_property_access=lower,
            modifiers=modifiers,
        )

    def _print_master(self, sql: str, modifiers: HogQLQueryModifiers) -> tuple[str, dict[str, Any]]:
        """The master oracle: prepare + print with no lowering and no physical pass."""
        context = self._context(lower=False, modifiers=modifiers)
        prepared = prepare_ast_for_printing(parse_select(sql), context=context, dialect="clickhouse")
        assert prepared is not None
        printed = print_prepared_ast(prepared, context=context, dialect="clickhouse")
        return printed, context.values

    def _print_lowered(self, sql: str, modifiers: HogQLQueryModifiers) -> tuple[str, dict[str, Any]]:
        """The pass under test: prepare, then lower to JSONFieldAccess, then run the physical pass, then print."""
        context = self._context(lower=True, modifiers=modifiers)
        prepared = prepare_ast_for_printing(parse_select(sql), context=context, dialect="clickhouse")
        assert prepared is not None
        lowered = lower_property_access(prepared, context)
        physical = clickhouse_physical_passes(lowered, context)
        printed = print_prepared_ast(physical, context=context, dialect="clickhouse")
        return printed, context.values

    def _assert_results_equivalent(self, sql: str, modifiers: HogQLQueryModifiers) -> tuple[str, dict[str, Any]]:
        """Execute the master and lowered SQL; assert identical rows. Returns the lowered (SQL, values) for further checks."""
        master_sql, master_values = self._print_master(sql, modifiers)
        lowered_sql, lowered_values = self._print_lowered(sql, modifiers)

        master_rows = sync_execute(master_sql, master_values)
        lowered_rows = sync_execute(lowered_sql, lowered_values)
        self.assertEqual(
            sorted(master_rows),
            sorted(lowered_rows),
            f"\nResult mismatch.\nMASTER SQL: {master_sql}\nLOWERED SQL: {lowered_sql}",
        )
        return lowered_sql, lowered_values

    def _assert_index_equivalent(self, sql: str, modifiers: HogQLQueryModifiers, index_name: str) -> None:
        """Assert the master and lowered SQL agree on whether the named skip index is used."""
        master_sql, master_values = self._print_master(sql, modifiers)
        lowered_sql, lowered_values = self._print_lowered(sql, modifiers)
        master_used = get_index_from_explain(master_sql, index_name, placeholder_values=master_values) is not None
        lowered_used = get_index_from_explain(lowered_sql, index_name, placeholder_values=lowered_values) is not None
        self.assertEqual(
            master_used,
            lowered_used,
            f"\nSkip-index usage diverged for {index_name} (master={master_used}, lowered={lowered_used}).\n"
            f"MASTER SQL: {master_sql}\nLOWERED SQL: {lowered_sql}",
        )
        # Both should actually use it for the index-eligible cases the callers pick.
        self.assertTrue(lowered_used, f"Expected {index_name} to be used by the lowered SQL.\nSQL: {lowered_sql}")

    @contextmanager
    def _materialize_person_properties(self, prop: str, *, is_nullable: bool) -> Iterator[str]:
        """Materialize an events.person_properties column for PoE-on-events tests, removing it on exit.

        The shared `materialized()` helper hardcodes `table_column="properties"`, so a person property on the events
        table (PoE-on-events reads `events.person_properties`) needs `materialize(table_column="person_properties")`.
        """
        column = materialize("events", prop, table_column="person_properties", is_nullable=is_nullable)
        try:
            yield column.name
        finally:
            cleanup_materialized_columns()


# The match/no-match event set, reused across the event-property scenarios.
EVENTS: tuple[tuple[str, dict], ...] = (
    ("match", {"test_prop": "v"}),
    ("other", {"test_prop": "other"}),
    ("a_in", {"test_prop": "a"}),
    ("five", {"test_prop": "5"}),
    ("seven", {"test_prop": "7"}),
    ("empty", {"test_prop": ""}),
    ("null_str", {"test_prop": "null"}),
    ("absent", {}),
    ("explicit_null", {"test_prop": None}),
    ("foobar", {"test_prop": "FooBar"}),
)


class TestEventPropertyPhysicalPass(_PhysicalPassTestBase):
    def _seed(self) -> None:
        for distinct_id, properties in EVENTS:
            _create_event(team=self.team, distinct_id=distinct_id, event="phys_event", properties=properties)
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("value_read", "SELECT distinct_id, properties.test_prop FROM events WHERE event = 'phys_event'"),
            ("equals", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop = 'v'"),
            ("not_equals", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop != 'v'"),
            ("range_gt", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop > '5'"),
            ("range_lte", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop <= '7'"),
            (
                "in_list",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop IN ('a', 'v')",
            ),
            (
                "not_in_list",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop NOT IN ('a', 'v')",
            ),
            ("like", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop LIKE 'Foo%'"),
            (
                "not_like",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop NOT LIKE 'Foo%'",
            ),
            (
                "ilike",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop ILIKE '%oob%'",
            ),
            (
                "not_ilike",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop NOT ILIKE '%oob%'",
            ),
            (
                "is_set",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop IS NOT NULL",
            ),
        ]
    )
    def test_nullable_results_equivalent(self, _name: str, sql: str) -> None:
        self._seed()
        with materialized("events", "test_prop", is_nullable=True):
            self._assert_results_equivalent(sql, self._modifiers())

    @parameterized.expand(
        [
            ("value_read", "SELECT distinct_id, properties.test_prop FROM events WHERE event = 'phys_event'"),
            ("equals", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop = 'v'"),
            ("not_equals", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop != 'v'"),
            ("range_gt", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop > '5'"),
            (
                "in_list",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop IN ('a', 'v')",
            ),
            (
                "not_in_list",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop NOT IN ('a', 'v')",
            ),
            ("like", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop LIKE 'Foo%'"),
            (
                "ilike",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop ILIKE '%oob%'",
            ),
            # Empty-string and 'null'-string comparisons hit the sentinel-bail branch (no optimization) — still must match.
            ("eq_empty", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop = ''"),
            (
                "eq_null_str",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop = 'null'",
            ),
        ]
    )
    def test_non_nullable_results_equivalent(self, _name: str, sql: str) -> None:
        self._seed()
        with materialized("events", "test_prop", is_nullable=False):
            self._assert_results_equivalent(sql, self._modifiers())

    def test_is_not_set_over_match_preserved(self) -> None:
        # §12.7 / §8.2: is-set over a NON-NULLABLE materialized column reads the scrubbed mat column, over-matching
        # empty-string and the literal 'null' string. The pass must reproduce master's over-match exactly (decision A).
        self._seed()
        sql = "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop IS NULL"
        with materialized("events", "test_prop", is_nullable=False):
            lowered_sql, lowered_values = self._assert_results_equivalent(sql, self._modifiers())
            rows = sync_execute(lowered_sql, lowered_values)
            # Over-match: absent + explicit_null (truthful) PLUS empty + null_str (the §8.2 quirk).
            self.assertEqual({r[0] for r in rows}, {"absent", "explicit_null", "empty", "null_str"})
            # The mat path must not touch the JSON blob (that is the perf regression the column prevents).
            self.assertNotIn("json", lowered_sql.lower())

    @parameterized.expand(
        [
            (
                "equals",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop = 'v'",
                True,
            ),
            (
                "range_gt",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop > '5'",
                True,
            ),
            (
                "in_list",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop IN ('a', 'v')",
                True,
            ),
        ]
    )
    def test_minmax_index_usage_equivalent(self, _name: str, sql: str, _should_use: bool) -> None:
        self._seed()
        with materialized("events", "test_prop", is_nullable=True, create_minmax_index=True) as mat_col:
            self._assert_index_equivalent(sql, self._modifiers(), get_minmax_index_name(mat_col.name))

    def test_non_nullable_minmax_index_usage_equivalent(self) -> None:
        self._seed()
        sql = "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop = 'v'"
        with materialized("events", "test_prop", is_nullable=False, create_minmax_index=True) as mat_col:
            self._assert_index_equivalent(sql, self._modifiers(), get_minmax_index_name(mat_col.name))

    def test_deep_chain_value_read_equivalent(self) -> None:
        # properties.test_prop.x reads the mat value for test_prop, then JSON-extracts the deeper key.
        _create_event(team=self.team, distinct_id="d_obj", event="phys_event", properties={"test_prop": {"x": "deep"}})
        flush_persons_and_events()
        sql = "SELECT distinct_id, properties.test_prop.x FROM events WHERE event = 'phys_event'"
        with materialized("events", "test_prop", is_nullable=True):
            self._assert_results_equivalent(sql, self._modifiers())

    def test_unmaterialized_property_declines_to_blob(self) -> None:
        # No materialized column: the pass declines, the JSONFieldAccess prints as the blob extract (same as master).
        self._seed()
        sql = "SELECT distinct_id, properties.test_prop FROM events WHERE event = 'phys_event'"
        lowered_sql, _ = self._print_lowered(sql, self._modifiers(materialization_mode=MaterializationMode.AUTO))
        self.assertIn("JSONExtractRaw", lowered_sql)
        self._assert_results_equivalent(sql, self._modifiers(materialization_mode=MaterializationMode.AUTO))


class TestAiPropertyPhysicalPass(_PhysicalPassTestBase):
    """$ai_* columns are read without nullIf scrubbing (bloom-filter friendliness) — the pass must reproduce that."""

    def _seed(self) -> None:
        _create_event(team=self.team, distinct_id="t1", event="ai_event", properties={"$ai_trace_id": "trace-1"})
        _create_event(team=self.team, distinct_id="t2", event="ai_event", properties={"$ai_trace_id": "trace-2"})
        _create_event(team=self.team, distinct_id="t3", event="ai_event", properties={})
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("value_read", "SELECT distinct_id, properties.$ai_trace_id FROM events WHERE event = 'ai_event'"),
            (
                "equals",
                "SELECT distinct_id FROM events WHERE event = 'ai_event' AND properties.$ai_trace_id = 'trace-1'",
            ),
        ]
    )
    def test_ai_trace_id_equivalent(self, _name: str, sql: str) -> None:
        self._seed()
        with materialized("events", "$ai_trace_id", is_nullable=False):
            lowered_sql, _ = self._assert_results_equivalent(sql, self._modifiers())
            # No nullIf scrubbing on the $ai value read.
            self.assertNotIn("nullIf", lowered_sql)


class TestDmatPropertyPhysicalPass(_PhysicalPassTestBase):
    """dmat (dynamic materialized) slot columns — read bare (nullable), resolved from the property swapper."""

    def _seed(self) -> None:
        for distinct_id, properties in EVENTS:
            _create_event(team=self.team, distinct_id=distinct_id, event="phys_event", properties=properties)
        flush_persons_and_events()

    def _register_dmat(self) -> None:
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            project_id=self.team.project_id,
            name="test_prop",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=0,
            state=MaterializedColumnSlotState.READY,
        )

    @parameterized.expand(
        [
            ("value_read", "SELECT distinct_id, properties.test_prop FROM events WHERE event = 'phys_event'"),
            ("equals", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop = 'v'"),
            (
                "in_list",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.test_prop IN ('a', 'v')",
            ),
        ]
    )
    def test_dmat_equivalent(self, _name: str, sql: str) -> None:
        self._seed()
        self._register_dmat()
        lowered_sql, _ = self._assert_results_equivalent(sql, self._modifiers())
        self.assertIn("dmat_string_0", lowered_sql)


class TestPropertyGroupPhysicalPass(_PhysicalPassTestBase):
    """Property groups under OPTIMIZED mode — Map access + has() forms."""

    def _seed(self) -> None:
        for distinct_id, properties in EVENTS:
            # `custom_prop` lands in properties_group_custom (no `$`, not ignored).
            mapped = {("custom_prop" if k == "test_prop" else k): v for k, v in properties.items()}
            _create_event(team=self.team, distinct_id=distinct_id, event="phys_event", properties=mapped)
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("value_read", "SELECT distinct_id, properties.custom_prop FROM events WHERE event = 'phys_event'"),
            ("equals", "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.custom_prop = 'v'"),
            (
                "not_equals",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.custom_prop != 'v'",
            ),
            (
                "in_list",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.custom_prop IN ('a', 'v')",
            ),
            (
                "is_set",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.custom_prop IS NOT NULL",
            ),
            (
                "is_not_set",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.custom_prop IS NULL",
            ),
            (
                "eq_empty",
                "SELECT distinct_id FROM events WHERE event = 'phys_event' AND properties.custom_prop = ''",
            ),
        ]
    )
    def test_property_group_optimized_equivalent(self, _name: str, sql: str) -> None:
        self._seed()
        modifiers = self._modifiers(property_groups_mode=PropertyGroupsMode.OPTIMIZED)
        lowered_sql, _ = self._assert_results_equivalent(sql, modifiers)
        self.assertIn("properties_group_custom", lowered_sql)

    def test_property_group_json_has_equivalent(self) -> None:
        self._seed()
        modifiers = self._modifiers(property_groups_mode=PropertyGroupsMode.OPTIMIZED)
        sql = "SELECT distinct_id FROM events WHERE event = 'phys_event' AND JSONHas(properties, 'custom_prop')"
        lowered_sql, _ = self._assert_results_equivalent(sql, modifiers)
        self.assertIn("has(events.properties_group_custom", lowered_sql)


class TestRestrictedPropertyPhysicalPass(_PhysicalPassTestBase):
    """Restricted properties (§8.5): the pass declines the mat substitution; the printer JSONDropKeys-wraps the blob."""

    def _seed(self) -> None:
        _create_event(team=self.team, distinct_id="r1", event="phys_event", properties={"secret": "leak", "ok": "fine"})
        flush_persons_and_events()

    def _print(self, sql: str, *, lower: bool) -> tuple[str, dict[str, Any]]:
        context = self._context(lower=lower, modifiers=self._modifiers())
        context.restricted_properties = {("secret", PropertyDefinition.Type.EVENT)}
        prepared = prepare_ast_for_printing(parse_select(sql), context=context, dialect="clickhouse")
        assert prepared is not None
        node = prepared
        if lower:
            node = clickhouse_physical_passes(lower_property_access(prepared, context), context)
        return print_prepared_ast(node, context=context, dialect="clickhouse"), context.values

    def test_restricted_declines_to_json_drop_keys_blob(self) -> None:
        self._seed()
        with materialized("events", "secret", is_nullable=False):
            sql = "SELECT distinct_id, properties.secret FROM events WHERE event = 'phys_event'"
            master_sql, master_values = self._print(sql, lower=False)
            lowered_sql, lowered_values = self._print(sql, lower=True)

            # Declined: the mat column is NOT read; the blob is JSONDropKeys-wrapped so the restricted value is scrubbed.
            self.assertNotIn("mat_secret", lowered_sql)
            self.assertIn("JSONDropKeys", lowered_sql)
            # Declining means the printer renders both paths identically, so byte-identity proves result-equivalence
            # without executing JSONDropKeys — a ClickHouse function whose name is server-version-specific
            # (JSONDropKeys_v12 on some servers) and orthogonal to the decline behavior this test pins.
            self.assertEqual(master_sql, lowered_sql)
            self.assertEqual(master_values, lowered_values)

    def test_non_restricted_sibling_still_materialized(self) -> None:
        self._seed()
        with materialized("events", "ok", is_nullable=False) as mat_col:
            sql = "SELECT distinct_id, properties.ok FROM events WHERE event = 'phys_event'"
            lowered_sql, _ = self._print(sql, lower=True)
            # A non-restricted sibling still reads its materialized column.
            self.assertIn(mat_col.name, lowered_sql)


class TestPersonPropertyPhysicalPass(_PhysicalPassTestBase):
    """Person properties in both PoE-on-events and PoE-joined modes — the §8.1 ClickHouse-table-name footgun."""

    def _seed(self) -> None:
        _create_person(distinct_ids=["p_has"], team=self.team, properties={"email": "a@b.com"}, immediate=True)
        _create_person(distinct_ids=["p_empty"], team=self.team, properties={"email": ""}, immediate=True)
        _create_person(distinct_ids=["p_none"], team=self.team, properties={"email": None}, immediate=True)
        _create_person(distinct_ids=["p_without"], team=self.team, properties={}, immediate=True)
        for distinct_id in ("p_has", "p_empty", "p_none", "p_without"):
            _create_event(team=self.team, distinct_id=distinct_id, event="person_event")
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("value_read", "SELECT distinct_id, person.properties.email FROM events WHERE event = 'person_event'"),
            (
                "equals",
                "SELECT distinct_id FROM events WHERE event = 'person_event' AND person.properties.email = 'a@b.com'",
            ),
            (
                "is_not_set",
                "SELECT distinct_id FROM events WHERE event = 'person_event' AND person.properties.email IS NULL",
            ),
        ]
    )
    def test_person_on_events_equivalent(self, _name: str, sql: str) -> None:
        self._seed()
        modifiers = self._modifiers(poe_mode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS)
        with self._materialize_person_properties("email", is_nullable=False):
            self._assert_results_equivalent(sql, modifiers)

    @parameterized.expand(
        [
            ("value_read", "SELECT distinct_id, person.properties.email FROM events WHERE event = 'person_event'"),
            (
                "equals",
                "SELECT distinct_id FROM events WHERE event = 'person_event' AND person.properties.email = 'a@b.com'",
            ),
        ]
    )
    def test_person_joined_equivalent(self, _name: str, sql: str) -> None:
        # §8.1: the person mat column registry is keyed by the ClickHouse table name (`person`), not the HogQL
        # `raw_persons`. The inner read inside the person join must resolve `pmat_email`; the outer joined-subquery
        # reference must be left untouched. Equivalence to master proves both.
        self._seed()
        modifiers = self._modifiers(poe_mode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED)
        with materialized("person", "email", is_nullable=False) as mat_col:
            lowered_sql, _ = self._assert_results_equivalent(sql, modifiers)
            # The materialized person column is read inside the join subquery (the §8.1 win).
            self.assertIn(mat_col.name, lowered_sql)


class TestResolveMaterializedPropertySource(_PhysicalPassTestBase):
    """Structural unit test of the §8.1 table-name resolution, independent of printing."""

    def _resolved_source(self, sql: str, modifiers: HogQLQueryModifiers) -> Literal["materialized_column"] | None:
        context = self._context(lower=True, modifiers=modifiers)
        prepared = prepare_ast_for_printing(parse_select(sql), context=context, dialect="clickhouse")
        assert prepared is not None
        lowered = lower_property_access(prepared, context)

        found: list[str] = []

        class _Collect(TraversingVisitor):
            def visit_jsonfield_access(self, node: ast.JSONFieldAccess) -> None:
                property_type = node.type
                if isinstance(property_type, ast.PropertyType):
                    source = resolve_materialized_property_source(property_type.field_type, str(node.keys[0]), context)
                    if source is not None:
                        found.append(source.kind)
                super().visit_jsonfield_access(node)

        _Collect().visit(lowered)
        return found[0] if found else None  # type: ignore[return-value]

    def test_person_joined_resolves_via_clickhouse_table_name(self) -> None:
        # The inner person read resolves a materialized_column only because we key on the ClickHouse name `person`.
        self._seed_person()
        modifiers = self._modifiers(poe_mode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED)
        with materialized("person", "email", is_nullable=False):
            sql = "SELECT person.properties.email FROM events WHERE event = 'person_event'"
            self.assertEqual(self._resolved_source(sql, modifiers), "materialized_column")

    def _seed_person(self) -> None:
        _create_person(distinct_ids=["p_has"], team=self.team, properties={"email": "a@b.com"}, immediate=True)
        _create_event(team=self.team, distinct_id="p_has", event="person_event")
        flush_persons_and_events()
