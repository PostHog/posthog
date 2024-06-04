from ._test_parser import parser_test_factory
from posthog.hogql.ast import (
    VariableAssignment,
    Constant,
    ArithmeticOperation,
    Field,
    ExprStatement,
    Call,
    ArithmeticOperationOp,
    CompareOperationOp,
    CompareOperation,
    JoinExpr,
    SelectQuery,
    Program,
    IfStatement,
    Block,
    WhileStatement,
    Function,
    Array,
    Dict,
    VariableDeclaration,
)

from posthog.hogql.parser import parse_program
from posthog.hogql import ast


class TestParserPython(parser_test_factory("python")):
    def _program(self, program: str, placeholders: dict[str, ast.Expr] | None = None) -> ast.Program:
        return parse_program(program, placeholders=placeholders, start=None)

    def test_program_variable_declarations(self):
        code = "var a := '123'; var b := a - 2; print(b);"
        program = self._program(code)

        expected = Program(
            declarations=[
                VariableDeclaration(name="a", expr=Constant(type=None, value="123")),
                VariableDeclaration(
                    name="b",
                    expr=ArithmeticOperation(
                        type=None,
                        left=Field(type=None, chain=["a"]),
                        right=Constant(type=None, value=2),
                        op=ArithmeticOperationOp.Sub,
                    ),
                ),
                ExprStatement(
                    expr=Call(
                        type=None,
                        name="print",
                        args=[Field(type=None, chain=["b"])],
                        params=None,
                        distinct=False,
                    ),
                ),
            ]
        )
        self.assertEqual(program, expected)

    def test_program_variable_reassignment(self):
        code = "var a := 3; a := 4;"
        program = self._program(code)
        expected = Program(
            start=None,
            end=None,
            declarations=[
                VariableDeclaration(
                    start=None,
                    end=None,
                    name="a",
                    expr=Constant(start=None, end=None, type=None, value=3),
                ),
                VariableAssignment(
                    start=None,
                    end=None,
                    left=Field(chain=["a"]),
                    right=Constant(start=None, end=None, type=None, value=4),
                ),
            ],
        )
        self.assertEqual(program, expected)

    def test_program_variable_declarations_with_sql_expr(self):
        code = """
            var query := (select id, properties.email from events where timestamp > now() - interval 1 day);
            var results := run(query);
        """
        program = self._program(code)
        expected = Program(
            declarations=[
                VariableDeclaration(
                    name="query",
                    expr=SelectQuery(
                        type=None,
                        ctes=None,
                        select=[
                            Field(type=None, chain=["id"]),
                            Field(type=None, chain=["properties", "email"]),
                        ],
                        distinct=None,
                        select_from=JoinExpr(
                            type=None,
                            join_type=None,
                            table=Field(type=None, chain=["events"]),
                            table_args=None,
                            alias=None,
                            table_final=None,
                            constraint=None,
                            next_join=None,
                            sample=None,
                        ),
                        array_join_op=None,
                        array_join_list=None,
                        window_exprs=None,
                        where=CompareOperation(
                            type=None,
                            left=Field(type=None, chain=["timestamp"]),
                            right=ArithmeticOperation(
                                type=None,
                                left=Call(type=None, name="now", args=[], params=None, distinct=False),
                                right=Call(
                                    type=None,
                                    name="toIntervalDay",
                                    args=[Constant(type=None, value=1)],
                                    params=None,
                                    distinct=False,
                                ),
                                op=ArithmeticOperationOp.Sub,
                            ),
                            op=CompareOperationOp.Gt,
                        ),
                        prewhere=None,
                        having=None,
                        group_by=None,
                        order_by=None,
                        limit=None,
                        limit_by=None,
                        limit_with_ties=None,
                        offset=None,
                        settings=None,
                        view_name=None,
                    ),
                ),
                VariableDeclaration(
                    name="results",
                    expr=Call(
                        name="run",
                        args=[Field(type=None, chain=["query"])],
                        params=None,
                        distinct=False,
                    ),
                ),
            ]
        )
        self.assertEqual(program, expected)

    def test_program_if(self):
        code = """
            if (a) {
                var c := 3;
            }
            else
                print(d);
        """

        program = self._program(code)
        expected = Program(
            declarations=[
                IfStatement(
                    expr=Field(type=None, chain=["a"]),
                    then=Block(
                        declarations=[
                            VariableDeclaration(
                                name="c",
                                expr=Constant(type=None, value=3),
                            )
                        ],
                    ),
                    else_=ExprStatement(
                        expr=Call(
                            type=None,
                            name="print",
                            args=[Field(type=None, chain=["d"])],
                            params=None,
                            distinct=False,
                        ),
                    ),
                )
            ],
        )

        self.assertEqual(program, expected)

    def test_program_while(self):
        code = """
            while (a < 5) {
                var c := 3;
            }
        """

        program = self._program(code)
        expected = Program(
            declarations=[
                WhileStatement(
                    expr=CompareOperation(
                        type=None,
                        left=Field(type=None, chain=["a"]),
                        right=Constant(type=None, value=5),
                        op=CompareOperationOp.Lt,
                    ),
                    body=Block(
                        declarations=[VariableDeclaration(name="c", expr=Constant(type=None, value=3))],
                    ),
                )
            ],
        )

        self.assertEqual(program, expected)

    def test_program_function(self):
        code = """
            fn query(a, b) {
                var c := 3;
            }
        """

        program = self._program(code)
        expected = Program(
            declarations=[
                Function(
                    name="query",
                    params=["a", "b"],
                    body=Block(
                        declarations=[VariableDeclaration(name="c", expr=Constant(type=None, value=3))],
                    ),
                )
            ],
        )
        self.assertEqual(program, expected)

    def test_program_functions(self):
        code = """
            fn query(a, b) {
                var c := 3;
            }

            fn read(a, b) {
                print(3);
                var b := 4;
            }
        """

        program = self._program(code)

        expected = Program(
            start=None,
            end=None,
            declarations=[
                Function(
                    start=None,
                    end=None,
                    name="query",
                    params=["a", "b"],
                    body=Block(
                        start=None,
                        end=None,
                        declarations=[
                            VariableDeclaration(
                                start=None,
                                end=None,
                                name="c",
                                expr=Constant(start=None, end=None, type=None, value=3),
                            )
                        ],
                    ),
                ),
                Function(
                    start=None,
                    end=None,
                    name="read",
                    params=["a", "b"],
                    body=Block(
                        start=None,
                        end=None,
                        declarations=[
                            ExprStatement(
                                start=None,
                                end=None,
                                expr=Call(
                                    start=None,
                                    end=None,
                                    type=None,
                                    name="print",
                                    args=[Constant(start=None, end=None, type=None, value=3)],
                                    params=None,
                                    distinct=False,
                                ),
                            ),
                            VariableDeclaration(
                                start=None,
                                end=None,
                                name="b",
                                expr=Constant(start=None, end=None, type=None, value=4),
                            ),
                        ],
                    ),
                ),
            ],
        )
        self.assertEqual(program, expected)

    def test_program_array(self):
        code = "var a := [1, 2, 3];"
        program = self._program(code)

        expected = Program(
            start=None,
            end=None,
            declarations=[
                VariableDeclaration(
                    start=None,
                    end=None,
                    name="a",
                    expr=Array(
                        start=None,
                        end=None,
                        type=None,
                        exprs=[
                            Constant(start=None, end=None, type=None, value=1),
                            Constant(start=None, end=None, type=None, value=2),
                            Constant(start=None, end=None, type=None, value=3),
                        ],
                    ),
                )
            ],
        )
        self.assertEqual(program, expected)

    def test_program_dict(self):
        code = "var a := {};"
        program = self._program(code)

        expected = Program(
            start=None,
            end=None,
            declarations=[
                VariableDeclaration(
                    start=None,
                    end=None,
                    name="a",
                    expr=Dict(start=None, end=None, type=None, items=[]),
                )
            ],
        )

        self.assertEqual(program, expected)

        code = "var a := {1: 2, 'a': [3, 4], g: true};"
        program = self._program(code)

        expected = Program(
            start=None,
            end=None,
            declarations=[
                VariableDeclaration(
                    start=None,
                    end=None,
                    name="a",
                    expr=Dict(
                        start=None,
                        end=None,
                        type=None,
                        items=[
                            (
                                Constant(start=None, end=None, type=None, value=1),
                                Constant(start=None, end=None, type=None, value=2),
                            ),
                            (
                                Constant(start=None, end=None, type=None, value="a"),
                                Array(
                                    start=None,
                                    end=None,
                                    type=None,
                                    exprs=[
                                        Constant(start=None, end=None, type=None, value=3),
                                        Constant(start=None, end=None, type=None, value=4),
                                    ],
                                ),
                            ),
                            (
                                Field(start=None, end=None, type=None, chain=["g"]),
                                Constant(start=None, end=None, type=None, value=True),
                            ),
                        ],
                    ),
                )
            ],
        )
        self.assertEqual(program, expected)
