from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from unittest import TestCase
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import RetentionEntity

from posthog.hogql import ast

from posthog.hogql_queries.insights.retention.retention_base_query_fixed import RetentionFixedIntervalBaseQueryBuilder
from posthog.hogql_queries.insights.retention.retention_query_runner import RetentionQueryRunner


def _walk_ast(node: Any, visit: Callable[[Any], None]) -> None:
    """Recursively visit every value in an AST tree (dataclass fields + list/tuple items)."""

    def walk(value: Any) -> None:
        visit(value)
        if hasattr(value, "__dataclass_fields__"):
            for field_name in value.__dataclass_fields__:
                walk(getattr(value, field_name))
        elif isinstance(value, list | tuple):
            for item in value:
                walk(item)

    walk(node)


def _collect_field_chains(node: Any) -> list[list[str | int]]:
    chains: list[list[str | int]] = []

    def visit(value: Any) -> None:
        if isinstance(value, ast.Field):
            chains.append(value.chain)

    _walk_ast(node, visit)
    return chains


def _collect_constants(node: Any) -> list[Any]:
    consts: list[Any] = []

    def visit(value: Any) -> None:
        if isinstance(value, ast.Constant):
            consts.append(value.value)

    _walk_ast(node, visit)
    return consts


def _collect_min_if_predicates(node: Any) -> list[ast.Expr]:
    """Collect the second argument of every `minIf(...)` call in the AST."""
    predicates: list[ast.Expr] = []

    def visit(value: Any) -> None:
        if isinstance(value, ast.Call) and value.name == "minIf" and len(value.args) >= 2:
            predicates.append(value.args[1])

    _walk_ast(node, visit)
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


_EVENTS_FIRST_EVER_ENTITY = RetentionEntity(id="$user_signed_up", name="$user_signed_up", type="events")
_EVENTS_FIRST_MATCHING_ENTITY = RetentionEntity(
    id="$user_signed_up",
    name="$user_signed_up",
    type="events",
    properties=[
        {"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"},
    ],
)
_DWH_WITH_PROPS_ENTITY = RetentionEntity(
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
_DWH_NO_PROPS_ENTITY = RetentionEntity(
    type="data_warehouse",
    table_name="warehouse_activity",
    timestamp_field="occurred_at",
    aggregation_target_field="person_id",
    id="warehouse_activity",
    name="warehouse_activity",
    properties=[],
)


class TestFirstTimeAnchorExpr(TestCase):
    @parameterized.expand(
        [
            (
                "events_first_ever_references_events_timestamp",
                _EVENTS_FIRST_EVER_ENTITY,
                True,  # is_first_ever
                False,  # is_first_matching
                [["events", "timestamp"]],  # expected_chains
                [],  # unexpected_chains
                ["$user_signed_up"],  # expected_constants
                False,  # assert_min_if_predicates_truthy
            ),
            (
                "events_first_time_matching_filters_uses_events_predicate",
                _EVENTS_FIRST_MATCHING_ENTITY,
                False,
                True,
                [["events", "timestamp"]],
                [],
                ["$user_signed_up", "Chrome"],
                False,
            ),
            (
                "dwh_with_properties_uses_property_filter_predicate",
                _DWH_WITH_PROPS_ENTITY,
                False,
                True,
                [["warehouse_activity", "occurred_at"]],
                [["events", "timestamp"]],
                ["signup"],
                False,
            ),
            (
                # First-ever so both no-props and with-props minIf predicates are surfaced.
                "dwh_without_properties_uses_truthy_constant_predicate",
                _DWH_NO_PROPS_ENTITY,
                True,
                False,
                [["warehouse_activity", "occurred_at"]],
                [["events", "timestamp"]],
                [],
                True,
            ),
        ]
    )
    def test_get_first_time_anchor_expr(
        self,
        _name: str,
        entity: RetentionEntity,
        is_first_ever: bool,
        is_first_matching: bool,
        expected_chains: list[list[str | int]],
        unexpected_chains: list[list[str | int]],
        expected_constants: list[Any],
        assert_min_if_predicates_truthy: bool,
    ) -> None:
        builder = _make_builder(
            start_event=entity,
            is_first_ever=is_first_ever,
            is_first_matching=is_first_matching,
        )

        expr = builder.get_first_time_anchor_expr(entity)

        chains = _collect_field_chains(expr)
        for chain in expected_chains:
            self.assertIn(chain, chains)
        for chain in unexpected_chains:
            self.assertNotIn(chain, chains)

        constants = _collect_constants(expr)
        for constant in expected_constants:
            self.assertIn(constant, constants)

        if assert_min_if_predicates_truthy:
            # Every minIf predicate must be a truthy constant — the with-props and no-props branches
            # both collapse to True for a DWH entity without properties.
            # (parse_expr substitution shares nodes so the walker can see more than 2.)
            min_if_predicates = _collect_min_if_predicates(expr)
            self.assertGreaterEqual(len(min_if_predicates), 2)
            for pred in min_if_predicates:
                self.assertIsInstance(pred, ast.Constant)
                assert isinstance(pred, ast.Constant)  # narrow for mypy
                self.assertTrue(pred.value)


# Pull the underlying function out of the cached_property descriptor so we can call it
# against a lightweight stub instead of building a full RetentionQueryRunner.
# Note: posthog's cached_property is `property(lru_cache(...)(func))`; .fget.__wrapped__ unwraps both.
_start_and_return_entities_are_same = RetentionQueryRunner.start_and_return_entities_are_same.fget.__wrapped__  # type: ignore[attr-defined,union-attr]


class TestStartAndReturnEntitiesAreSame(TestCase):
    @parameterized.expand(
        [
            (
                "identical_events_entity",
                RetentionEntity(id="$pageview", type="events"),
                RetentionEntity(id="$pageview", type="events"),
                True,
            ),
            (
                "different_id",
                RetentionEntity(id="$pageview", type="events"),
                RetentionEntity(id="$screen", type="events"),
                False,
            ),
            (
                "different_type",
                RetentionEntity(id="1", type="events"),
                RetentionEntity(id="1", type="actions"),
                False,
            ),
            (
                "differing_properties",
                RetentionEntity(
                    id="$pageview",
                    type="events",
                    properties=[{"key": "browser", "value": "Chrome", "operator": "exact", "type": "event"}],
                ),
                RetentionEntity(id="$pageview", type="events", properties=[]),
                False,
            ),
            (
                "different_property_order",
                # Order-sensitive — list equality is element-wise, so reordering counts as different.
                # Documenting current behaviour so a future change doesn't silently widen this.
                RetentionEntity(
                    id="$pageview",
                    type="events",
                    properties=[
                        {"key": "browser", "value": "Chrome", "operator": "exact", "type": "event"},
                        {"key": "os", "value": "Mac", "operator": "exact", "type": "event"},
                    ],
                ),
                RetentionEntity(
                    id="$pageview",
                    type="events",
                    properties=[
                        {"key": "os", "value": "Mac", "operator": "exact", "type": "event"},
                        {"key": "browser", "value": "Chrome", "operator": "exact", "type": "event"},
                    ],
                ),
                False,
            ),
            (
                "dwh_same_table_and_timestamp_differing_aggregation_target",
                # aggregation_target_field is intentionally NOT in the identity set — the WHERE
                # predicate doesn't depend on it. Pinning the current behaviour so a future
                # widening of the field set is a conscious choice.
                RetentionEntity(
                    type="data_warehouse",
                    table_name="warehouse_activity",
                    timestamp_field="occurred_at",
                    aggregation_target_field="person_id",
                    id="warehouse_activity",
                ),
                RetentionEntity(
                    type="data_warehouse",
                    table_name="warehouse_activity",
                    timestamp_field="occurred_at",
                    aggregation_target_field="account_id",
                    id="warehouse_activity",
                ),
                True,
            ),
            (
                "dwh_different_table_name",
                RetentionEntity(
                    type="data_warehouse",
                    table_name="a",
                    timestamp_field="ts",
                    aggregation_target_field="person_id",
                    id="a",
                ),
                RetentionEntity(
                    type="data_warehouse",
                    table_name="b",
                    timestamp_field="ts",
                    aggregation_target_field="person_id",
                    id="b",
                ),
                False,
            ),
        ]
    )
    def test_start_and_return_entities_are_same(
        self,
        _name: str,
        start_event: RetentionEntity,
        return_event: RetentionEntity,
        expected: bool,
    ) -> None:
        stub = SimpleNamespace(start_event=start_event, return_event=return_event)
        self.assertEqual(_start_and_return_entities_are_same(stub), expected)
