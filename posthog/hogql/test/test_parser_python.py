from ._test_parser import parser_test_factory
from posthog.hogql.ast import (
    VariableDeclaration,
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
                VariableDeclaration(
                    start=None, end=None, name="a", expr=Constant(start=None, end=None, type=None, value="123")
                ),
                VariableDeclaration(
                    start=None,
                    end=None,
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
                    start=None,
                    end=None,
                    name="query",
                    expr=SelectQuery(
                        start=None,
                        end=None,
                        type=None,
                        ctes=None,
                        select=[
                            Field(start=None, end=None, type=None, chain=["id"]),
                            Field(start=None, end=None, type=None, chain=["properties", "email"]),
                        ],
                        distinct=None,
                        select_from=JoinExpr(
                            start=None,
                            end=None,
                            type=None,
                            join_type=None,
                            table=Field(start=None, end=None, type=None, chain=["events"]),
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
                            start=None,
                            end=None,
                            type=None,
                            left=Field(start=None, end=None, type=None, chain=["timestamp"]),
                            right=ArithmeticOperation(
                                start=None,
                                end=None,
                                type=None,
                                left=Call(
                                    start=None, end=None, type=None, name="now", args=[], params=None, distinct=False
                                ),
                                right=Call(
                                    start=None,
                                    end=None,
                                    type=None,
                                    name="toIntervalDay",
                                    args=[Constant(start=None, end=None, type=None, value=1)],
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
                    start=None,
                    end=None,
                    name="results",
                    expr=Call(
                        start=None,
                        end=None,
                        name="run",
                        args=[Field(start=None, end=None, type=None, chain=["query"])],
                        params=None,
                        distinct=False,
                    ),
                ),
            ]
        )
        self.assertEqual(program, expected)

    # def test_program_fetch(self):
    #     code = """
    #         var events := fetch("https://hogql.io/events.json");
    #         var queries := map(events, (event) -> (
    #             select id, properties.email
    #             from events
    #             where timestamp > now() - interval 1 day and event={event}
    #         ));
    #         var results := map(queries, (query) -> run(query));
    #         var combined_rows := reduce(results, (acc, result) -> acc + result.rows, []);
    #     """

    #     program = self._program(code)
    #     expected = []

    #     self.assertEqual(program, expected)

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
            start=None,
            end=None,
            declarations=[
                IfStatement(
                    start=None,
                    end=None,
                    expr=Field(start=None, end=None, type=None, chain=["a"]),
                    then=Block(
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
                    else_=ExprStatement(
                        start=None,
                        end=None,
                        expr=Call(
                            start=None,
                            end=None,
                            type=None,
                            name="print",
                            args=[Field(start=None, end=None, type=None, chain=["d"])],
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
            start=None,
            end=None,
            declarations=[
                WhileStatement(
                    start=None,
                    end=None,
                    expr=CompareOperation(
                        start=None,
                        end=None,
                        type=None,
                        left=Field(start=None, end=None, type=None, chain=["a"]),
                        right=Constant(start=None, end=None, type=None, value=5),
                        op=CompareOperationOp.Lt,
                    ),
                    body=Block(
                        start=None,
                        end=None,
                        declarations=[
                            VariableDeclaration(
                                start=None, end=None, name="c", expr=Constant(start=None, end=None, type=None, value=3)
                            )
                        ],
                    ),
                )
            ],
        )

        self.assertEqual(program, expected)
