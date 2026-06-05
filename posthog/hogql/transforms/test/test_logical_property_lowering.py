from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import StringJSONDatabaseField
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.hogql.printer.test.property_corpus import LOGICAL_CASES
from posthog.hogql.printer.test.property_harness import compile_case
from posthog.hogql.printer.test.reachability_oracle import printer_reachability_oracle
from posthog.hogql.visitor import TraversingVisitor


class _CountNodes(TraversingVisitor):
    """Counts JSONFieldAccess nodes and surviving JSON-blob PropertyType Field reads in a prepared tree."""

    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context
        self.json_field_access = 0
        self.blob_property_fields = 0

    def visit_jsonfield_access(self, node: ast.JSONFieldAccess) -> None:
        self.json_field_access += 1
        super().visit_jsonfield_access(node)

    def visit_field(self, node: ast.Field) -> None:
        if isinstance(node.type, ast.PropertyType) and node.type.joined_subquery is None:
            base = node.type.field_type
            if isinstance(base.resolve_database_field(self.context), StringJSONDatabaseField):
                self.blob_property_fields += 1
        super().visit_field(node)


class TestLogicalPropertyLowering(BaseTest):
    def test_lowering_is_byte_identical_to_master_across_dialects(self) -> None:
        # The strangler invariant (§12.8): turning the gate on must not change any printed SQL — logical lowering is a
        # pure refactor. Covers every corpus case on every dialect; pg/duckdb actually lower, ch/hogql are untouched
        # (their pipeline isn't wired to the pass yet), so equality there is trivially true and guards against leakage.
        for case in LOGICAL_CASES:
            for dialect in case.dialects:
                off, _ = compile_case(case.sql, dialect, self.team, case.modifiers)
                on, _ = compile_case(case.sql, dialect, self.team, case.modifiers, lower_property_access=True)
                self.assertEqual(on, off, f"{case.name}/{dialect}: lowering changed output\n off: {off}\n on:  {on}")

    def test_blob_properties_no_longer_reach_printer_for_warehouse_dialects(self) -> None:
        # With lowering on, JSON-blob property reads are JSONFieldAccess before printing, so they never reach the
        # printer's property-decision code — the reachability oracle (the deletion gate) records nothing for them.
        sql = "SELECT properties.foo, properties.a.b.c FROM events WHERE properties.bar = 'x'"
        for dialect in ("postgres", "duckdb"):
            with printer_reachability_oracle() as collector:
                compile_case(sql, dialect, self.team, lower_property_access=True)
            self.assertEqual(
                collector.property_names_for_dialect(dialect),
                set(),
                f"{dialect}: blob properties should be lowered, not reach the printer",
            )

    def test_prepared_tree_has_no_surviving_blob_property(self) -> None:
        for dialect in ("postgres", "duckdb"):
            context = HogQLContext(
                team_id=self.team.pk,
                team=self.team,
                enable_select_queries=True,
                modifiers=create_default_modifiers_for_team(self.team),
                lower_property_access=True,
            )
            prepared = prepare_ast_for_printing(
                parse_select("SELECT properties.foo FROM events WHERE properties.bar = 'x'"),
                context=context,
                dialect=dialect,
            )
            counter = _CountNodes(context)
            counter.visit(prepared)
            self.assertGreaterEqual(counter.json_field_access, 2, f"{dialect}: expected JSONFieldAccess nodes")
            self.assertEqual(counter.blob_property_fields, 0, f"{dialect}: a JSON-blob PropertyType survived lowering")
