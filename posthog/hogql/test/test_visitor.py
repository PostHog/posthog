from posthog.hogql import ast
from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import CloningVisitor, Visitor, TraversingVisitor
from posthog.test.base import BaseTest


class TestVisitor(BaseTest):
    def test_visitor_pattern(self):
        class ConstantVisitor(CloningVisitor):
            def __init__(self):
                super().__init__()
                self.constants = []
                self.fields = []
                self.operations = []

            def visit_constant(self, node):
                self.constants.append(node.value)
                return super().visit_constant(node)

            def visit_field(self, node):
                self.fields.append(node.chain)
                return super().visit_field(node)

            def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
                self.operations.append(node.op)
                return super().visit_arithmetic_operation(node)

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
                            op=ast.CompareOperationOp.Eq,
                            left=ast.Field(chain=["a"]),
                            right=ast.Constant(value=1),
                        ),
                        ast.ArithmeticOperation(
                            op=ast.ArithmeticOperationOp.Add,
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
                ast.Alias(
                    expr=ast.SelectQuery(select=[ast.Field(chain=["timestamp"])]),
                    alias="f",
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["a"])],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["b"]),
                        table_final=True,
                        alias="c",
                        next_join=ast.JoinExpr(
                            join_type="INNER",
                            table=ast.Field(chain=["f"]),
                            constraint=ast.JoinConstraint(
                                expr=ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["d"]),
                                    right=ast.Field(chain=["e"]),
                                )
                            ),
                        ),
                        sample=ast.SampleExpr(
                            sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=2)),
                            offset_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=2)),
                        ),
                    ),
                    where=ast.Constant(value=True),
                    prewhere=ast.Constant(value=True),
                    having=ast.Constant(value=True),
                    group_by=[ast.Constant(value=True)],
                    order_by=[ast.OrderExpr(expr=ast.Constant(value=True), order="DESC")],
                    limit=ast.Constant(value=1),
                    limit_by=[ast.Constant(value=True)],
                    limit_with_ties=True,
                    offset=ast.Or(exprs=[ast.Constant(value=1)]),
                    distinct=True,
                ),
            ]
        )
        self.assertEqual(node, CloningVisitor().visit(node))

    def test_unknown_visitor(self):
        class UnknownVisitor(Visitor):
            def visit_unknown(self, node):
                return "!!"

            def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
                return self.visit(node.left) + node.op + self.visit(node.right)

        self.assertEqual(UnknownVisitor().visit(parse_expr("1 + 3 / 'asd2'")), "!!+!!/!!")

    def test_unknown_error_visitor(self):
        class UnknownNotDefinedVisitor(Visitor):
            def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
                return self.visit(node.left) + node.op + self.visit(node.right)

        with self.assertRaises(HogQLException) as e:
            UnknownNotDefinedVisitor().visit(parse_expr("1 + 3 / 'asd2'"))
        self.assertEqual(str(e.exception), "Visitor has no method visit_constant")

    def test_hogql_exception_start_end(self):
        class EternalVisitor(TraversingVisitor):
            def visit_constant(self, node: ast.Constant):
                if node.value == 616:
                    raise HogQLException("You tried accessing a forbidden number, perish!")

        with self.assertRaises(HogQLException) as e:
            EternalVisitor().visit(parse_expr("1 + 616 / 'asd2'"))
        self.assertEqual(str(e.exception), "You tried accessing a forbidden number, perish!")
        self.assertEqual(e.exception.start, 4)
        self.assertEqual(e.exception.end, 7)
