from ._test_parser import parser_test_factory
from posthog.hogql.ast import (
    VariableDeclaration,
    Constant,
    ArithmeticOperation,
    Field,
    ExprStatement,
    Call,
    ArithmeticOperationOp,
)

from posthog.hogql.parser import parse_program
from posthog.hogql import ast


class TestParserPython(parser_test_factory("python")):
    def _program(self, program: str, placeholders: dict[str, ast.Expr] | None = None) -> list[ast.Expr]:
        return parse_program(program, placeholders=placeholders, start=None)

    def test_program(self):
        code = "var a := '123'; var b := a - 2; print(b);"
        program = self._program(code)
        expected = [
            VariableDeclaration(
                start=None, end=None, type=None, name="a", expr=Constant(start=None, end=None, type=None, value="123")
            ),
            VariableDeclaration(
                start=None,
                end=None,
                type=None,
                name="b",
                expr=ArithmeticOperation(
                    start=None,
                    end=None,
                    type=None,
                    left=Field(start=None, end=None, type=None, chain=["a"]),
                    right=Constant(start=None, end=None, type=None, value=2),
                    op=ArithmeticOperationOp.Sub,
                ),
            ),
            ExprStatement(
                start=None,
                end=None,
                type=None,
                expr=Call(
                    start=None,
                    end=None,
                    type=None,
                    name="print",
                    args=[Field(start=None, end=None, type=None, chain=["b"])],
                    params=None,
                    distinct=False,
                ),
            ),
        ]
        self.assertEqual(program, expected)
