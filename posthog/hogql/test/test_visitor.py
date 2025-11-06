from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.ast import HogQLXAttribute, HogQLXTag, UUIDType
from posthog.hogql.errors import InternalHogQLError
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, Visitor


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
                                expr=ast.Placeholder(expr=ast.Field(chain=["e"])),
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
                                ),
                                constraint_type="ON",
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
                    limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Constant(value=True)]),
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

        with self.assertRaises(InternalHogQLError) as e:
            UnknownNotDefinedVisitor().visit(parse_expr("1 + 3 / 'asd2'"))
        self.assertEqual(str(e.exception), "UnknownNotDefinedVisitor has no method visit_constant")

    def test_hogql_exception_start_end(self):
        class EternalVisitor(TraversingVisitor):
            def visit_constant(self, node: ast.Constant):
                if node.value == 616:
                    raise InternalHogQLError("You tried accessing a forbidden number, perish!")

        with self.assertRaises(InternalHogQLError) as e:
            EternalVisitor().visit(parse_expr("1 + 616 / 'asd2'"))
        self.assertEqual(str(e.exception), "You tried accessing a forbidden number, perish!")
        self.assertEqual(e.exception.start, 4)
        self.assertEqual(e.exception.end, 7)

    def test_hogql_visitor_naming_exceptions(self):
        class NamingCheck(Visitor):
            def visit_uuid_type(self, node: ast.Constant):
                return "visit_uuid_type"

            def visit_hogqlx_tag(self, node: ast.Constant):
                return "visit_hogqlx_tag"

            def visit_hogqlx_attribute(self, node: ast.Constant):
                return "visit_hogqlx_attribute"

            def visit_string_json_type(self, node: ast.Constant):
                return "visit_string_json_type"

        assert NamingCheck().visit(UUIDType()) == "visit_uuid_type"
        assert NamingCheck().visit(HogQLXAttribute(name="a", value="a")) == "visit_hogqlx_attribute"
        assert NamingCheck().visit(HogQLXTag(kind="", attributes=[])) == "visit_hogqlx_tag"
        assert NamingCheck().visit(ast.StringJSONType()) == "visit_string_json_type"

    def test_visit_interval_type(self):
        # Just ensure ``IntervalType`` can be visited without throwing ``NotImplementedError``
        TraversingVisitor().visit(ast.IntervalType())
