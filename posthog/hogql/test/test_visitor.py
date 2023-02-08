from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import EverythingVisitor
from posthog.test.base import BaseTest


class ConstantVisitor(EverythingVisitor):
    def __init__(self):
        self.constants = []
        self.fields = []
        self.operations = []

    def visit_constant(self, node):
        self.constants.append(node.value)

    def visit_field(self, node):
        self.fields.append(node.chain)

    def visit_binary_operation(self, binary_operation: ast.BinaryOperation):
        self.operations.append(binary_operation.op)
        super().visit_binary_operation(binary_operation)


class TestVisitor(BaseTest):
    def test_visitor_pattern(self):
        visitor = ConstantVisitor()
        visitor.visit(ast.Constant(value="asd"))
        self.assertEqual(visitor.constants, ["asd"])

        visitor.visit(parse_expr("1 + 3 / 'asd2'"))
        self.assertEqual(visitor.operations, ["+", "/"])
        self.assertEqual(visitor.constants, ["asd", 1, 3, "asd2"])

    def test_everything_visitor(self):
        node = ast.Or(
            exprs=[
                ast.And(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationType.Eq,
                            left=ast.Field(chain=["a"]),
                            right=ast.Constant(value=1),
                        ),
                        ast.BinaryOperation(
                            op=ast.BinaryOperationType.Add,
                            left=ast.Field(chain=["b"]),
                            right=ast.Constant(value=2),
                        ),
                    ]
                ),
                ast.Not(
                    expr=ast.Call(
                        name="c",
                        args=[
                            ast.Alias(
                                alias="d",
                                expr=ast.Placeholder(field="e"),
                            ),
                            ast.OrderExpr(
                                expr=ast.Field(chain=["c"]),
                                order="DESC",
                            ),
                        ],
                    )
                ),
            ]
        )
        self.assertEqual(node, EverythingVisitor().visit(node))
