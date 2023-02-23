from typing import List, Union, cast

from posthog.constants import PropertyOperatorType
from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.models import Property
from posthog.models.property import PropertyGroup
from posthog.schema import HogQLPropertyFilter
from posthog.test.base import BaseTest


class TestProperty(BaseTest):
    def test_property_to_expr_hogql(self):
        self.assertEqual(property_to_expr({"type": "hogql", "key": "1"}), ast.Constant(value=1))
        self.assertEqual(property_to_expr(Property(type="hogql", key="1")), ast.Constant(value=1))
        self.assertEqual(property_to_expr(HogQLPropertyFilter(type="hogql", key="1")), ast.Constant(value=1))

    def test_property_to_expr_event(self):
        self.assertEqual(
            property_to_expr({"key": "a", "value": "b"}),
            ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=ast.Field(chain=["properties", "a"]),
                right=ast.Constant(value="b"),
            ),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b"}),
            ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=ast.Field(chain=["properties", "a"]),
                right=ast.Constant(value="b"),
            ),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "exact"}),
            ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=ast.Field(chain=["properties", "a"]),
                right=ast.Constant(value="b"),
            ),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "is_not"}),
            ast.CompareOperation(
                op=ast.CompareOperationType.NotEq,
                left=ast.Field(chain=["properties", "a"]),
                right=ast.Constant(value="b"),
            ),
        )
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "3", "operator": "lt"}),
            ast.CompareOperation(
                op=ast.CompareOperationType.Lt,
                left=ast.Field(chain=["properties", "a"]),
                right=ast.Constant(value="3"),
            ),
        )

    def test_property_to_expr_feature(self):
        self.assertEqual(
            property_to_expr({"type": "event", "key": "a", "value": "b", "operator": "exact"}),
            ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=ast.Field(chain=["properties", "a"]),
                right=ast.Constant(value="b"),
            ),
        )

    def test_property_to_expr_person(self):
        self.assertEqual(
            property_to_expr({"type": "person", "key": "a", "value": "b", "operator": "exact"}),
            ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=ast.Field(chain=["person", "properties", "a"]),
                right=ast.Constant(value="b"),
            ),
        )

    def test_property_groups(self):
        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="a", value="b", operator="exact"),
                        Property(type="event", key="e", value="b", operator="exact"),
                    ],
                )
            ),
            ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationType.Eq,
                        left=ast.Field(chain=["person", "properties", "a"]),
                        right=ast.Constant(value="b"),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationType.Eq,
                        left=ast.Field(chain=["properties", "e"]),
                        right=ast.Constant(value="b"),
                    ),
                ]
            ),
        )

        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.OR,
                    values=[
                        Property(type="person", key="a", value="b", operator="exact"),
                        Property(type="event", key="e", value="b", operator="exact"),
                    ],
                )
            ),
            ast.Or(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationType.Eq,
                        left=ast.Field(chain=["person", "properties", "a"]),
                        right=ast.Constant(value="b"),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationType.Eq,
                        left=ast.Field(chain=["properties", "e"]),
                        right=ast.Constant(value="b"),
                    ),
                ]
            ),
        )

    def test_property_groups_single(self):
        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(type="person", key="a", value="b", operator="exact"),
                    ],
                )
            ),
            ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=ast.Field(chain=["person", "properties", "a"]),
                right=ast.Constant(value="b"),
            ),
        )

        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.OR, values=[Property(type="event", key="e", value="b", operator="exact")]
                )
            ),
            ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=ast.Field(chain=["properties", "e"]),
                right=ast.Constant(value="b"),
            ),
        )

    def test_property_groups_combined(self):
        self.assertEqual(
            property_to_expr(
                PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=cast(
                        Union[List[Property], List[PropertyGroup]],
                        [
                            Property(type="person", key="a", value="b", operator="exact"),
                            PropertyGroup(
                                type=PropertyOperatorType.OR,
                                values=[
                                    Property(type="person", key="a", value="b", operator="exact"),
                                    Property(type="event", key="e", value="b", operator="exact"),
                                ],
                            ),
                        ],
                    ),
                )
            ),
            ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationType.Eq,
                        left=ast.Field(chain=["person", "properties", "a"]),
                        right=ast.Constant(value="b"),
                    ),
                    ast.Or(
                        exprs=[
                            ast.CompareOperation(
                                op=ast.CompareOperationType.Eq,
                                left=ast.Field(chain=["person", "properties", "a"]),
                                right=ast.Constant(value="b"),
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationType.Eq,
                                left=ast.Field(chain=["properties", "e"]),
                                right=ast.Constant(value="b"),
                            ),
                        ]
                    ),
                ]
            ),
        )
