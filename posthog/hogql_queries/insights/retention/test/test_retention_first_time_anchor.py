from typing import Any

from unittest import TestCase
from unittest.mock import MagicMock

from posthog.schema import RetentionEntity

from posthog.hogql import ast

from posthog.hogql_queries.insights.retention.retention_base_query_fixed import RetentionFixedIntervalBaseQueryBuilder


def _collect_field_chains(node: Any) -> list[list[str | int]]:
    chains: list[list[str | int]] = []

    def visit(value: Any) -> None:
        if isinstance(value, ast.Field):
            chains.append(value.chain)
        if hasattr(value, "__dataclass_fields__"):
            for field_name in value.__dataclass_fields__:
                visit(getattr(value, field_name))
        elif isinstance(value, list | tuple):
            for item in value:
                visit(item)

    visit(node)
    return chains


def _collect_constants(node: Any) -> list[Any]:
    consts: list[Any] = []

    def visit(value: Any) -> None:
        if isinstance(value, ast.Constant):
            consts.append(value.value)
        if hasattr(value, "__dataclass_fields__"):
            for field_name in value.__dataclass_fields__:
                visit(getattr(value, field_name))
        elif isinstance(value, list | tuple):
            for item in value:
                visit(item)

    visit(node)
    return consts


def _collect_min_if_predicates(node: Any) -> list[ast.Expr]:
    """Collect the second argument of every `minIf(...)` call in the AST."""
    predicates: list[ast.Expr] = []

    def visit(value: Any) -> None:
        if isinstance(value, ast.Call) and value.name == "minIf" and len(value.args) >= 2:
            predicates.append(value.args[1])
        if hasattr(value, "__dataclass_fields__"):
            for field_name in value.__dataclass_fields__:
                visit(getattr(value, field_name))
        elif isinstance(value, list | tuple):
            for item in value:
                visit(item)

    visit(node)
    return predicates


def _make_builder(
    *,
    start_event: RetentionEntity,
    is_first_ever: bool = False,
    is_first_matching: bool = False,
) -> RetentionFixedIntervalBaseQueryBuilder:
    """Build a RetentionFixedIntervalBaseQueryBuilder with a stubbed runner.

    The helpers under test only need `team`, `start_event`, and the two first-occurrence
    flags from the runner, so we don't need a real Django Team or a live ClickHouse stack.
    """
    runner = MagicMock()
    runner.team = MagicMock(pk=1)
    runner.start_event = start_event
    runner.is_first_ever_occurrence = is_first_ever
    runner.is_first_occurrence_matching_filters = is_first_matching
    return RetentionFixedIntervalBaseQueryBuilder(runner)


class TestFirstTimeAnchorExpr(TestCase):
    def test_events_entity_first_ever_references_events_timestamp(self) -> None:
        entity = RetentionEntity(id="$user_signed_up", name="$user_signed_up", type="events")
        builder = _make_builder(start_event=entity, is_first_ever=True)

        expr = builder.get_first_time_anchor_expr(entity)

        chains = _collect_field_chains(expr)
        self.assertIn(["events", "timestamp"], chains)

        constants = _collect_constants(expr)
        self.assertIn("$user_signed_up", constants)

    def test_events_entity_first_time_matching_filters_uses_events_predicate(self) -> None:
        entity = RetentionEntity(
            id="$user_signed_up",
            name="$user_signed_up",
            type="events",
            properties=[
                {"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"},
            ],
        )
        builder = _make_builder(start_event=entity, is_first_matching=True)

        expr = builder.get_first_time_anchor_expr(entity)

        chains = _collect_field_chains(expr)
        self.assertIn(["events", "timestamp"], chains)

        constants = _collect_constants(expr)
        self.assertIn("$user_signed_up", constants)
        self.assertIn("Chrome", constants)

    def test_dwh_entity_with_properties_uses_property_filter_predicate(self) -> None:
        entity = RetentionEntity(
            type="data_warehouse",
            table_name="warehouse_activity",
            timestamp_field="occurred_at",
            aggregation_target_field="person_id",
            id="warehouse_activity",
            name="warehouse_activity",
            properties=[
                {"key": "event_type", "value": "signup", "operator": "exact", "type": "data_warehouse"},
            ],
        )
        builder = _make_builder(start_event=entity, is_first_matching=True)

        expr = builder.get_first_time_anchor_expr(entity)

        chains = _collect_field_chains(expr)
        self.assertIn(["warehouse_activity", "occurred_at"], chains)
        self.assertNotIn(["events", "timestamp"], chains)

        # property filter value should appear in the predicate (built via property_to_expr)
        constants = _collect_constants(expr)
        self.assertIn("signup", constants)

    def test_dwh_entity_without_properties_uses_truthy_constant_predicate(self) -> None:
        entity = RetentionEntity(
            type="data_warehouse",
            table_name="warehouse_activity",
            timestamp_field="occurred_at",
            aggregation_target_field="person_id",
            id="warehouse_activity",
            name="warehouse_activity",
            properties=[],
        )
        # Use first-ever so both no-props and with-props minIf predicates are surfaced.
        builder = _make_builder(start_event=entity, is_first_ever=True)

        expr = builder.get_first_time_anchor_expr(entity)

        chains = _collect_field_chains(expr)
        self.assertIn(["warehouse_activity", "occurred_at"], chains)
        self.assertNotIn(["events", "timestamp"], chains)

        # Every minIf predicate must be a truthy constant — the with-props and no-props branches
        # both collapse to True for a DWH entity without properties.
        # (parse_expr substitution shares nodes so the walker can see more than 2.)
        min_if_predicates = _collect_min_if_predicates(expr)
        self.assertGreaterEqual(len(min_if_predicates), 2)
        for pred in min_if_predicates:
            self.assertIsInstance(pred, ast.Constant)
            self.assertTrue(pred.value)  # type: ignore[union-attr]
