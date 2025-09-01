from typing import cast

import pytest
from unittest.mock import MagicMock

from inline_snapshot import snapshot
from parameterized import parameterized

from posthog.schema import (
    ActionsNode,
    DataWarehouseNode,
    EventPropertyFilter,
    EventsNode,
    PersonPropertyFilter,
    PropertyOperator,
)

from posthog.hogql import ast

from posthog.models import Team
from posthog.session_recordings.queries.sub_queries.events_subquery import negative_event_predicates


class TestNegativeEventPredicates:
    @parameterized.expand(
        [
            (
                "empty_entities_list",
                [],
                [],
            ),
            (
                "entity_with_no_properties",
                [EventsNode(event="click", properties=None)],
                [],
            ),
            (
                "entity_with_empty_properties_list",
                [EventsNode(event="click", properties=[])],
                [],
            ),
            (
                "entity_with_positive_operator_only",
                [
                    EventsNode(
                        event="click",
                        properties=[
                            EventPropertyFilter(key="url", operator=PropertyOperator.EXACT, value="example.com")
                        ],
                    )
                ],
                [],
            ),
            (
                "entity_with_multiple_positive_operators",
                [
                    EventsNode(
                        event="click",
                        properties=[
                            EventPropertyFilter(key="url", operator=PropertyOperator.EXACT, value="example.com"),
                            EventPropertyFilter(key="browser", operator=PropertyOperator.ICONTAINS, value="chrome"),
                        ],
                    )
                ],
                [],
            ),
            (
                "entity_with_one_negative_operator_is_not_set",
                [
                    EventsNode(
                        event="click",
                        properties=[EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET)],
                    )
                ],
                1,
            ),
            (
                "entity_with_one_negative_operator_is_not",
                [
                    EventsNode(
                        event="click",
                        properties=[
                            EventPropertyFilter(key="browser", operator=PropertyOperator.IS_NOT, value="safari")
                        ],
                    )
                ],
                1,
            ),
            (
                "entity_with_one_negative_operator_not_regex",
                [
                    EventsNode(
                        event="click",
                        properties=[
                            EventPropertyFilter(key="url", operator=PropertyOperator.NOT_REGEX, value=".*\\.pdf$")
                        ],
                    )
                ],
                1,
            ),
            (
                "entity_with_mixed_positive_and_negative_operators",
                [
                    EventsNode(
                        event="click",
                        properties=[
                            EventPropertyFilter(key="url", operator=PropertyOperator.EXACT, value="example.com"),
                            EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET),
                            EventPropertyFilter(key="browser", operator=PropertyOperator.ICONTAINS, value="chrome"),
                        ],
                    )
                ],
                1,
            ),
            (
                "multiple_entities_with_negative_operators",
                [
                    EventsNode(
                        event="click",
                        properties=[EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET)],
                    ),
                    EventsNode(
                        event="pageview",
                        properties=[
                            EventPropertyFilter(key="browser", operator=PropertyOperator.IS_NOT, value="safari")
                        ],
                    ),
                ],
                2,
            ),
            (
                "entity_with_multiple_negative_operators",
                [
                    EventsNode(
                        event="click",
                        properties=[
                            EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET),
                            EventPropertyFilter(key="browser", operator=PropertyOperator.IS_NOT, value="safari"),
                            EventPropertyFilter(key="url", operator=PropertyOperator.NOT_REGEX, value=".*\\.pdf$"),
                        ],
                    )
                ],
                1,
            ),
            (
                "actions_node_with_negative_operators",
                [
                    ActionsNode(
                        id=1, properties=[EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET)]
                    )
                ],
                1,
            ),
            (
                "person_property_with_negative_operator",
                [
                    EventsNode(
                        event="click",
                        properties=[
                            PersonPropertyFilter(key="email", operator=PropertyOperator.IS_NOT_SET, type="person")
                        ],
                    )
                ],
                1,
            ),
            (
                "multiple_property_types_with_negative_operators",
                [
                    EventsNode(
                        event="click",
                        properties=[
                            EventPropertyFilter(key="browser", operator=PropertyOperator.IS_NOT, value="safari"),
                            PersonPropertyFilter(key="email", operator=PropertyOperator.IS_NOT_SET, type="person"),
                        ],
                    )
                ],
                1,
            ),
            (
                "string_entity_support",
                ["some_event_string"],
                [],
            ),
        ]
    )
    def test_negative_event_predicates_with_various_inputs(self, name, entities, expected_expr_count):
        from posthog.test.base import BaseTest

        team = BaseTest().team

        result = negative_event_predicates(team, entities)

        if isinstance(expected_expr_count, int):
            assert len(result) == expected_expr_count
            # Verify results are ast.Expr instances when we expect expressions
            if expected_expr_count > 0:
                assert all(isinstance(expr, ast.Expr) for expr in result)
        else:
            assert result == expected_expr_count

    def test_negative_event_predicates_with_datawarehouse_node_raises_error(self):
        team = MagicMock(spec=Team)

        node = DataWarehouseNode(
            id="warehouse_1",
            distinct_id_field="user_id",
            id_field="id",
            table_name="warehouse_table",
            timestamp_field="created_at",
            properties=[EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET)],
        )
        entities = cast(list[EventsNode | ActionsNode | DataWarehouseNode | str], [node])

        with pytest.raises(
            NotImplementedError, match="DataWarehouseNode is not supported in negative event predicates"
        ):
            negative_event_predicates(team, entities)

    def test_entity_with_mixed_operators_creates_single_expression(self):
        from posthog.test.base import BaseTest

        team = BaseTest().team

        properties = [
            EventPropertyFilter(key="url", operator=PropertyOperator.EXACT, value="example.com"),
            EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET),
            EventPropertyFilter(key="browser", operator=PropertyOperator.IS_NOT, value="safari"),
        ]

        entity = EventsNode(event="click", properties=properties)
        entities = cast(list[EventsNode | ActionsNode | DataWarehouseNode | str], [entity])

        result = negative_event_predicates(team, entities)

        # Should create exactly one expression for the entity that has negative operators
        assert len(result) == 1
        # The result should be an ast.Expr (And expression combining all the properties)
        assert isinstance(result[0], ast.Expr)

    def test_multiple_negative_operators_create_single_expression_per_entity(self):
        from posthog.test.base import BaseTest

        team = BaseTest().team

        # First entity with multiple negative operators
        entity1 = EventsNode(
            event="click",
            properties=[
                EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET),
                EventPropertyFilter(key="browser", operator=PropertyOperator.IS_NOT, value="safari"),
                EventPropertyFilter(key="url", operator=PropertyOperator.NOT_REGEX, value=".*\\.pdf$"),
            ],
        )

        # Second entity with one negative operator
        entity2 = EventsNode(
            event="pageview",
            properties=[
                EventPropertyFilter(key="referrer", operator=PropertyOperator.IS_NOT_SET),
            ],
        )

        entities = cast(list[EventsNode | ActionsNode | DataWarehouseNode | str], [entity1, entity2])
        result = negative_event_predicates(team, entities)

        # Should create exactly two expressions (one per entity with negative operators)
        assert len(result) == 2
        # Both results should be ast.Expr instances
        assert all(isinstance(expr, ast.Expr) for expr in result)

    def test_negative_predicates_contain_correct_operators(self):
        from posthog.test.base import BaseTest

        team = BaseTest().team

        # Create entity with specific negative operators
        entity = EventsNode(
            event="click",
            properties=[
                EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET),
                EventPropertyFilter(key="browser", operator=PropertyOperator.IS_NOT, value="safari"),
                EventPropertyFilter(
                    key="url", operator=PropertyOperator.EXACT, value="example.com"
                ),  # positive operator
            ],
        )

        entities = cast(list[EventsNode | ActionsNode | DataWarehouseNode | str], [entity])
        result = negative_event_predicates(team, entities)

        assert len(result) == 1
        expr_sql = str(result[0])
        assert expr_sql == snapshot(
            "sql(and(or(equals(events.properties.user_id, NULL), not(JSONHas(events.properties, 'user_id'))), notEquals(events.properties.browser, 'safari'), equals(events.properties.url, 'example.com')))"
        )

    def test_negative_predicates_exclude_positive_operators_from_logic(self):
        from posthog.test.base import BaseTest

        team = BaseTest().team

        # Create two entities - one with only positive operators, one with negative
        entity_positive = EventsNode(
            event="click",
            properties=[
                EventPropertyFilter(key="url", operator=PropertyOperator.EXACT, value="example.com"),
                EventPropertyFilter(key="browser", operator=PropertyOperator.ICONTAINS, value="chrome"),
            ],
        )

        entity_negative = EventsNode(
            event="pageview",
            properties=[
                EventPropertyFilter(key="user_id", operator=PropertyOperator.IS_NOT_SET),
            ],
        )

        entities = cast(list[EventsNode | ActionsNode | DataWarehouseNode | str], [entity_positive, entity_negative])
        result = negative_event_predicates(team, entities)

        # Should only return expression for entity with negative operators
        assert len(result) == 1, "Should only create expressions for entities with negative operators"
        self._compare_with_snapshot(
            result, "sql(or(equals(events.properties.user_id, NULL), not(JSONHas(events.properties, 'user_id'))))"
        )

    def test_is_not_set_operator_generates_proper_predicate(self):
        from posthog.test.base import BaseTest

        team = BaseTest().team

        entity = EventsNode(
            event="click",
            properties=[
                EventPropertyFilter(key="user_email", operator=PropertyOperator.IS_NOT_SET),
            ],
        )

        entities = cast(list[EventsNode | ActionsNode | DataWarehouseNode | str], [entity])
        result = negative_event_predicates(team, entities)

        self._compare_with_snapshot(
            result, "sql(or(equals(events.properties.user_email, NULL), not(JSONHas(events.properties, 'user_email'))))"
        )

    def test_is_not_operator_with_value_generates_proper_predicate(self):
        from posthog.test.base import BaseTest

        team = BaseTest().team

        entity = EventsNode(
            event="click",
            properties=[
                EventPropertyFilter(key="browser", operator=PropertyOperator.IS_NOT, value="safari"),
            ],
        )

        entities = cast(list[EventsNode | ActionsNode | DataWarehouseNode | str], [entity])
        result = negative_event_predicates(team, entities)

        self._compare_with_snapshot(result, "sql(notEquals(events.properties.browser, 'safari'))")

    def test_not_regex_operator_generates_proper_predicate(self):
        from posthog.test.base import BaseTest

        team = BaseTest().team

        entity = EventsNode(
            event="click",
            properties=[
                EventPropertyFilter(key="url", operator=PropertyOperator.NOT_REGEX, value=".*\\.pdf$"),
            ],
        )

        entities = cast(list[EventsNode | ActionsNode | DataWarehouseNode | str], [entity])
        result = negative_event_predicates(team, entities)

        self._compare_with_snapshot(
            result, "sql(ifNull(not(match(toString(events.properties.url), '.*\\\\.pdf$')), 1))"
        )

    @staticmethod
    def _compare_with_snapshot(result: list[ast.Expr], expected: str) -> None:
        assert len(result) == 1
        expr_sql = str(result[0])
        assert expr_sql == expected
