from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.ast import AST_CLASSES, HogQLXAttribute, HogQLXTag, UUIDType
from posthog.hogql.base import _VISIT_NAME_REPLACEMENTS, AST, camel_case_pattern
from posthog.hogql.errors import (
    InternalHogQLError,
    NotImplementedError as HogQLNotImplementedError,
    QueryError,
)
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, Visitor, clone_expr


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

    def test_visit_aggregate_state_type_visits_wrapped_type(self):
        class TypeCollector(TraversingVisitor):
            def __init__(self):
                self.visited_types: list[str] = []

            def visit_string_type(self, node: ast.StringType):
                self.visited_types.append(node.print_type())

        visitor = TypeCollector()
        visitor.visit(ast.AggregateStateType(wrapped_type=ast.StringType()))

        assert visitor.visited_types == ["String"]

    def test_cached_visit_method_name_matches_legacy_algorithm(self):
        def legacy(cls_name: str) -> str:
            name = camel_case_pattern.sub("_", cls_name).lower()
            for old, new in _VISIT_NAME_REPLACEMENTS.items():
                name = name.replace(old, new)
            return f"visit_{name}"

        def all_subclasses(cls):
            seen: set[type] = set()
            stack = [cls]
            while stack:
                c = stack.pop()
                for sub in c.__subclasses__():
                    if sub not in seen:
                        seen.add(sub)
                        stack.append(sub)
            return seen

        subclasses = all_subclasses(AST)
        # `__subclasses__()` also returns pre-`@dataclass(slots=True)` ghost
        # classes, so `subclasses` is always a superset of `AST_CLASSES`.
        assert len(subclasses) >= len(AST_CLASSES), (
            f"expected at least {len(AST_CLASSES)} AST subclasses, found {len(subclasses)}"
        )
        mismatches = [
            (cls.__name__, cls._visit_method_name, legacy(cls.__name__))
            for cls in subclasses
            if cls._visit_method_name != legacy(cls.__name__)
        ]
        assert not mismatches, f"_visit_method_name mismatches: {mismatches}"

    def test_accept_falls_back_to_visit_unknown(self):
        class FallbackVisitor(Visitor):
            def visit_unknown(self, node):
                return f"unknown:{node.__class__.__name__}"

        assert FallbackVisitor().visit(ast.Field(chain=["x"])) == "unknown:Field"

    def test_accept_raises_when_no_visit_method_and_no_unknown(self):
        class EmptyVisitor(Visitor):
            pass

        with self.assertRaises(HogQLNotImplementedError) as ctx:
            EmptyVisitor().visit(ast.Field(chain=["x"]))
        self.assertIn("visit_field", str(ctx.exception))

    @parameterized.expand(
        [
            ("asc", "ASC"),
            ("desc", "DESC"),
        ]
    )
    def test_order_expr_accepts_valid_directions(self, _name: str, direction: str):
        expr = ast.OrderExpr(expr=ast.Field(chain=["col"]), order=direction)  # type: ignore[arg-type]
        self.assertEqual(expr.order, direction)

    @parameterized.expand(
        [
            ("injection", "DESC; SELECT 1"),
            ("empty", ""),
            ("lowercase", "asc"),
        ]
    )
    def test_order_expr_rejects_invalid_direction(self, _name: str, direction: str):
        with self.assertRaises(ValueError):
            ast.OrderExpr(expr=ast.Field(chain=["col"]), order=direction)  # type: ignore[arg-type]

    def test_deeply_nested_clone_raises_query_error_not_recursion_error(self):
        # clone_expr never passes through resolve_types, so guarding only that boundary would leave
        # this path (and the direct Resolver.visit in query.py) crashing with a raw RecursionError.
        # The guard lives on the shared Visitor.visit, so a deep clone surfaces a clean QueryError.
        node: ast.Expr = ast.Constant(value=1)
        for _ in range(2000):
            node = ast.Not(expr=node)

        with self.assertRaises(QueryError) as context:
            clone_expr(node)
        self.assertEqual(str(context.exception), "Query is too deeply nested to process. Please simplify it.")
