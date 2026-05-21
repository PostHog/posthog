import math
from typing import Optional, cast

from posthog.test.base import BaseTest, MemoryLeakTestMixin, no_memory_leak_check

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.ast import (
    ArithmeticOperation,
    ArithmeticOperationOp,
    Array,
    Block,
    Call,
    CompareOperation,
    CompareOperationOp,
    Constant,
    Dict,
    ExprStatement,
    Field,
    Function,
    IfStatement,
    JoinExpr,
    Program,
    SelectQuery,
    SelectSetNode,
    SelectSetQuery,
    VariableAssignment,
    VariableDeclaration,
    WhileStatement,
)
from posthog.hogql.constants import HogQLParserBackend
from posthog.hogql.errors import ExposedHogQLError, SyntaxError
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_program, parse_select, parse_string_template
from posthog.hogql.visitor import clear_locations


def parser_test_factory(backend: HogQLParserBackend):
    base_classes = (BaseTest,) if backend == "python" else (MemoryLeakTestMixin, BaseTest)

    class TestParser(*base_classes):  # type: ignore
        MEMORY_INCREASE_PER_PARSE_LIMIT_B = 10_000
        MEMORY_INCREASE_INCREMENTAL_FACTOR_LIMIT = 0.1
        MEMORY_PRIMING_RUNS_N = 2
        MEMORY_LEAK_CHECK_RUNS_N = 100

        maxDiff = None

        def _string_template(self, template: str, placeholders: Optional[dict[str, ast.Expr]] = None) -> ast.Expr:
            return clear_locations(parse_string_template(template, placeholders=placeholders, backend=backend))

        def _expr(self, expr: str, placeholders: Optional[dict[str, ast.Expr]] = None) -> ast.Expr:
            return clear_locations(parse_expr(expr, placeholders=placeholders, backend=backend))

        def _select(
            self, query: str, placeholders: Optional[dict[str, ast.Expr]] = None
        ) -> ast.SelectQuery | ast.SelectSetQuery | ast.HogQLXTag:
            return cast(
                ast.SelectQuery | ast.SelectSetQuery | ast.HogQLXTag,
                clear_locations(parse_select(query, placeholders=placeholders, backend=backend)),
            )

        def _program(self, program: str) -> ast.Program:
            return cast(ast.Program, clear_locations(cast(ast.Expr, parse_program(program, backend=backend))))

        def test_numbers(self):
            self.assertEqual(self._expr("1"), ast.Constant(value=1))
            self.assertEqual(self._expr("1.2"), ast.Constant(value=1.2))
            self.assertEqual(self._expr("-1"), ast.Constant(value=-1))
            self.assertEqual(self._expr("-1.1"), ast.Constant(value=-1.1))
            self.assertEqual(self._expr("0"), ast.Constant(value=0))
            self.assertEqual(self._expr("0.0"), ast.Constant(value=0))
            self.assertEqual(self._expr("-inf"), ast.Constant(value=float("-inf")))
            self.assertEqual(self._expr("inf"), ast.Constant(value=float("inf")))
            # nan-s don't like to be compared
            parsed_nan = self._expr("nan")
            self.assertTrue(isinstance(parsed_nan, ast.Constant))
            self.assertTrue(math.isnan(cast(ast.Constant, parsed_nan).value))
            self.assertEqual(self._expr("1e-18"), ast.Constant(value=1e-18))
            self.assertEqual(self._expr("2.34e+20"), ast.Constant(value=2.34e20))

        @parameterized.expand(
            [
                # Hex: HEXADECIMAL_LITERAL tokens were being parsed via base-10 stoll/int,
                # which stops at the 'x' and silently yielded 0.
                ("hex_positive", "0x1F", 31),
                ("hex_zero", "0x0", 0),
                ("hex_ff", "0xff", 255),
                ("hex_negative", "-0x1F", -31),
                ("hex_positive_sign", "+0x1F", 31),
                # Hex digits include 'e' — must be dispatched before the float guard,
                # or "0xfe" routes through float()/stod and either raises (Python)
                # or silently returns a double (C++) instead of an int64.
                ("hex_with_e_digit", "0xfe", 254),
                ("hex_negative_with_e_digit", "-0xae", -174),
                # Near 2^60 the double mantissa is 8 bits short, so a stod-based hex parse rounds wrong.
                ("hex_breaks_double_precision", "0x100000000000000e", 0x100000000000000E),
                # Leading zeros are no-ops, never octal — "017" → 17, "09" → 9 — matching ClickHouse/Postgres.
                ("leading_zero_017_decimal", "017", 17),
                ("leading_zero_negative_017_decimal", "-017", -17),
                ("leading_zero_signed_017_decimal", "+017", 17),
                ("leading_zero_011", "011", 11),
                ("leading_zero_018", "018", 18),
                ("leading_zero_09", "09", 9),
                ("leading_zero_019", "019", 19),
                ("leading_zero_08", "08", 8),
                ("leading_zero_099", "099", 99),
                ("leading_zero_negative_09", "-09", -9),
                # `+inf` once fell through to NaN — visitor only matched "inf" / "-inf".
                ("positive_inf", "+inf", float("inf")),
                # `infinity` spelling (INF token matches it too) — accepted, matching ClickHouse.
                ("infinity_lowercase", "infinity", float("inf")),
                ("infinity_titlecase", "Infinity", float("inf")),
                ("infinity_uppercase", "INFINITY", float("inf")),
                ("infinity_negative", "-Infinity", float("-inf")),
                ("infinity_positive_sign", "+Infinity", float("inf")),
            ]
        )
        def test_signed_radix_number_literals(self, _name: str, expr: str, expected: int | float):
            self.assertEqual(self._expr(expr), ast.Constant(value=expected))

        def test_select_columns_leading_zero_literals(self):
            # Leading zeros are no-ops in SELECT-column position too.
            select = cast(ast.SelectQuery, self._select("SELECT 9, 09, 011, 017, 018"))
            self.assertEqual([cast(ast.Constant, c).value for c in select.select], [9, 9, 11, 17, 18])

        @parameterized.expand(
            [
                ("binary_zero", "0b0", 0),
                ("binary_one", "0b1", 1),
                ("binary_two_bit", "0b10", 2),
                ("binary_byte", "0b1010", 10),
                ("binary_uppercase_prefix", "0B11", 3),
                ("binary_negative", "-0b1010", -10),
                ("binary_positive_sign", "+0b11", 3),
                # 64-bit boundary: magnitude fits UInt64 (positive) or Int64 (negative).
                ("binary_int64_max", "0b" + "1" * 63, 2**63 - 1),
                ("binary_uint64_max", "0b" + "1" * 64, 2**64 - 1),
                ("binary_int64_min", "-0b1" + "0" * 63, -(2**63)),
            ]
        )
        def test_binary_literals(self, _name: str, expr: str, expected: int):
            # `0b<binary-digits>` is a real lexer token; ClickHouse parses binary literals natively.
            self.assertEqual(self._expr(expr), ast.Constant(value=expected))

        def test_select_binary_literals_in_select(self):
            # Before BINARY_LITERAL was a token, `0b1010` split into `0` + IDENTIFIER `b1010`.
            select = cast(ast.SelectQuery, self._select("SELECT 0b1010, 0b11 + 1, 0b0"))
            values = []
            for c in select.select:
                if isinstance(c, ast.Constant):
                    values.append(c.value)
                else:
                    values.append(c)  # arithmetic expr stays
            self.assertEqual(values[0], 10)
            self.assertEqual(values[2], 0)
            # 0b11 + 1: 3 + 1 = 4, expressed as an ArithmeticOperation.
            self.assertEqual(
                values[1],
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Add,
                    left=ast.Constant(value=3),
                    right=ast.Constant(value=1),
                ),
            )

        def test_binary_literal_in_where(self):
            # Binary literals work in every position a number can — including WHERE.
            select = cast(ast.SelectQuery, self._select("SELECT 1 FROM events WHERE id = 0b1010"))
            assert select.where is not None
            where = cast(ast.CompareOperation, select.where)
            self.assertEqual(cast(ast.Constant, where.right).value, 10)

        @parameterized.expand(
            [
                ("octal_lowercase_o", "SELECT 0o11"),
                ("octal_uppercase_o", "SELECT 0O11"),
                ("octal_in_arithmetic", "SELECT 0o11 + 1"),
                ("octal_in_where", "SELECT 1 FROM events WHERE id = 0o11"),
                ("octal_invalid_digit", "SELECT 0o9"),  # rejected regardless of digit validity
                ("octal_signed", "SELECT -0o11"),
            ]
        )
        def test_postgres_octal_literals_rejected(self, _name: str, query: str):
            # `0o<digits>` lexes as OCTAL_PREFIX_LITERAL and visitNumberLiteral throws — matches ClickHouse / pre-pg16 PG.
            with self.assertRaises((ExposedHogQLError, SyntaxError)):
                self._select(query)

        @parameterized.expand(
            [
                ("invalid_digit_2", "SELECT 0b22"),
                ("invalid_digit_9", "SELECT 0b9"),
                ("partial_invalid", "SELECT 0b102"),
            ]
        )
        def test_malformed_binary_literals_rejected(self, _name: str, query: str):
            # `0b<non-binary-digit>` lexes as MALFORMED_BINARY_LITERAL, unreferenced by any rule, so the parser rejects it.
            with self.assertRaises((ExposedHogQLError, SyntaxError)):
                self._select(query)

        @parameterized.expand(
            [
                ("65_bits", "SELECT 0b" + "1" * 65),
                ("2_to_the_64", "SELECT 0b1" + "0" * 64),
                ("negative_below_int64_min", "SELECT -0b" + "1" * 64),
            ]
        )
        def test_oversized_binary_literals_rejected(self, _name: str, query: str):
            # ClickHouse caps binary literals at 64 bits — magnitude must fit UInt64 (positive) or Int64 (negative).
            with self.assertRaises((ExposedHogQLError, SyntaxError)):
                self._select(query)

        @parameterized.expand(
            [
                ("logical_not", "let x := !y", "U+0021"),
                ("logical_not_in_condition", "if (!country) { return 1 }", "U+0021"),
                ("logical_and", "let x := a && b", "U+0026"),
                ("bitwise_and", "let x := a & b", "U+0026"),
                ("stray_at_sign", "let x := a @ b", "U+0040"),
                ("zero_width_space", "let x :=​y", "U+200B"),
                ("zero_width_joiner", "let x := a‍b", "U+200D"),
            ]
        )
        def test_unexpected_character_rejected(self, _name: str, program: str, code_point: str):
            # A character no lexer rule matches — a JavaScript `!`, `&&`, a
            # zero-width space, any stray byte — lexes as the catch-all
            # UNEXPECTED_CHARACTER token. No parser rule references it, so
            # the program fails loudly instead of the lexer silently
            # dropping the character via error recovery and the rest
            # parsing as a different, valid-looking program. The error
            # names the offending character by Unicode code point — the
            # only actionable signal when the character is invisible.
            with self.assertRaises((ExposedHogQLError, SyntaxError)) as caught:
                self._program(program)
            self.assertIn(code_point, str(caught.exception))

        def test_zero_width_character_allowed_inside_string(self):
            # The catch-all only fires outside string literals — a
            # zero-width character is ordinary content within a string.
            self._program("let x := 'a​b'")

        @parameterized.expand(
            [
                ("not_equals", "a != b"),
                ("not_regex", "a !~ b"),
                ("concat", "a || b"),
                ("nullish_coalesce", "a ?? b"),
            ]
        )
        def test_multi_character_operators_still_parse(self, _name: str, expr: str):
            # The catch-all is a last-resort fallback: maximal munch keeps
            # genuine multi-character operators whose first byte would
            # otherwise be unrecognized (`!=`, `!~`) intact.
            self._expr(expr)

        @parameterized.expand(
            [
                ("no_break_space", " "),
                ("next_line", ""),
                ("ogham_space_mark", " "),
                ("en_space", " "),
                ("line_separator", " "),
                ("paragraph_separator", " "),
                ("narrow_no_break_space", " "),
                ("medium_mathematical_space", " "),
                ("ideographic_space", "　"),
            ]
        )
        def test_unicode_whitespace_separates_tokens(self, _name: str, space: str):
            # A Unicode whitespace character — routinely pasted in from
            # rich editors or documents — is genuine whitespace. It must
            # keep separating tokens and produce the same AST as an
            # ordinary space, NOT fall through to UNEXPECTED_CHARACTER and
            # fail the parse. Checked both between statements and inside
            # an expression.
            self.assertEqual(self._program(f"let x :={space}1"), self._program("let x := 1"))
            self.assertEqual(self._expr(f"1{space}+{space}2"), self._expr("1 + 2"))

        def test_byte_order_mark_does_not_break_parse(self):
            # A file saved with a leading UTF-8 byte-order mark still parses.
            self.assertEqual(self._program("﻿let x := 1"), self._program("let x := 1"))

        def test_booleans(self):
            self.assertEqual(self._expr("true"), ast.Constant(value=True))
            self.assertEqual(self._expr("TRUE"), ast.Constant(value=True))
            self.assertEqual(self._expr("false"), ast.Constant(value=False))

        def test_null(self):
            self.assertEqual(self._expr("null"), ast.Constant(value=None))

        def test_nullish(self):
            self.assertEqual(
                self._expr("1 ?? 2"),
                ast.Call(
                    name="ifNull",
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                    ],
                ),
            )

        def test_null_property(self):
            self.assertEqual(
                self._expr("a?.b"),
                ast.ArrayAccess(
                    array=ast.Field(chain=["a"]),
                    property=ast.Constant(value="b"),
                    nullish=True,
                ),
            )

        def test_null_tuple(self):
            self.assertEqual(
                self._expr("a?.1"),
                ast.TupleAccess(
                    tuple=ast.Field(chain=["a"]),
                    index=1,
                    nullish=True,
                ),
            )

        def test_null_property_nested(self):
            self.assertEqual(
                self._expr("a?.b?.['c']"),
                ast.ArrayAccess(
                    array=ast.ArrayAccess(array=ast.Field(chain=["a"]), property=ast.Constant(value="b"), nullish=True),
                    property=ast.Constant(value="c"),
                    nullish=True,
                ),
            )

        def test_conditional(self):
            self.assertEqual(
                self._expr("1 > 2 ? 1 : 2"),
                ast.Call(
                    name="if",
                    args=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Gt,
                            left=ast.Constant(value=1),
                            right=ast.Constant(value=2),
                        ),
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                    ],
                ),
            )

        def test_arrays(self):
            self.assertEqual(self._expr("[]"), ast.Array(exprs=[]))
            self.assertEqual(self._expr("[1]"), ast.Array(exprs=[ast.Constant(value=1)]))
            self.assertEqual(
                self._expr("[1, avg()]"),
                ast.Array(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])]),
            )
            self.assertEqual(self._expr("[1,]"), ast.Array(exprs=[ast.Constant(value=1)]))
            self.assertEqual(
                self._expr("[1, avg(),]"),
                ast.Array(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])]),
            )
            self.assertEqual(
                self._expr("properties['value']"),
                ast.ArrayAccess(
                    array=ast.Field(chain=["properties"]),
                    property=ast.Constant(value="value"),
                ),
            )
            self.assertEqual(
                self._expr("properties[(select 'value')]"),
                ast.ArrayAccess(
                    array=ast.Field(chain=["properties"]),
                    property=ast.SelectQuery(select=[ast.Constant(value="value")]),
                ),
            )
            self.assertEqual(
                self._expr("[1,2,3][1]"),
                ast.ArrayAccess(
                    array=ast.Array(
                        exprs=[
                            ast.Constant(value=1),
                            ast.Constant(value=2),
                            ast.Constant(value=3),
                        ]
                    ),
                    property=ast.Constant(value=1),
                ),
            )
            self.assertEqual(
                self._expr("arr[1:3]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=ast.Constant(value=1),
                    end_expr=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._expr("arr[:3]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=None,
                    end_expr=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._expr("arr[1:]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=ast.Constant(value=1),
                    end_expr=None,
                ),
            )
            self.assertEqual(
                self._expr("arr[:]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=None,
                    end_expr=None,
                ),
            )
            self.assertEqual(
                self._expr("arr[(1 + 2):(-3)]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Add,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                    end_expr=ast.Constant(value=-3),
                ),
            )
            self.assertEqual(
                self._expr("arr[-5:]"),
                ast.ArraySlice(
                    array=ast.Field(chain=["arr"]),
                    start_expr=ast.Constant(value=-5),
                    end_expr=None,
                ),
            )

        def test_tuples(self):
            self.assertEqual(
                self._expr("(1, avg())"),
                ast.Tuple(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])]),
            )
            self.assertEqual(
                self._expr("(1, avg(),)"),
                ast.Tuple(exprs=[ast.Constant(value=1), ast.Call(name="avg", args=[])]),
            )
            self.assertEqual(
                self._expr("(1,)"),
                ast.Tuple(exprs=[ast.Constant(value=1)]),
            )
            # needs at least two values to be a tuple
            self.assertEqual(self._expr("(1)"), ast.Constant(value=1))

        def test_lambdas(self):
            self.assertEqual(
                self._expr("(x, y) -> x * y"),
                ast.Lambda(
                    args=["x", "y"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Field(chain=["y"]),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("x, y -> x * y"),
                ast.Lambda(
                    args=["x", "y"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Field(chain=["y"]),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("(x) -> x * y"),
                ast.Lambda(
                    args=["x"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Field(chain=["y"]),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("x -> x * y"),
                ast.Lambda(
                    args=["x"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Field(chain=["y"]),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("lambda x: x * 2"),
                ast.Lambda(
                    args=["x"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Constant(value=2),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("lambda x, y: x * y"),
                ast.Lambda(
                    args=["x", "y"],
                    expr=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Mult,
                        left=ast.Field(chain=["x"]),
                        right=ast.Field(chain=["y"]),
                    ),
                ),
            )
            self.assertEqual(
                self._expr("arrayMap(x -> x * 2)"),
                ast.Call(
                    name="arrayMap",
                    args=[
                        ast.Lambda(
                            args=["x"],
                            expr=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Mult,
                                left=ast.Field(chain=["x"]),
                                right=ast.Constant(value=2),
                            ),
                        )
                    ],
                ),
            )
            self.assertEqual(
                self._expr("arrayMap((x) -> x * 2)"),
                ast.Call(
                    name="arrayMap",
                    args=[
                        ast.Lambda(
                            args=["x"],
                            expr=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Mult,
                                left=ast.Field(chain=["x"]),
                                right=ast.Constant(value=2),
                            ),
                        )
                    ],
                ),
            )
            self.assertEqual(
                self._expr("arrayMap((x, y) -> x * y)"),
                ast.Call(
                    name="arrayMap",
                    args=[
                        ast.Lambda(
                            args=["x", "y"],
                            expr=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Mult,
                                left=ast.Field(chain=["x"]),
                                right=ast.Field(chain=["y"]),
                            ),
                        )
                    ],
                ),
            )

        def test_lambda_blocks(self):
            self.assertEqual(
                self._expr("(x, y) -> { print('hello'); return x * y }"),
                ast.Lambda(
                    args=["x", "y"],
                    expr=ast.Block(
                        declarations=[
                            ast.ExprStatement(expr=ast.Call(name="print", args=[ast.Constant(value="hello")])),
                            ast.ReturnStatement(
                                expr=ast.ArithmeticOperation(
                                    op=ast.ArithmeticOperationOp.Mult,
                                    left=ast.Field(chain=["x"]),
                                    right=ast.Field(chain=["y"]),
                                )
                            ),
                        ]
                    ),
                ),
            )

        def test_try_cast(self):
            self.assertEqual(
                self._expr("try_cast(1 AS Int64)"),
                ast.TryCast(expr=ast.Constant(value=1), type_name="int64"),
            )

        def test_call_expr(self):
            self.assertEqual(
                self._expr("asd.asd(123)"),
                ast.ExprCall(
                    expr=ast.Field(chain=["asd", "asd"]),
                    args=[ast.Constant(value=123)],
                ),
            )
            self.assertEqual(
                self._expr("asd['asd'](123)"),
                ast.ExprCall(
                    expr=ast.ArrayAccess(array=ast.Field(chain=["asd"]), property=ast.Constant(value="asd")),
                    args=[ast.Constant(value=123)],
                ),
            )
            self.assertEqual(
                self._expr("(x -> x * 2)(3)"),
                ast.ExprCall(
                    expr=ast.Lambda(
                        args=["x"],
                        expr=ast.ArithmeticOperation(
                            op=ast.ArithmeticOperationOp.Mult, left=ast.Field(chain=["x"]), right=ast.Constant(value=2)
                        ),
                    ),
                    args=[ast.Constant(value=3)],
                ),
            )

        def test_call_expr_sql(self):
            self.assertEqual(
                self._expr("asd.asd(select 1)"),
                ast.ExprCall(
                    expr=ast.Field(chain=["asd", "asd"]),
                    args=[ast.SelectQuery(select=[ast.Constant(value=1)])],
                ),
            )
            self.assertEqual(
                self._expr("sql(select 1)"),
                ast.Call(
                    name="sql",
                    args=[ast.SelectQuery(select=[ast.Constant(value=1)])],
                ),
            )

        def test_strings(self):
            self.assertEqual(self._expr("'null'"), ast.Constant(value="null"))
            self.assertEqual(self._expr("'n''ull'"), ast.Constant(value="n'ull"))
            self.assertEqual(self._expr("'n''''ull'"), ast.Constant(value="n''ull"))
            self.assertEqual(self._expr("'n\null'"), ast.Constant(value="n\null"))  # newline passed into string
            self.assertEqual(self._expr("'n\\null'"), ast.Constant(value="n\null"))  # slash and 'n' passed into string
            self.assertEqual(self._expr("'n\\\\ull'"), ast.Constant(value="n\\ull"))  # slash and 'n' passed into string
            self.assertEqual(self._expr("'\\x41'"), ast.Constant(value="\\x41"))
            self.assertEqual(self._expr("'\\x61\\x62'"), ast.Constant(value="\\x61\\x62"))
            self.assertEqual(self._expr("'\\x5a'"), ast.Constant(value="\\x5a"))

            # String literals containing special float names should remain as strings
            self.assertEqual(self._expr("'Infinity'"), ast.Constant(value="Infinity"))
            self.assertEqual(self._expr("'-Infinity'"), ast.Constant(value="-Infinity"))
            self.assertEqual(self._expr("'NaN'"), ast.Constant(value="NaN"))

        def test_arithmetic_operations(self):
            self.assertEqual(
                self._expr("1 + 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 + -2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=-2),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 - 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Sub,
                ),
            )
            self.assertEqual(
                self._expr("1 * 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Mult,
                ),
            )
            self.assertEqual(
                self._expr("1 / 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Div,
                ),
            )
            self.assertEqual(
                self._expr("1 % 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Mod,
                ),
            )
            self.assertEqual(
                self._expr("1 + 2 + 2"),
                ast.ArithmeticOperation(
                    left=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                        op=ast.ArithmeticOperationOp.Add,
                    ),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 * 1 * 2"),
                ast.ArithmeticOperation(
                    left=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=1),
                        op=ast.ArithmeticOperationOp.Mult,
                    ),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Mult,
                ),
            )
            self.assertEqual(
                self._expr("1 + 1 * 2"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                        op=ast.ArithmeticOperationOp.Mult,
                    ),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 * 1 + 2"),
                ast.ArithmeticOperation(
                    left=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=1),
                        op=ast.ArithmeticOperationOp.Mult,
                    ),
                    right=ast.Constant(value=2),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )

        def test_math_comparison_operations(self):
            self.assertEqual(
                self._expr("1 = 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.Eq,
                ),
            )
            self.assertEqual(
                self._expr("1 == 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.Eq,
                ),
            )
            self.assertEqual(
                self._expr("1 != 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.NotEq,
                ),
            )
            self.assertEqual(
                self._expr("1 < 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.Lt,
                ),
            )
            self.assertEqual(
                self._expr("1 <= 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.LtEq,
                ),
            )
            self.assertEqual(
                self._expr("1 > 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.Gt,
                ),
            )
            self.assertEqual(
                self._expr("1 >= 2"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    op=ast.CompareOperationOp.GtEq,
                ),
            )
            self.assertEqual(
                self._expr("1 is distinct from 2"),
                ast.IsDistinctFrom(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    negated=False,
                ),
            )
            self.assertEqual(
                self._expr("1 is not distinct from 2"),
                ast.IsDistinctFrom(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    negated=True,
                ),
            )

        def test_null_comparison_operations(self):
            self.assertEqual(
                self._expr("1 is null"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=None),
                    op=ast.CompareOperationOp.Eq,
                    is_null_comparison_style=True,
                ),
            )
            self.assertEqual(
                self._expr("1 is not null"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=None),
                    op=ast.CompareOperationOp.NotEq,
                    is_null_comparison_style=True,
                ),
            )

        def test_like_comparison_operations(self):
            self.assertEqual(
                self._expr("1 like 'a%sd'"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="a%sd"),
                    op=ast.CompareOperationOp.Like,
                ),
            )
            self.assertEqual(
                self._expr("1 not like 'a%sd'"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="a%sd"),
                    op=ast.CompareOperationOp.NotLike,
                ),
            )
            self.assertEqual(
                self._expr("1 ilike 'a%sd'"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="a%sd"),
                    op=ast.CompareOperationOp.ILike,
                ),
            )
            self.assertEqual(
                self._expr("1 not ilike 'a%sd'"),
                ast.CompareOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value="a%sd"),
                    op=ast.CompareOperationOp.NotILike,
                ),
            )

        def test_and_or(self):
            self.assertEqual(
                self._expr("true or false"),
                ast.Or(exprs=[ast.Constant(value=True), ast.Constant(value=False)]),
            )
            self.assertEqual(
                self._expr("true and false"),
                ast.And(exprs=[ast.Constant(value=True), ast.Constant(value=False)]),
            )
            self.assertEqual(
                self._expr("true and not false"),
                ast.And(
                    exprs=[
                        ast.Constant(value=True),
                        ast.Not(expr=ast.Constant(value=False)),
                    ],
                ),
            )
            self.assertEqual(
                self._expr("true or false or not true or 2"),
                ast.Or(
                    exprs=[
                        ast.Constant(value=True),
                        ast.Constant(value=False),
                        ast.Not(expr=ast.Constant(value=True)),
                        ast.Constant(value=2),
                    ],
                ),
            )
            self.assertEqual(
                self._expr("true or false and not true or 2"),
                ast.Or(
                    exprs=[
                        ast.Constant(value=True),
                        ast.And(
                            exprs=[
                                ast.Constant(value=False),
                                ast.Not(expr=ast.Constant(value=True)),
                            ],
                        ),
                        ast.Constant(value=2),
                    ],
                ),
            )

        def test_unary_operations(self):
            self.assertEqual(
                self._expr("not true"),
                ast.Not(expr=ast.Constant(value=True)),
            )

        def test_parens(self):
            self.assertEqual(
                self._expr("(1)"),
                ast.Constant(value=1),
            )
            self.assertEqual(
                self._expr("(1 + 1)"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=1),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )
            self.assertEqual(
                self._expr("1 + (1 + 1)"),
                ast.ArithmeticOperation(
                    left=ast.Constant(value=1),
                    right=ast.ArithmeticOperation(
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=1),
                        op=ast.ArithmeticOperationOp.Add,
                    ),
                    op=ast.ArithmeticOperationOp.Add,
                ),
            )

        def test_field_access(self):
            self.assertEqual(
                self._expr("event"),
                ast.Field(chain=["event"]),
            )
            self.assertEqual(
                self._expr("event like '$%'"),
                ast.CompareOperation(
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value="$%"),
                    op=ast.CompareOperationOp.Like,
                ),
            )

        def test_property_access(self):
            self.assertEqual(
                self._expr("properties.something == 1"),
                ast.CompareOperation(
                    left=ast.Field(chain=["properties", "something"]),
                    right=ast.Constant(value=1),
                    op=ast.CompareOperationOp.Eq,
                ),
            )
            self.assertEqual(
                self._expr("properties.something"),
                ast.Field(chain=["properties", "something"]),
            )
            self.assertEqual(
                self._expr("properties.$something"),
                ast.Field(chain=["properties", "$something"]),
            )
            self.assertEqual(
                self._expr("person.properties.something"),
                ast.Field(chain=["person", "properties", "something"]),
            )
            self.assertEqual(
                self._expr("this.can.go.on.for.miles"),
                ast.Field(chain=["this", "can", "go", "on", "for", "miles"]),
            )

        def test_calls(self):
            self.assertEqual(
                self._expr("avg()"),
                ast.Call(name="avg", args=[]),
            )
            self.assertEqual(
                self._expr("avg(1,2,3)"),
                ast.Call(
                    name="avg",
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                        ast.Constant(value=3),
                    ],
                ),
            )

        def test_calls_with_params(self):
            self.assertEqual(
                self._expr("quantile(0.95)(foo)"),
                ast.Call(
                    name="quantile",
                    args=[ast.Field(chain=["foo"])],
                    params=[ast.Constant(value=0.95)],
                ),
            )

        @parameterized.expand([["percentile_cont"], ["percentile_disc"]])
        def test_percentile_calls_within_group(self, function_name: str):
            self.assertEqual(
                self._expr(f"{function_name}(0.5) within group (order by foo desc)"),
                ast.Call(
                    name=function_name,
                    args=[],
                    params=[ast.Constant(value=0.5)],
                    within_group=[ast.OrderExpr(expr=ast.Field(chain=["foo"]), order="DESC")],
                ),
            )

        def test_function_calls_with_filter(self):
            self.assertEqual(
                self._expr("sum(event) FILTER (WHERE event = 'a')"),
                ast.Call(
                    name="sum",
                    params=None,
                    args=[ast.Field(chain=["event"])],
                    distinct=False,
                    filter_expr=ast.CompareOperation(
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value="a"),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ),
            )

        def test_function_calls_with_order_by(self):
            self.assertEqual(
                self._expr("sum(event ORDER BY timestamp DESC)"),
                ast.Call(
                    name="sum",
                    params=None,
                    args=[ast.Field(chain=["event"])],
                    distinct=False,
                    order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                ),
            )

        def test_keyword_named_function_call(self):
            self.assertEqual(
                self._expr("if(1, 2, 3)"),
                ast.Call(
                    name="if",
                    params=None,
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                        ast.Constant(value=3),
                    ],
                    distinct=False,
                ),
            )

        def test_alias(self):
            self.assertEqual(
                self._expr("1 as asd"),
                ast.Alias(alias="asd", expr=ast.Constant(value=1)),
            )
            self.assertEqual(
                self._expr("1 as `asd`"),
                ast.Alias(alias="asd", expr=ast.Constant(value=1)),
            )
            self.assertEqual(
                self._expr("1 as `🍄`"),
                ast.Alias(alias="🍄", expr=ast.Constant(value=1)),
            )
            self.assertEqual(
                self._expr("(1 as b) as `🍄`"),
                ast.Alias(alias="🍄", expr=ast.Alias(alias="b", expr=ast.Constant(value=1))),
            )

        def test_quoted_reserved_keyword_alias(self):
            self.assertEqual(
                self._select('select 1 "from"'),
                ast.SelectQuery(
                    select=[ast.Alias(alias="from", expr=ast.Constant(value=1))],
                ),
            )

        def test_quoted_reserved_keyword_alias_with_from_clause(self):
            self.assertEqual(
                self._select('select 1 "from" from events'),
                ast.SelectQuery(
                    select=[ast.Alias(alias="from", expr=ast.Constant(value=1))],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_not_expression_is_not_parsed_as_implicit_alias(self):
            self.assertEqual(
                self._select("select not true"),
                ast.SelectQuery(
                    select=[ast.Not(expr=ast.Constant(value=True))],
                ),
            )

        @parameterized.expand(
            [["ascending"], ["cohort"], ["date"], ["descending"], ["final"], ["id"], ["return"], ["top"], ["totals"]]
        )
        def test_allowed_keyword_implicit_aliases(self, alias: str):
            self.assertEqual(
                self._select(f"select 1 {alias} from events"),
                ast.SelectQuery(
                    select=[ast.Alias(alias=alias, expr=ast.Constant(value=1))],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        @parameterized.expand([["name"], ["timestamp"]])
        def test_disallowed_keyword_implicit_aliases(self, alias: str):
            with self.assertRaises(SyntaxError):
                self._select(f"select 1 {alias} from events")

        def test_from_cannot_precede_implicit_alias(self):
            with self.assertRaises(ExposedHogQLError):
                self._select("select from foo")

        def test_select_trailing_comma_before_from(self):
            self.assertEqual(
                self._select(
                    """
                    select
                      session.id as session_id,
                    from events
                    where
                      session_id = '019d4492-db9b-713e-b5ba-211e88348587'
                      and timestamp >= '1970-01-01'
                    """
                ),
                ast.SelectQuery(
                    select=[ast.Alias(alias="session_id", expr=ast.Field(chain=["session", "id"]))],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    where=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["session_id"]),
                                right=ast.Constant(value="019d4492-db9b-713e-b5ba-211e88348587"),
                                op=ast.CompareOperationOp.Eq,
                            ),
                            ast.CompareOperation(
                                left=ast.Field(chain=["timestamp"]),
                                right=ast.Constant(value="1970-01-01"),
                                op=ast.CompareOperationOp.GtEq,
                            ),
                        ]
                    ),
                ),
            )

        def test_clause_keyword_as_column_after_comma(self):
            # After a comma, the column list continues with another
            # column for a clause keyword that can also be a Field —
            # only `FROM` (and two-token `GROUP BY` / `ORDER BY`) makes
            # the comma trailing. `window` here is the second column.
            self.assertEqual(
                self._select("select 1, window from events"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1), ast.Field(chain=["window"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            # Same in a GROUP BY list — `window` is the second grouping
            # key, not the start of a WINDOW clause.
            grouped = self._select("select count() from events group by tool, window")
            assert isinstance(grouped, ast.SelectQuery)
            self.assertEqual(
                grouped.group_by,
                [ast.Field(chain=["tool"]), ast.Field(chain=["window"])],
            )

        def test_clause_keywords_reused_as_identifiers_throughout_query(self):
            # Every word in this query is a HogQL clause/operator keyword
            # being reused as a Field or table reference. The grammar's
            # `keyword` rule allow-lists `SELECT` / `FROM` / `WHERE` /
            # `AND` so they can stand in for an `identifier` in three
            # positions: column list (`select` as a Field), FROM-table
            # (`from` as a table), and WHERE expression (`where AND and`
            # is the And-of-two-Fields predicate). Catches lexer-mode
            # bugs and parser-rule bugs where a backend takes the
            # keyword path instead of the identifier path when both
            # are legal.
            self.assertEqual(
                self._select("select select from from where where and and"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["select"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["from"])),
                    where=ast.And(
                        exprs=[
                            ast.Field(chain=["where"]),
                            ast.Field(chain=["and"]),
                        ]
                    ),
                ),
            )

        def test_expr_with_ignored_sql_comment(self):
            self.assertEqual(
                self._expr("1 -- asd"),
                ast.Constant(value=1),
            )
            self.assertEqual(
                self._expr("1 -- 'asd'"),
                ast.Constant(value=1),
            )
            self.assertEqual(
                self._expr("1 -- '🍄'"),
                ast.Constant(value=1),
            )

        def test_placeholders(self):
            self.assertEqual(
                self._expr("{foo}"),
                ast.Placeholder(expr=ast.Field(chain=["foo"])),
            )
            self.assertEqual(
                self._expr("{foo}", {"foo": ast.Constant(value="bar")}),
                ast.Constant(value="bar"),
            )
            self.assertEqual(
                self._expr("timestamp < {timestamp}", {"timestamp": ast.Constant(value=123)}),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=123),
                ),
            )
            self.assertEqual(
                self._expr("timestamp={timestamp}", {"timestamp": ast.Constant(value=123)}),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=123),
                ),
            )

        def test_intervals(self):
            self.assertEqual(
                self._expr("interval 1 month"),
                ast.Call(name="toIntervalMonth", args=[ast.Constant(value=1)]),
            )
            self.assertEqual(
                self._expr("interval '1 month'"),
                ast.Call(name="toIntervalMonth", args=[ast.Constant(value=1)]),
            )
            self.assertEqual(
                self._expr("now() - interval 1 week"),
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub,
                    left=ast.Call(name="now", args=[]),
                    right=ast.Call(name="toIntervalWeek", args=[ast.Constant(value=1)]),
                ),
            )
            self.assertEqual(
                self._expr("now() - interval '1 week'"),
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub,
                    left=ast.Call(name="now", args=[]),
                    right=ast.Call(name="toIntervalWeek", args=[ast.Constant(value=1)]),
                ),
            )
            self.assertEqual(
                self._expr("interval event year"),
                ast.Call(name="toIntervalYear", args=[ast.Field(chain=["event"])]),
            )

        def test_select_columns(self):
            self.assertEqual(
                self._select("select 1"),
                ast.SelectQuery(select=[ast.Constant(value=1)]),
            )
            self.assertEqual(
                self._select("select total: 1 + 2"),
                ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="total",
                            expr=ast.ArithmeticOperation(
                                op=ast.ArithmeticOperationOp.Add,
                                left=ast.Constant(value=1),
                                right=ast.Constant(value=2),
                            ),
                        )
                    ]
                ),
            )
            self.assertEqual(
                self._select("select 1, 4, 'string'"),
                ast.SelectQuery(
                    select=[
                        ast.Constant(value=1),
                        ast.Constant(value=4),
                        ast.Constant(value="string"),
                    ]
                ),
            )

        def test_select_columns_distinct(self):
            self.assertEqual(
                self._select("select distinct 1"),
                ast.SelectQuery(select=[ast.Constant(value=1)], distinct=True),
            )

        def test_select_where(self):
            self.assertEqual(
                self._select("select 1 where true"),
                ast.SelectQuery(select=[ast.Constant(value=1)], where=ast.Constant(value=True)),
            )
            self.assertEqual(
                self._select("select 1 where 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                ),
            )

        def test_select_prewhere(self):
            self.assertEqual(
                self._select("select 1 prewhere true"),
                ast.SelectQuery(select=[ast.Constant(value=1)], prewhere=ast.Constant(value=True)),
            )
            self.assertEqual(
                self._select("select 1 prewhere 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    prewhere=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                ),
            )

        def test_select_having(self):
            self.assertEqual(
                self._select("select 1 having true"),
                ast.SelectQuery(select=[ast.Constant(value=1)], having=ast.Constant(value=True)),
            )
            self.assertEqual(
                self._select("select 1 having 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    having=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                ),
            )

        def test_select_qualify(self):
            self.assertEqual(
                self._select("select 1 qualify true"),
                ast.SelectQuery(select=[ast.Constant(value=1)], qualify=ast.Constant(value=True)),
            )
            self.assertEqual(
                self._select("select 1 qualify 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    qualify=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                ),
            )

        def test_select_qualify_with_having(self):
            self.assertEqual(
                self._select("select 1 having true qualify 1 == 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    having=ast.Constant(value=True),
                    qualify=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                ),
            )

        def test_select_complex_wheres(self):
            self.assertEqual(
                self._select("select 1 prewhere 2 != 3 where 1 == 2 having 'string' like '%a%'"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value=2),
                    ),
                    prewhere=ast.CompareOperation(
                        op=ast.CompareOperationOp.NotEq,
                        left=ast.Constant(value=2),
                        right=ast.Constant(value=3),
                    ),
                    having=ast.CompareOperation(
                        op=ast.CompareOperationOp.Like,
                        left=ast.Constant(value="string"),
                        right=ast.Constant(value="%a%"),
                    ),
                ),
            )

        def test_select_from(self):
            self.assertEqual(
                self._select("select 1 from events"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events as e"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events as e (event_alias, ts_alias)"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        alias="e",
                        column_aliases=["event_alias", "ts_alias"],
                    ),
                ),
            )
            self.assertEqual(
                self._select("select * exclude (first_name) from customers"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(all_columns=True, exclude=["first_name"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["customers"])),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events e"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
                ),
            )
            # `TableExprAlias` is left-recursive, so a table can carry a
            # chain of implicit aliases — the last one wins.
            self.assertEqual(
                self._select("select 1 from events e1 e2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e2"),
                ),
            )
            self.assertEqual(
                self._select("select 1 from complex.table"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"])),
                ),
            )
            self.assertEqual(
                self._select("select 1 from complex.table as a"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"]), alias="a"),
                ),
            )
            self.assertEqual(
                self._select("select 1 from complex.table a"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["complex", "table"]), alias="a"),
                ),
            )
            self.assertEqual(
                self._select("select 1 from (select 1 from events)"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.SelectQuery(
                            select=[ast.Constant(value=1)],
                            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                        )
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from (select 1 from events) as sq"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.SelectQuery(
                            select=[ast.Constant(value=1)],
                            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                        ),
                        alias="sq",
                    ),
                ),
            )

        def test_select_replace_columns(self):
            self.assertEqual(
                self._select("select (* replace (1 as event)) from events"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(all_columns=True, replace={"event": ast.Constant(value=1)})],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_select_columns_quoted_exclude(self):
            # Quoted identifiers inside an exclude list must be unquoted, matching the cpp parser.
            self.assertEqual(
                self._select('select * exclude ("first name") from customers'),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(all_columns=True, exclude=["first name"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["customers"])),
                ),
            )

        def test_ignore_nulls_expr(self):
            self.assertEqual(
                self._expr("event IGNORE NULLS"),
                ast.Field(chain=["event"]),
            )
            self.assertEqual(
                self._select("select event IGNORE NULLS from events"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["event"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_select_columns_qualified(self):
            self.assertEqual(
                self._select("select COLUMNS(events.*) from events"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(columns=[ast.Field(chain=["events", "*"])])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("select COLUMNS(events.* EXCLUDE (event)) from events"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(columns=[ast.ColumnsExpr(all_columns=True, exclude=["event"])])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("select COLUMNS(events.* REPLACE (1 as event)) from events"),
                ast.SelectQuery(
                    select=[ast.ColumnsExpr(all_columns=True, replace={"event": ast.Constant(value=1)})],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("select COLUMNS(events.* EXCLUDE (event) REPLACE (1 as event)) from events"),
                ast.SelectQuery(
                    select=[
                        ast.ColumnsExpr(
                            all_columns=True,
                            exclude=["event"],
                            replace={"event": ast.Constant(value=1)},
                        )
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_select_from_placeholder(self):
            self.assertEqual(
                self._select("select 1 from {placeholder}"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Placeholder(expr=ast.Field(chain=["placeholder"]))),
                ),
            )
            self.assertEqual(
                self._select(
                    "select 1 from {placeholder}",
                    {"placeholder": ast.Field(chain=["events"])},
                ),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_select_from_join(self):
            self.assertEqual(
                self._select("select 1 from events JOIN events2 ON 1"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="JOIN",
                            table=ast.Field(chain=["events2"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select * from events LEFT OUTER JOIN events2 ON 1"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="LEFT OUTER JOIN",
                            table=ast.Field(chain=["events2"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LEFT OUTER JOIN events2 ON 1 ANY RIGHT JOIN events3 ON 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="LEFT OUTER JOIN",
                            table=ast.Field(chain=["events2"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                            next_join=ast.JoinExpr(
                                join_type="RIGHT ANY JOIN",
                                table=ast.Field(chain=["events3"]),
                                constraint=ast.JoinConstraint(expr=ast.Constant(value=2), constraint_type="ON"),
                            ),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events JOIN events2 USING 1"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="JOIN",
                            table=ast.Field(chain=["events2"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="USING"),
                        ),
                    ),
                ),
            )

        def test_select_from_table_function_join(self):
            # Regression: TableFunctionExpr produced a JoinExpr without next_join,
            # causing chainJoinExprs to throw "JoinExpr is missing 'next_join' field"
            self.assertEqual(
                self._select("select 1 from numbers(10) JOIN events ON 1"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["numbers"]),
                        table_args=[ast.Constant(value=10)],
                        next_join=ast.JoinExpr(
                            join_type="JOIN",
                            table=ast.Field(chain=["events"]),
                            constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from numbers(10) CROSS JOIN events"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["numbers"]),
                        table_args=[ast.Constant(value=10)],
                        next_join=ast.JoinExpr(
                            join_type="CROSS JOIN",
                            table=ast.Field(chain=["events"]),
                        ),
                    ),
                ),
            )

        def test_select_from_join_multiple(self):
            node = self._select(
                """
                SELECT event, timestamp, e.distinct_id, p.id, p.properties.email
                FROM events e
                LEFT JOIN person_distinct_id pdi
                ON pdi.distinct_id = e.distinct_id
                LEFT JOIN persons p
                ON p.id = pdi.person_id
                """,
                self.team,
            )
            self.assertEqual(
                node,
                ast.SelectQuery(
                    select=[
                        ast.Field(chain=["event"]),
                        ast.Field(chain=["timestamp"]),
                        ast.Field(chain=["e", "distinct_id"]),
                        ast.Field(chain=["p", "id"]),
                        ast.Field(chain=["p", "properties", "email"]),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        alias="e",
                        next_join=ast.JoinExpr(
                            join_type="LEFT JOIN",
                            table=ast.Field(chain=["person_distinct_id"]),
                            alias="pdi",
                            constraint=ast.JoinConstraint(
                                expr=ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["pdi", "distinct_id"]),
                                    right=ast.Field(chain=["e", "distinct_id"]),
                                ),
                                constraint_type="ON",
                            ),
                            next_join=ast.JoinExpr(
                                join_type="LEFT JOIN",
                                table=ast.Field(chain=["persons"]),
                                alias="p",
                                constraint=ast.JoinConstraint(
                                    expr=ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["p", "id"]),
                                        right=ast.Field(chain=["pdi", "person_id"]),
                                    ),
                                    constraint_type="ON",
                                ),
                            ),
                        ),
                    ),
                ),
            )

        def test_select_from_cross_join(self):
            self.assertEqual(
                self._select("select 1 from events CROSS JOIN events2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="CROSS JOIN",
                            table=ast.Field(chain=["events2"]),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events CROSS JOIN events2 CROSS JOIN events3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="CROSS JOIN",
                            table=ast.Field(chain=["events2"]),
                            next_join=ast.JoinExpr(
                                join_type="CROSS JOIN",
                                table=ast.Field(chain=["events3"]),
                            ),
                        ),
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events, events2 CROSS JOIN events3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="CROSS JOIN",
                            table=ast.Field(chain=["events2"]),
                            next_join=ast.JoinExpr(
                                join_type="CROSS JOIN",
                                table=ast.Field(chain=["events3"]),
                            ),
                        ),
                    ),
                ),
            )

        def test_select_array_join(self):
            self.assertEqual(
                self._select("select a from events ARRAY JOIN [1,2,3] as a"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["a"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    array_join_op="ARRAY JOIN",
                    array_join_list=[
                        ast.Alias(
                            expr=ast.Array(
                                exprs=[
                                    ast.Constant(value=1),
                                    ast.Constant(value=2),
                                    ast.Constant(value=3),
                                ]
                            ),
                            alias="a",
                        )
                    ],
                ),
            )
            self.assertEqual(
                self._select("select a from events INNER ARRAY JOIN [1,2,3] as a"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["a"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    array_join_op="INNER ARRAY JOIN",
                    array_join_list=[
                        ast.Alias(
                            expr=ast.Array(
                                exprs=[
                                    ast.Constant(value=1),
                                    ast.Constant(value=2),
                                    ast.Constant(value=3),
                                ]
                            ),
                            alias="a",
                        )
                    ],
                ),
            )
            self.assertEqual(
                self._select("select 1, b from events LEFT ARRAY JOIN [1,2,3] as a, [4,5,6] AS b"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1), ast.Field(chain=["b"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    array_join_op="LEFT ARRAY JOIN",
                    array_join_list=[
                        ast.Alias(
                            expr=ast.Array(
                                exprs=[
                                    ast.Constant(value=1),
                                    ast.Constant(value=2),
                                    ast.Constant(value=3),
                                ]
                            ),
                            alias="a",
                        ),
                        ast.Alias(
                            expr=ast.Array(
                                exprs=[
                                    ast.Constant(value=4),
                                    ast.Constant(value=5),
                                    ast.Constant(value=6),
                                ]
                            ),
                            alias="b",
                        ),
                    ],
                ),
            )

        def test_select_array_join_errors(self):
            with self.assertRaises(ExposedHogQLError) as e:
                self._select("select a from events ARRAY JOIN [1,2,3]")
            self.assertEqual(str(e.exception), "ARRAY JOIN arrays must have an alias")
            self.assertEqual(e.exception.start, 32)
            self.assertEqual(e.exception.end, 39)

            with self.assertRaises(ExposedHogQLError) as e:
                self._select("select a ARRAY JOIN [1,2,3]")
            self.assertEqual(
                str(e.exception),
                "Using ARRAY JOIN without a FROM clause is not permitted",
            )
            self.assertEqual(e.exception.start, 0)
            self.assertEqual(e.exception.end, 27)

        def test_select_group_by(self):
            self.assertEqual(
                self._select("select 1 from events GROUP BY 1, event"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    group_by=[ast.Constant(value=1), ast.Field(chain=["event"])],
                ),
            )

        def test_select_group_by_all(self):
            self.assertEqual(
                self._select("select distinct_id, event, count(*) from events GROUP BY ALL"),
                ast.SelectQuery(
                    select=[
                        ast.Field(chain=["distinct_id"]),
                        ast.Field(chain=["event"]),
                        ast.Call(name="count", args=[ast.Field(chain=["*"])]),
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    group_by=None,
                    group_by_mode="all",
                ),
            )

        @parameterized.expand(
            [
                (
                    "count_cast_with_as",
                    "select count(*)::int as num_events from active_events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="num_events",
                                expr=ast.TypeCast(
                                    expr=ast.Call(name="count", args=[ast.Field(chain=["*"])]),
                                    type_name="int",
                                ),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["active_events"])),
                    ),
                ),
                (
                    "paren_count_cast_without_as",
                    "select (count(*))::int num_events from active_events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="num_events",
                                expr=ast.TypeCast(
                                    expr=ast.Call(name="count", args=[ast.Field(chain=["*"])]),
                                    type_name="int",
                                ),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["active_events"])),
                    ),
                ),
                (
                    "qualified_field_cast",
                    "select e.event::text as event_name from events e",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="event_name",
                                expr=ast.TypeCast(expr=ast.Field(chain=["e", "event"]), type_name="text"),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
                    ),
                ),
                (
                    "compound_type_cast",
                    "select now()::timestamp with time zone as ts from events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="ts",
                                expr=ast.TypeCast(
                                    expr=ast.Call(name="now", args=[]),
                                    type_name="timestamp with time zone",
                                ),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    ),
                ),
                (
                    "interval_cast",
                    "select 1::interval as i from events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="i",
                                expr=ast.TypeCast(expr=ast.Constant(value=1), type_name="interval"),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    ),
                ),
                (
                    "int_cast_with_as",
                    "select 1::int as value",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="value",
                                expr=ast.TypeCast(expr=ast.Constant(value=1), type_name="int"),
                            )
                        ],
                    ),
                ),
                (
                    "literal_cast",
                    "select '123'::int as x from events",
                    ast.SelectQuery(
                        select=[
                            ast.Alias(
                                alias="x",
                                expr=ast.TypeCast(expr=ast.Constant(value="123"), type_name="int"),
                            )
                        ],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    ),
                ),
            ]
        )
        def test_type_cast_alias_parsing(self, _, query, expected):
            self.assertEqual(self._select(query), expected)

        @parameterized.expand(
            [
                ("with_alone", "select 1::with"),
                ("zone_alone", "select 1::zone"),
                ("local_alone", "select 1::local"),
            ]
        )
        def test_type_cast_rejects_partial_with_time_zone_keywords(self, _, query):
            with self.assertRaises(SyntaxError):
                self._select(query)

        def test_order_by(self):
            self.assertEqual(
                parse_order_expr("1 ASC"),
                ast.OrderExpr(
                    expr=ast.Constant(value=1, start=0, end=1),
                    order="ASC",
                    start=0,
                    end=5,
                ),
            )
            self.assertEqual(
                parse_order_expr("event"),
                ast.OrderExpr(
                    expr=ast.Field(chain=["event"], start=0, end=5),
                    order="ASC",
                    start=0,
                    end=5,
                ),
            )
            self.assertEqual(
                parse_order_expr("timestamp DESC"),
                ast.OrderExpr(
                    expr=ast.Field(chain=["timestamp"], start=0, end=9),
                    order="DESC",
                    start=0,
                    end=14,
                ),
            )
            # Note that the parser will skip anything after `--`, so the `DESC` behind will not be parsed
            self.assertEqual(
                parse_order_expr("timestamp -- a comment DESC"),
                ast.OrderExpr(
                    expr=ast.Field(chain=["timestamp"], start=0, end=9),
                    order="ASC",
                    start=0,
                    end=9,
                ),
            )

        def test_order_by_with_fill(self):
            self.assertEqual(
                clear_locations(parse_order_expr("timestamp WITH FILL", backend=backend)),
                ast.OrderExpr(
                    expr=ast.Field(chain=["timestamp"]),
                    order="ASC",
                    with_fill=ast.WithFillExpr(),
                ),
            )
            self.assertEqual(
                clear_locations(parse_order_expr("timestamp WITH FILL FROM 1 TO 10 STEP 2", backend=backend)),
                ast.OrderExpr(
                    expr=ast.Field(chain=["timestamp"]),
                    order="ASC",
                    with_fill=ast.WithFillExpr(
                        from_value=ast.Constant(value=1),
                        to_value=ast.Constant(value=10),
                        step_value=ast.Constant(value=2),
                    ),
                ),
            )
            self.assertEqual(
                clear_locations(parse_order_expr("timestamp DESC WITH FILL FROM 0 TO 100", backend=backend)),
                ast.OrderExpr(
                    expr=ast.Field(chain=["timestamp"]),
                    order="DESC",
                    with_fill=ast.WithFillExpr(
                        from_value=ast.Constant(value=0),
                        to_value=ast.Constant(value=100),
                    ),
                ),
            )
            self.assertEqual(
                clear_locations(parse_order_expr("timestamp WITH FILL STEP 1", backend=backend)),
                ast.OrderExpr(
                    expr=ast.Field(chain=["timestamp"]),
                    order="ASC",
                    with_fill=ast.WithFillExpr(
                        step_value=ast.Constant(value=1),
                    ),
                ),
            )

        def test_select_order_by_with_fill(self):
            self.assertEqual(
                self._select("select 1 from events ORDER BY timestamp WITH FILL FROM 0 TO 10 STEP 1"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[
                        ast.OrderExpr(
                            expr=ast.Field(chain=["timestamp"]),
                            order="ASC",
                            with_fill=ast.WithFillExpr(
                                from_value=ast.Constant(value=0),
                                to_value=ast.Constant(value=10),
                                step_value=ast.Constant(value=1),
                            ),
                        ),
                    ],
                ),
            )

        def test_select_order_by_with_fill_and_interpolate(self):
            self.assertEqual(
                self._select("select x, y from events ORDER BY x WITH FILL FROM 0 TO 10 STEP 1 INTERPOLATE (y AS 0)"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["x"]), ast.Field(chain=["y"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[
                        ast.OrderExpr(
                            expr=ast.Field(chain=["x"]),
                            order="ASC",
                            with_fill=ast.WithFillExpr(
                                from_value=ast.Constant(value=0),
                                to_value=ast.Constant(value=10),
                                step_value=ast.Constant(value=1),
                            ),
                        ),
                    ],
                    interpolate=[
                        ast.InterpolateExpr(
                            expr=ast.Field(chain=["y"]),
                            value=ast.Constant(value=0),
                        ),
                    ],
                ),
            )

        def test_select_order_by_with_fill_and_naked_interpolate(self):
            self.assertEqual(
                self._select("select x, y from events ORDER BY x WITH FILL FROM 0 TO 10 STEP 1 INTERPOLATE"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["x"]), ast.Field(chain=["y"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[
                        ast.OrderExpr(
                            expr=ast.Field(chain=["x"]),
                            order="ASC",
                            with_fill=ast.WithFillExpr(
                                from_value=ast.Constant(value=0),
                                to_value=ast.Constant(value=10),
                                step_value=ast.Constant(value=1),
                            ),
                        ),
                    ],
                    interpolate=[],
                ),
            )

        def test_select_order_by_with_fill_and_interpolate_no_as(self):
            self.assertEqual(
                self._select("select x, y from events ORDER BY x WITH FILL FROM 0 TO 10 STEP 1 INTERPOLATE (y)"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["x"]), ast.Field(chain=["y"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[
                        ast.OrderExpr(
                            expr=ast.Field(chain=["x"]),
                            order="ASC",
                            with_fill=ast.WithFillExpr(
                                from_value=ast.Constant(value=0),
                                to_value=ast.Constant(value=10),
                                step_value=ast.Constant(value=1),
                            ),
                        ),
                    ],
                    interpolate=[
                        ast.InterpolateExpr(
                            expr=ast.Field(chain=["y"]),
                        ),
                    ],
                ),
            )

        def test_select_order_by(self):
            self.assertEqual(
                self._select("select 1 from events ORDER BY 1 ASC, event, timestamp DESC"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[
                        ast.OrderExpr(expr=ast.Constant(value=1), order="ASC"),
                        ast.OrderExpr(expr=ast.Field(chain=["event"]), order="ASC"),
                        ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC"),
                    ],
                ),
            )

        def test_select_limit_offset(self):
            self.assertEqual(
                self._select("select 1 from events LIMIT 1"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=1),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 %"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=1),
                    limit_percent=True,
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT (60 + 7) %"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Add,
                        left=ast.Constant(value=60),
                        right=ast.Constant(value=7),
                    ),
                    limit_percent=True,
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT (select avg(team_id) from events) %"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.SelectQuery(
                        select=[ast.Call(name="avg", args=[ast.Field(chain=["team_id"])])],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    ),
                    limit_percent=True,
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 OFFSET 3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=1),
                    offset=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 % OFFSET 3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=1),
                    limit_percent=True,
                    offset=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 42% OFFSET 20"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=42),
                    limit_percent=True,
                    offset=ast.Constant(value=20),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events OFFSET 3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=None,
                    offset=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events ORDER BY 1 LIMIT 1 WITH TIES"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[ast.OrderExpr(expr=ast.Constant(value=1), order="ASC")],
                    limit=ast.Constant(value=1),
                    limit_with_ties=True,
                    offset=None,
                ),
            )
            self.assertEqual(
                self._select("select 1 from events ORDER BY 1 LIMIT 1, 3 WITH TIES"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    order_by=[ast.OrderExpr(expr=ast.Constant(value=1), order="ASC")],
                    limit=ast.Constant(value=1),
                    limit_with_ties=True,
                    offset=ast.Constant(value=3),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 BY event LIMIT 2 OFFSET 3"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=2),
                    offset=ast.Constant(value=3),
                    limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["event"])]),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 OFFSET 4 BY event LIMIT 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=2),
                    limit_by=ast.LimitByExpr(
                        n=ast.Constant(value=1), offset_value=ast.Constant(value=4), exprs=[ast.Field(chain=["event"])]
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 4, 1 BY event LIMIT 2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=2),
                    limit_by=ast.LimitByExpr(
                        n=ast.Constant(value=1), offset_value=ast.Constant(value=4), exprs=[ast.Field(chain=["event"])]
                    ),
                ),
            )
            self.assertEqual(
                self._select("select 1 from events LIMIT 1 OFFSET 4 BY event LIMIT 2 OFFSET 5"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                    limit=ast.Constant(value=2),
                    offset=ast.Constant(value=5),
                    limit_by=ast.LimitByExpr(
                        n=ast.Constant(value=1), offset_value=ast.Constant(value=4), exprs=[ast.Field(chain=["event"])]
                    ),
                ),
            )

        def test_select_set_level_limit_offset_divergences(self):
            # Set-level LIMIT/OFFSET on a SelectSetQuery initial query — Python dropped both. C++ was already correct.
            parsed = self._select("((select 1) intersect (select 2)) limit 3, 4")
            assert isinstance(parsed, ast.SelectSetQuery)
            self.assertEqual(parsed.limit, ast.Constant(value=3))
            self.assertEqual(parsed.offset, ast.Constant(value=4))

            # A bare outer `LIMIT n` must not clobber an existing inner OFFSET.
            parsed = self._select("(select 1 offset 5) limit 3")
            assert isinstance(parsed, ast.SelectQuery)
            self.assertEqual(parsed.limit, ast.Constant(value=3))
            self.assertEqual(parsed.offset, ast.Constant(value=5))

            # A placeholder select body has no node to carry a set-level LIMIT/OFFSET, so both backends drop the clause.
            placeholder = ast.Placeholder(expr=ast.Field(chain=["foo"]))
            for query in ("{foo} offset 1", "{foo} limit 2", "{foo} limit 2 offset 3"):
                with self.subTest(query=query):
                    self.assertEqual(self._select(query), placeholder)

        def test_select_placeholders(self):
            self.assertEqual(
                self._select("select 1 where 1 == {hogql_val_1}"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Placeholder(expr=ast.Field(chain=["hogql_val_1"])),
                    ),
                ),
            )
            self.assertEqual(
                self._select(
                    "select 1 where 1 == {hogql_val_1}",
                    {"hogql_val_1": ast.Constant(value="bar")},
                ),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Constant(value="bar"),
                    ),
                ),
            )

        def test_placeholder_expressions(self):
            actual = self._select("select 1 where 1 == {1 ? hogql_val_1 : hogql_val_2}")
            expected = clear_locations(
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    where=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Constant(value=1),
                        right=ast.Placeholder(
                            expr=ast.Call(
                                name="if",
                                args=[
                                    ast.Constant(value=1),
                                    ast.Field(chain=["hogql_val_1"]),
                                    ast.Field(chain=["hogql_val_2"]),
                                ],
                            )
                        ),
                    ),
                )
            )
            self.assertEqual(actual, expected)

        def test_select_union_all(self):
            self.assertEqual(
                self._select("select 1 union all select 2 union all select 3"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
                    subsequent_select_queries=[
                        SelectSetNode(set_operator="UNION ALL", select_query=query)
                        for query in (
                            ast.SelectQuery(select=[ast.Constant(value=2)]),
                            ast.SelectQuery(select=[ast.Constant(value=3)]),
                        )
                    ],
                ),
            )

        def test_select_intersect_all(self):
            self.assertEqual(
                self._select("select 1 intersect all select 2"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
                    subsequent_select_queries=[
                        SelectSetNode(
                            set_operator="INTERSECT ALL",
                            select_query=ast.SelectQuery(select=[ast.Constant(value=2)]),
                        )
                    ],
                ),
            )

        def test_select_except_all(self):
            self.assertEqual(
                self._select("select 1 except all select 2"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
                    subsequent_select_queries=[
                        SelectSetNode(
                            set_operator="EXCEPT ALL",
                            select_query=ast.SelectQuery(select=[ast.Constant(value=2)]),
                        )
                    ],
                ),
            )

        def test_select_set_order_by(self):
            self.assertEqual(
                self._select("select 1 union all select 2 order by 1"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(select=[ast.Constant(value=1)]),
                    subsequent_select_queries=[
                        SelectSetNode(
                            set_operator="UNION ALL",
                            select_query=ast.SelectQuery(
                                select=[ast.Constant(value=2)],
                                order_by=[ast.OrderExpr(expr=ast.Constant(value=1), order="ASC")],
                            ),
                        )
                    ],
                ),
            )

        @parameterized.expand(
            [
                ("union by name", "UNION DISTINCT BY NAME"),
                ("union all by name", "UNION ALL BY NAME"),
                ("union distinct by name", "UNION DISTINCT BY NAME"),
            ]
        )
        def test_select_union_by_name(self, sql_operator, expected_operator):
            self.assertEqual(
                self._select(f"select 1 as a, 2 as b {sql_operator} select 3 as b, 4 as a"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(
                        select=[
                            ast.Alias(alias="a", expr=ast.Constant(value=1)),
                            ast.Alias(alias="b", expr=ast.Constant(value=2)),
                        ]
                    ),
                    subsequent_select_queries=[
                        SelectSetNode(
                            set_operator=expected_operator,
                            select_query=ast.SelectQuery(
                                select=[
                                    ast.Alias(alias="b", expr=ast.Constant(value=3)),
                                    ast.Alias(alias="a", expr=ast.Constant(value=4)),
                                ]
                            ),
                        )
                    ],
                ),
            )

        def test_nested_selects(self):
            self.assertEqual(
                self._select("(select 1 intersect select 2) union all (select 3 except select 4)"),
                SelectSetQuery(
                    initial_select_query=SelectSetQuery(
                        initial_select_query=SelectQuery(select=[Constant(value=1)]),
                        subsequent_select_queries=[
                            SelectSetNode(
                                select_query=SelectQuery(
                                    select=[Constant(value=2)],
                                ),
                                set_operator="INTERSECT",
                            )
                        ],
                    ),
                    subsequent_select_queries=[
                        SelectSetNode(
                            select_query=SelectSetQuery(
                                initial_select_query=SelectQuery(
                                    select=[Constant(value=3)],
                                ),
                                subsequent_select_queries=[
                                    SelectSetNode(
                                        select_query=SelectQuery(select=[Constant(value=4)]), set_operator="EXCEPT"
                                    )
                                ],
                            ),
                            set_operator="UNION ALL",
                        )
                    ],
                ),
            )

        def test_sample_clause(self):
            self.assertEqual(
                self._select("select 1 from events sample 1/10 offset 999"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        sample=ast.SampleExpr(
                            offset_value=ast.RatioExpr(left=ast.Constant(value=999)),
                            sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=10)),
                        ),
                    ),
                ),
            )

            self.assertEqual(
                self._select("select 1 from events sample 0.1 offset 999"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        sample=ast.SampleExpr(
                            offset_value=ast.RatioExpr(left=ast.Constant(value=999)),
                            sample_value=ast.RatioExpr(
                                left=ast.Constant(value=0.1),
                            ),
                        ),
                    ),
                ),
            )

            self.assertEqual(
                self._select("select 1 from events sample 10 offset 1/2"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        sample=ast.SampleExpr(
                            offset_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=2)),
                            sample_value=ast.RatioExpr(
                                left=ast.Constant(value=10),
                            ),
                        ),
                    ),
                ),
            )

            self.assertEqual(
                self._select("select 1 from events sample 10"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        sample=ast.SampleExpr(
                            sample_value=ast.RatioExpr(
                                left=ast.Constant(value=10),
                            ),
                        ),
                    ),
                ),
            )

        def test_select_with_columns(self):
            self.assertEqual(
                self._select("with event as boo select boo from events"),
                ast.SelectQuery(
                    ctes={
                        "boo": ast.CTE(
                            name="boo",
                            expr=ast.Field(chain=["event"]),
                            cte_type="column",
                        )
                    },
                    select=[ast.Field(chain=["boo"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )
            self.assertEqual(
                self._select("with count() as kokku select kokku from events"),
                ast.SelectQuery(
                    ctes={
                        "kokku": ast.CTE(
                            name="kokku",
                            expr=ast.Call(name="count", args=[]),
                            cte_type="column",
                        )
                    },
                    select=[ast.Field(chain=["kokku"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_select_with_subqueries(self):
            self.assertEqual(
                self._select("with customers as (select 'yes' from events) select * from customers"),
                ast.SelectQuery(
                    ctes={
                        "customers": ast.CTE(
                            name="customers",
                            expr=ast.SelectQuery(
                                select=[ast.Constant(value="yes")],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                            ),
                            cte_type="subquery",
                        )
                    },
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["customers"])),
                ),
            )

        def test_select_with_mixed(self):
            self.assertEqual(
                self._select("with happy as (select 'yes' from events), ':(' as sad select sad from happy"),
                ast.SelectQuery(
                    ctes={
                        "happy": ast.CTE(
                            name="happy",
                            expr=ast.SelectQuery(
                                select=[ast.Constant(value="yes")],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                            ),
                            cte_type="subquery",
                        ),
                        "sad": ast.CTE(name="sad", expr=ast.Constant(value=":("), cte_type="column"),
                    },
                    select=[ast.Field(chain=["sad"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["happy"])),
                ),
            )

        def test_ctes_preserve_declaration_order(self):
            node = cast(
                ast.SelectQuery,
                self._select(
                    "with zz_first as (select 1 from events), "
                    "mm_middle as (select * from zz_first), "
                    "aa_last as (select * from mm_middle) "
                    "select * from aa_last"
                ),
            )
            assert isinstance(node.ctes, dict)
            self.assertEqual(list(node.ctes.keys()), ["zz_first", "mm_middle", "aa_last"])

        def test_ctes_subquery_recursion(self):
            query = "with users as (select event, timestamp as tt from events ), final as ( select tt from users ) select * from final"
            self.assertEqual(
                self._select(query),
                ast.SelectQuery(
                    ctes={
                        "users": ast.CTE(
                            name="users",
                            expr=ast.SelectQuery(
                                select=[
                                    ast.Field(chain=["event"]),
                                    ast.Alias(alias="tt", expr=ast.Field(chain=["timestamp"])),
                                ],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                            ),
                            cte_type="subquery",
                        ),
                        "final": ast.CTE(
                            name="final",
                            expr=ast.SelectQuery(
                                select=[ast.Field(chain=["tt"])],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["users"])),
                            ),
                            cte_type="subquery",
                        ),
                    },
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["final"])),
                ),
            )

        def test_case_when(self):
            self.assertEqual(
                self._expr("case when 1 then 2 else 3 end"),
                ast.Call(
                    name="if",
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                        ast.Constant(value=3),
                    ],
                ),
            )

        def test_case_when_many(self):
            self.assertEqual(
                self._expr("case when 1 then 2 when 3 then 4 else 5 end"),
                ast.Call(
                    name="multiIf",
                    args=[
                        ast.Constant(value=1),
                        ast.Constant(value=2),
                        ast.Constant(value=3),
                        ast.Constant(value=4),
                        ast.Constant(value=5),
                    ],
                ),
            )

        def test_case_when_case(self):
            self.assertEqual(
                self._expr("case 0 when 1 then 2 when 3 then 4 else 5 end"),
                ast.Call(
                    name="transform",
                    args=[
                        ast.Constant(value=0),
                        ast.Array(exprs=[ast.Constant(value=1), ast.Constant(value=3)]),
                        ast.Array(exprs=[ast.Constant(value=2), ast.Constant(value=4)]),
                        ast.Constant(value=5),
                    ],
                ),
            )

        def test_window_functions(self):
            query = "SELECT person.id, min(timestamp) over (PARTITION by person.id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS timestamp FROM events"
            expr = self._select(query)
            expected = ast.SelectQuery(
                select=[
                    ast.Field(chain=["person", "id"]),
                    ast.Alias(
                        alias="timestamp",
                        expr=ast.WindowFunction(
                            name="min",
                            exprs=[ast.Field(chain=["timestamp"])],
                            over_expr=ast.WindowExpr(
                                partition_by=[ast.Field(chain=["person", "id"])],
                                order_by=[
                                    ast.OrderExpr(
                                        expr=ast.Field(chain=["timestamp"]),
                                        order="DESC",
                                    )
                                ],
                                frame_method="ROWS",
                                frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=None),
                                frame_end=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=1),
                            ),
                        ),
                    ),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            )
            self.assertEqual(expr, expected)

        def test_window_functions_call_arg(self):
            query = "SELECT quantiles(0.0, 0.25, 0.5, 0.75, 1.0)(distinct distinct_id) over () as values FROM events"
            expr = self._select(query)
            expected = ast.SelectQuery(
                select=[
                    ast.Alias(
                        alias="values",
                        expr=ast.WindowFunction(
                            name="quantiles",
                            args=[ast.Field(chain=["distinct_id"])],
                            exprs=[
                                ast.Constant(value=0.0),
                                ast.Constant(value=0.25),
                                ast.Constant(value=0.5),
                                ast.Constant(value=0.75),
                                ast.Constant(value=1.0),
                            ],
                            over_expr=ast.WindowExpr(),
                        ),
                        hidden=False,
                    )
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            )
            self.assertEqual(expr, expected)

        def test_window_functions_with_window(self):
            query = "SELECT person.id, min(timestamp) over win1 AS timestamp FROM events WINDOW win1 as (PARTITION by person.id ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)"
            expr = self._select(query)
            expected = ast.SelectQuery(
                select=[
                    ast.Field(chain=["person", "id"]),
                    ast.Alias(
                        alias="timestamp",
                        expr=ast.WindowFunction(
                            name="min",
                            exprs=[ast.Field(chain=["timestamp"])],
                            over_identifier="win1",
                        ),
                    ),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                window_exprs={
                    "win1": ast.WindowExpr(
                        partition_by=[ast.Field(chain=["person", "id"])],
                        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                        frame_method="ROWS",
                        frame_start=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=None),
                        frame_end=ast.WindowFrameExpr(frame_type="PRECEDING", frame_value=1),
                    )
                },
            )
            self.assertEqual(expr, expected)

        def test_reserved_keyword_alias_error(self):
            query = f"SELECT 0 AS trUE FROM events"
            with self.assertRaisesMessage(
                SyntaxError,
                '"trUE" cannot be an alias or identifier, as it\'s a reserved keyword',
            ) as e:
                self._select(query)
            self.assertEqual(e.exception.start, 7)
            self.assertEqual(e.exception.end, 16)

        def test_unquoted_reserved_keyword_alias_is_invalid(self):
            with self.assertRaises(SyntaxError):
                self._select("select 1 from")

        def test_quoted_reserved_keyword_identifier(self):
            self.assertEqual(
                self._select('select "from" from events'),
                ast.SelectQuery(
                    select=[ast.Field(chain=["from"])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        @parameterized.expand([["id"], ["name"], ["timestamp"], ["time"], ["date"], ["key"]])
        def test_non_reserved_keywords_can_be_used_as_identifiers(self, identifier: str):
            self.assertEqual(
                self._select(f"select {identifier} from events"),
                ast.SelectQuery(
                    select=[ast.Field(chain=[identifier])],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        def test_malformed_sql(self):
            query = "SELEC 2"
            with self.assertRaisesMessage(
                SyntaxError,
                "mismatched input 'SELEC' expecting {SELECT, WITH, '{', '(', '<'}",
            ) as e:
                self._select(query)
            self.assertEqual(e.exception.start, 0)
            self.assertEqual(e.exception.end, 7)

        def test_visit_hogqlx_tag(self):
            node = self._select("select event from <HogQLQuery query='select event from events' />")
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="HogQLQuery",
                attributes=[ast.HogQLXAttribute(name="query", value=ast.Constant(value="select event from events"))],
            )

            node2 = self._select("select event from (<HogQLQuery query='select event from events' />)")
            assert node2 == node

        def test_visit_hogqlx_tag_nested(self):
            # Basic case
            node = self._select(
                "select event from <OuterQuery><HogQLQuery query='select event from events' /></OuterQuery>"
            )
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="OuterQuery",
                attributes=[
                    ast.HogQLXAttribute(
                        name="children",
                        value=[
                            ast.HogQLXTag(
                                kind="HogQLQuery",
                                attributes=[
                                    ast.HogQLXAttribute(
                                        name="query", value=ast.Constant(value="select event from events")
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )

            # Empty tag
            node = self._select("select event from <OuterQuery></OuterQuery>")
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(kind="OuterQuery", attributes=[])

            # With attribute
            node = self._select(
                "select event from <OuterQuery q='b'><HogQLQuery query='select event from events' /></OuterQuery>"
            )
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="OuterQuery",
                attributes=[
                    ast.HogQLXAttribute(name="q", value=ast.Constant(value="b")),
                    ast.HogQLXAttribute(
                        name="children",
                        value=[
                            ast.HogQLXTag(
                                kind="HogQLQuery",
                                attributes=[
                                    ast.HogQLXAttribute(
                                        name="query", value=ast.Constant(value="select event from events")
                                    )
                                ],
                            )
                        ],
                    ),
                ],
            )

            # With mismatched closing tag
            with self.assertRaises(ExposedHogQLError) as e:
                self._select(
                    "select event from <OuterQuery q='b'><HogQLQuery query='select event from events' /></HogQLQuery>"
                )
            assert str(e.exception) == "Opening and closing HogQLX tags must match. Got OuterQuery and HogQLQuery"

            # With mismatched closing tag
            with self.assertRaises(ExposedHogQLError) as e:
                self._select(
                    "select event from <OuterQuery children='b'><HogQLQuery query='select event from events' /></OuterQuery>"
                )
            assert str(e.exception) == "Can't have a HogQLX tag with both children and a 'children' attribute"

        def test_visit_hogqlx_tag_alias(self):
            node = self._select("select event from <HogQLQuery query='select event from events' /> as a")
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            alias = node.select_from.alias
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="HogQLQuery",
                attributes=[ast.HogQLXAttribute(name="query", value=ast.Constant(value="select event from events"))],
            )
            assert alias == "a"

            node2 = self._select("select event from <HogQLQuery query='select event from events' /> a")
            assert node2 == node

        def test_visit_hogqlx_tag_source(self):
            query = """
                select id, email from (
                    <ActorsQuery
                        select={['id', 'properties.email as email']}
                        source={
                            <HogQLQuery query='select distinct person_id from events' />
                        }
                    />
                )
            """
            node = self._select(query)
            assert isinstance(node, ast.SelectQuery)
            assert isinstance(node.select_from, ast.JoinExpr)
            table_node = node.select_from.table
            assert isinstance(table_node, ast.HogQLXTag)
            assert table_node == ast.HogQLXTag(
                kind="ActorsQuery",
                attributes=[
                    ast.HogQLXAttribute(
                        name="select",
                        value=ast.Array(
                            exprs=[ast.Constant(value="id"), ast.Constant(value="properties.email as email")]
                        ),
                    ),
                    ast.HogQLXAttribute(
                        name="source",
                        value=ast.HogQLXTag(
                            kind="HogQLQuery",
                            attributes=[
                                ast.HogQLXAttribute(
                                    name="query", value=ast.Constant(value="select distinct person_id from events")
                                )
                            ],
                        ),
                    ),
                ],
            )

        def test_visit_hogqlx_tag_column_source(self):
            query = """
                select <a href='https://google.com'>{event}</a> from events
            """
            node = self._select(query)
            assert isinstance(node, ast.SelectQuery) and cast(ast.HogQLXTag, node.select[0]) == ast.HogQLXTag(
                kind="a",
                attributes=[
                    ast.HogQLXAttribute(name="href", value=Constant(value="https://google.com")),
                    ast.HogQLXAttribute(name="children", value=[ast.Field(chain=["event"])]),
                ],
            )

        def test_visit_hogqlx_multiple_children(self):
            query = """
                select <a href='https://google.com'>{event}<b>{'Bold!'}</b></a> from events
            """
            node = self._select(query)
            assert isinstance(node, ast.SelectQuery) and cast(ast.HogQLXTag, node.select[0]) == ast.HogQLXTag(
                kind="a",
                attributes=[
                    ast.HogQLXAttribute(name="href", value=Constant(value="https://google.com")),
                    ast.HogQLXAttribute(
                        name="children",
                        value=[
                            ast.Field(chain=["event"]),
                            ast.HogQLXTag(
                                kind="b",
                                attributes=[
                                    ast.HogQLXAttribute(name="children", value=[ast.Constant(value="Bold!")]),
                                ],
                            ),
                        ],
                    ),
                ],
            )

        def test_visit_hogqlx_text_only_child(self):
            """A tag with a single plain-text child should be turned into
            a Constant wrapped in the auto-injected `children` attribute."""
            node = self._select("select <span>Hello World</span> from events")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])
            self.assertEqual(
                tag,
                ast.HogQLXTag(
                    kind="span",
                    attributes=[
                        ast.HogQLXAttribute(
                            name="children",
                            value=[ast.Constant(value="Hello World")],
                        )
                    ],
                ),
            )

        def test_visit_hogqlx_text_and_expr_children(self):
            """Mixed text + expression children must keep ordering:
            Constant('Hello')  →  Field(event)."""
            node = self._select("select <span>Hello {event}</span> from events")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])
            self.assertEqual(
                tag,
                ast.HogQLXTag(
                    kind="span",
                    attributes=[
                        ast.HogQLXAttribute(
                            name="children",
                            value=[
                                ast.Constant(value="Hello "),
                                ast.Field(chain=["event"]),
                            ],
                        )
                    ],
                ),
            )

        # 1. <strong>hello world <strong>banana</strong></strong>
        def test_visit_hogqlx_nested_tags(self) -> None:
            node = self._select("select <strong>hello world <strong>banana</strong></strong>")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])

            self.assertEqual(
                tag,
                ast.HogQLXTag(
                    kind="strong",
                    attributes=[
                        ast.HogQLXAttribute(
                            name="children",
                            value=[
                                ast.Constant(value="hello world "),
                                ast.HogQLXTag(
                                    kind="strong",
                                    attributes=[
                                        ast.HogQLXAttribute(
                                            name="children",
                                            value=[ast.Constant(value="banana")],
                                        )
                                    ],
                                ),
                            ],
                        )
                    ],
                ),
            )

        # 2. <em />
        def test_visit_hogqlx_self_closing(self) -> None:
            node = self._select("select <em /> from events")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])

            # A self-closing element has no “children” attribute at all.
            self.assertEqual(tag, ast.HogQLXTag(kind="em", attributes=[]))

        # 3. <strong>{event} <em>asd</em></strong>
        def test_visit_hogqlx_expr_text_and_tag_children(self) -> None:
            node = self._select("select <strong>{event} <em>asd</em></strong> from events")
            assert isinstance(node, ast.SelectQuery)
            tag = cast(ast.HogQLXTag, node.select[0])

            self.assertEqual(
                tag,
                ast.HogQLXTag(
                    kind="strong",
                    attributes=[
                        ast.HogQLXAttribute(
                            name="children",
                            value=[
                                ast.Field(chain=["event"]),
                                ast.Constant(value=" "),
                                ast.HogQLXTag(
                                    kind="em",
                                    attributes=[
                                        ast.HogQLXAttribute(
                                            name="children",
                                            value=[ast.Constant(value="asd")],
                                        )
                                    ],
                                ),
                            ],
                        )
                    ],
                ),
            )

        # 4. <strong><a href="…">Hello <em>{event}</em></a>{'a'}</strong>
        def test_visit_hogqlx_mixed_nested_attributes(self) -> None:
            node = self._select(
                "select <strong><a href='https://google.com'>Hello <em>{event}</em></a>{'a'}</strong> from events"
            )
            assert isinstance(node, ast.SelectQuery)
            outer = cast(ast.HogQLXTag, node.select[0])

            expected = ast.HogQLXTag(
                kind="strong",
                attributes=[
                    ast.HogQLXAttribute(
                        name="children",
                        value=[
                            ast.HogQLXTag(
                                kind="a",
                                attributes=[
                                    ast.HogQLXAttribute(
                                        name="href",
                                        value=ast.Constant(value="https://google.com"),
                                    ),
                                    ast.HogQLXAttribute(
                                        name="children",
                                        value=[
                                            ast.Constant(value="Hello "),
                                            ast.HogQLXTag(
                                                kind="em",
                                                attributes=[
                                                    ast.HogQLXAttribute(
                                                        name="children",
                                                        value=[ast.Field(chain=["event"])],
                                                    )
                                                ],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            ast.Constant(value="a"),
                        ],
                    )
                ],
            )

            self.assertEqual(outer, expected)

        # Regression tests: “<” operator vs HOGQLX-tag opener
        def test_lt_vs_tags_and_comments(self):
            # 1. Plain operator – no whitespace
            self.assertEqual(
                self._expr("a<b"),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["a"]),
                    right=ast.Field(chain=["b"]),
                ),
            )

            # 2. Operator with unusual spacing: the ‘b+c’ part must be parsed first,
            #    so we use a small arithmetic expression on the RHS.
            self.assertEqual(
                self._expr("a <b +c"),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["a"]),
                    right=ast.ArithmeticOperation(
                        op=ast.ArithmeticOperationOp.Add,
                        left=ast.Field(chain=["b"]),
                        right=ast.Field(chain=["c"]),
                    ),
                ),
            )

            # 3. Trailing whitespace after RHS – still an operator
            self.assertEqual(
                self._expr("a < timestamp "),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["a"]),
                    right=ast.Field(chain=["timestamp"]),
                ),
            )

            # 4. Same, but with an end-of-line comment that must be ignored
            self.assertEqual(
                self._expr("a < timestamp // comment\n"),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["a"]),
                    right=ast.Field(chain=["timestamp"]),
                ),
            )

            # 5. Sequence that *is* a tag: `<b …`  → should now fail to parse
            with self.assertRaises(SyntaxError):
                self._expr("a <b c")

        def test_program_while_lt_with_space_and_comment(self):
            code = """
                while (a < timestamp // comment
                ) {
                    let c := 3;
                }
            """
            program = self._program(code)
            expected = Program(
                declarations=[
                    WhileStatement(
                        expr=CompareOperation(
                            op=CompareOperationOp.Lt,
                            left=Field(chain=["a"]),
                            right=Field(chain=["timestamp"]),
                        ),
                        body=Block(
                            declarations=[
                                VariableDeclaration(
                                    name="c",
                                    expr=Constant(value=3),
                                )
                            ],
                        ),
                    )
                ],
            )
            self.assertEqual(program, expected)

        def test_select_extract_as_function(self):
            node = self._select("select extract('string', 'other string') from events")

            assert node == ast.SelectQuery(
                select=[
                    ast.Call(
                        name="extract",
                        args=[ast.Constant(value="string"), ast.Constant(value="other string")],
                    )
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            )

        def test_trim_leading_trailing_both(self):
            node1 = self._select(
                "select trim(LEADING 'fish' FROM event), trim(TRAILING 'fish' FROM event), trim(BOTH 'fish' FROM event) from events"
            )
            node2 = self._select(
                "select trimLeft(event, 'fish'), trimRight(event, 'fish'), trim(event, 'fish') from events"
            )
            assert node1 == node2

            node3 = self._select(
                "select TRIM (LEADING 'fish' FROM event), TRIM (TRAILING 'fish' FROM event), TRIM (BOTH 'fish' FROM event) from events"
            )
            assert node3 == node1

            node4 = self._select("select TRIM (LEADING f'fi{'a'}sh' FROM event) from events")
            assert isinstance(node4, ast.SelectQuery)
            assert node4.select[0] == ast.Call(
                name="trimLeft",
                args=[
                    ast.Field(chain=["event"]),
                    ast.Call(
                        name="concat",
                        args=[
                            ast.Constant(value="fi"),
                            ast.Constant(value="a"),
                            ast.Constant(value="sh"),
                        ],
                    ),
                ],
            )

        def test_template_strings(self):
            node = self._expr("f'hello {event}'")
            assert node == ast.Call(name="concat", args=[ast.Constant(value="hello "), ast.Field(chain=["event"])])

            select = self._select("select f'hello {event}' from events")
            assert isinstance(select, ast.SelectQuery)
            assert select.select[0] == node

        def test_template_strings_nested_strings(self):
            node = self._expr("a = f'aa {1 + call('string')}aa'")
            assert node == ast.CompareOperation(
                left=ast.Field(chain=["a"]),
                right=ast.Call(
                    name="concat",
                    args=[
                        ast.Constant(value="aa "),
                        ast.ArithmeticOperation(
                            left=ast.Constant(value=1),
                            right=ast.Call(name="call", args=[ast.Constant(value="string")]),
                            op=ast.ArithmeticOperationOp.Add,
                        ),
                        ast.Constant(value="aa"),
                    ],
                ),
                op=ast.CompareOperationOp.Eq,
            )

        def test_template_strings_multiple_levels(self):
            node = self._expr("a = f'aa {1 + call(f'fi{one(more, time, 'stringy')}sh')}aa'")
            assert node == ast.CompareOperation(
                left=ast.Field(chain=["a"]),
                right=ast.Call(
                    name="concat",
                    args=[
                        ast.Constant(value="aa "),
                        ast.ArithmeticOperation(
                            left=ast.Constant(value=1),
                            right=ast.Call(
                                name="call",
                                args=[
                                    ast.Call(
                                        name="concat",
                                        args=[
                                            ast.Constant(value="fi"),
                                            ast.Call(
                                                name="one",
                                                args=[
                                                    ast.Field(chain=["more"]),
                                                    ast.Field(chain=["time"]),
                                                    ast.Constant(value="stringy"),
                                                ],
                                            ),
                                            ast.Constant(value="sh"),
                                        ],
                                    )
                                ],
                            ),
                            op=ast.ArithmeticOperationOp.Add,
                        ),
                        ast.Constant(value="aa"),
                    ],
                ),
                op=ast.CompareOperationOp.Eq,
            )

        def test_template_strings_full(self):
            node = self._string_template("hello {event}")
            assert node == ast.Call(name="concat", args=[ast.Constant(value="hello "), ast.Field(chain=["event"])])

            node = self._string_template("we're ready to open {person.properties.email}")
            assert node == ast.Call(
                name="concat",
                args=[ast.Constant(value="we're ready to open "), ast.Field(chain=["person", "properties", "email"])],
            )

            node = self._string_template("strings' to {'strings'}")
            assert node == ast.Call(
                name="concat", args=[ast.Constant(value="strings' to "), ast.Constant(value="strings")]
            )
            node2 = self._expr("f'strings\\' to {'strings'}'")
            assert node2 == node

            node = self._string_template("strings\\{ to {'strings'}")
            assert node == ast.Call(
                name="concat", args=[ast.Constant(value="strings{ to "), ast.Constant(value="strings")]
            )
            node2 = self._expr("f'strings\\{ to {'strings'}'")
            assert node2 == node

        def test_template_strings_full_multiline(self):
            node = self._string_template("hello \n{event}")
            assert node == ast.Call(name="concat", args=[ast.Constant(value="hello \n"), ast.Field(chain=["event"])])

            node = self._string_template("we're ready to \n\nopen {\nperson.properties.email\n}")
            assert node == ast.Call(
                name="concat",
                args=[
                    ast.Constant(value="we're ready to \n\nopen "),
                    ast.Field(chain=["person", "properties", "email"]),
                ],
            )

        def test_program_variable_declarations(self):
            code = "let a := '123'; let b := a - 2; print(b);"
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
            code = "let a := 3; a := 4;"
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

        def test_program_exprstmt_routes_assignment_vs_expression(self):
            # `:=` present yields a VariableAssignment for any expression target; otherwise an ExprStatement.
            declarations = self._program("a := 1; o.a := 2; arr[1] := 3; (x) := 9; foo();").declarations
            self.assertEqual(
                [type(declaration).__name__ for declaration in declarations],
                [
                    "VariableAssignment",
                    "VariableAssignment",
                    "VariableAssignment",
                    "VariableAssignment",
                    "ExprStatement",
                ],
            )

        def test_named_argument_in_call_not_treated_as_assignment(self):
            # A named argument inside a call stays a NamedArgument; only a statement-level one is promoted.
            call = self._expr("f(x := 1)")
            # `assert isinstance` rather than `assertIsInstance` so mypy narrows the type.
            assert isinstance(call, ast.Call)
            assert isinstance(call.args[0], ast.NamedArgument)
            self.assertEqual(call.args[0].name, "x")
            declaration = self._program("f(x := 1);").declarations[0]
            assert isinstance(declaration, ast.ExprStatement)

        def test_parenthesized_named_arg_is_an_expression_statement(self):
            # `(x := 9)` is a parenthesised named-argument expression, not a statement-level
            # assignment; the fold does not unwrap parens, so both backends agree.
            for code in ("(x := 9);", "((y := 2));"):
                assert isinstance(self._program(code).declarations[0], ast.ExprStatement)

        def test_promoted_assignment_target_carries_position(self):
            # The Field synthesised for a bare-identifier assignment target carries the
            # identifier's source position, matching a non-folded target.
            assignment = parse_program("xyz := 1", backend=backend).declarations[0]
            assert isinstance(assignment, ast.VariableAssignment)
            assert assignment.left.start is not None
            assert assignment.left.end is not None

        def test_program_variable_declarations_with_sql_expr(self):
            code = """
                let query := (select id, properties.email from events where timestamp > now() - interval 1 day);
                let results := run(query);
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
                    let c := 3;
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
                    let c := 3;
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
                fun query(a, b) {
                    let c := 3;
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
            # test both "fn" (deprecated) and "fun"
            code = """
                fn query(a, b) {
                    let c := 3;
                }

                fun read(a, b) {
                    print(3);
                    let b := 4;
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

        def test_program_quoted_identifiers(self):
            # Quoted identifiers in name positions must be unquoted, matching the cpp parser.
            self.assertEqual(
                self._program('fn "my fn"("a b", "c d") { return 1; }'),
                Program(
                    declarations=[
                        Function(
                            name="my fn",
                            params=["a b", "c d"],
                            body=Block(declarations=[ast.ReturnStatement(expr=Constant(value=1))]),
                        )
                    ],
                ),
            )
            self.assertEqual(
                self._program('let "my var" := 1;'),
                Program(declarations=[VariableDeclaration(name="my var", expr=Constant(value=1))]),
            )
            self.assertEqual(
                self._program('for (let "key", "val" in [1]) {}'),
                Program(
                    declarations=[
                        ast.ForInStatement(
                            keyVar="key",
                            valueVar="val",
                            expr=ast.Array(exprs=[Constant(value=1)]),
                            body=Block(declarations=[]),
                        )
                    ],
                ),
            )

        def test_program_bare_throw_rejected(self):
            # `throwStmt` requires an expression — Hog has no bare-throw / implicit re-throw.
            with self.assertRaises((ExposedHogQLError, SyntaxError)):
                self._program("throw")
            with self.assertRaises((ExposedHogQLError, SyntaxError)):
                self._program("throw;")

        def test_program_array(self):
            code = "let a := [1, 2, 3];"
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
            code = "let a := {};"
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

            code = "let a := {1: 2, 'a': [3, 4], g: true};"
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

        def test_program_simple_return(self):
            code = "return"
            program = self._program(code)
            expected = Program(
                declarations=[ast.ReturnStatement(expr=None)],
            )
            self.assertEqual(program, expected)

        def test_program_simple_return_twice(self):
            code = "return;return"
            program = self._program(code)
            expected = Program(
                declarations=[ast.ReturnStatement(expr=None), ast.ReturnStatement(expr=None)],
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_throw_simple(self):
            code = "return"
            program = self._program(code)
            expected = Program(
                declarations=[ast.ReturnStatement(expr=None)],
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_blocks(self):
            code = "try { 1 } catch (e) { 2 }"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[("e", None, ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))]))],
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_finally_simple(self):
            code = "try {1 } finally { 2 }"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[],
                        finally_stmt=ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))]),
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_finally(self):
            code = "try {1} catch (e) {2} finally {3}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[("e", None, ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))]))],
                        finally_stmt=ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=3))]),
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_alone(self):
            # This parses, but will throw later when printing bytecode.
            code = "try {1}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]), catches=[]
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_type(self):
            code = "try {1} catch (e: DodgyError) {2}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[
                            ("e", "DodgyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))]))
                        ],
                        finally_stmt=None,
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_multiple(self):
            code = "try {1} catch (e: DodgyError) {2}  catch (e: FishyError) {3}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[
                            ("e", "DodgyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))])),
                            ("e", "FishyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=3))])),
                        ],
                        finally_stmt=None,
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_program_exceptions_try_catch_multiple_plain(self):
            code = "try {1} catch (e: DodgyError) {2}  catch (e: FishyError) {3} catch {4}"
            program = self._program(code)
            expected = Program(
                declarations=[
                    ast.TryCatchStatement(
                        try_stmt=ast.Block(declarations=[ast.ExprStatement(expr=ast.Constant(value=1))]),
                        catches=[
                            ("e", "DodgyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=2))])),
                            ("e", "FishyError", ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=3))])),
                            (None, None, ast.Block(declarations=[ast.ExprStatement(expr=Constant(value=4))])),
                        ],
                        finally_stmt=None,
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_pop_empty_stack(self):
            with self.assertRaises(SyntaxError) as e:
                self._select("select } from events")
            self.assertEqual(str(e.exception), "Unmatched curly bracket")

        def test_for_in_loops(self):
            code = """
                for (let i in [1, 2, 3]) {
                    print(a);
                }
            """
            program = self._program(code)
            expected = ast.Program(
                declarations=[
                    ast.ForInStatement(
                        keyVar=None,
                        valueVar="i",
                        expr=ast.Array(exprs=[Constant(value=1), Constant(value=2), Constant(value=3)]),
                        body=ast.Block(
                            declarations=[ast.ExprStatement(expr=Call(name="print", args=[Field(chain=["a"])]))]
                        ),
                    )
                ]
            )
            self.assertEqual(program, expected)

            code = """
                for (let key, value in [1, 2, 3]) {
                    print(a);
                }
            """
            program = self._program(code)
            expected = ast.Program(
                declarations=[
                    ast.ForInStatement(
                        keyVar="key",
                        valueVar="value",
                        expr=ast.Array(exprs=[Constant(value=1), Constant(value=2), Constant(value=3)]),
                        body=ast.Block(
                            declarations=[ast.ExprStatement(expr=Call(name="print", args=[Field(chain=["a"])]))]
                        ),
                    )
                ]
            )
            self.assertEqual(program, expected)

        def test_trailing_semicolon_select(self):
            self.assertEqual(self._select("SELECT 1;"), self._select("SELECT 1"))

            self.assertEqual(self._select("SELECT 1 FROM events;"), self._select("SELECT 1 FROM events"))

            self.assertEqual(
                self._select("SELECT * FROM events WHERE timestamp > now();"),
                self._select("SELECT * FROM events WHERE timestamp > now()"),
            )

            self.assertEqual(
                self._select("SELECT e.event FROM events e JOIN persons p ON e.person_id = p.id;"),
                self._select("SELECT e.event FROM events e JOIN persons p ON e.person_id = p.id"),
            )

            self.assertEqual(self._select("SELECT 1 UNION ALL SELECT 2;"), self._select("SELECT 1 UNION ALL SELECT 2"))

        def test_postgres_style_cast(self):
            self.assertEqual(
                self._expr("x::int"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="int"),
            )
            self.assertEqual(self._expr("'123'::int"), ast.TypeCast(expr=ast.Constant(value="123"), type_name="int"))
            self.assertEqual(self._expr("x::integer"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="integer"))
            self.assertEqual(self._expr("x::text"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="text"))
            self.assertEqual(self._expr("x::float"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="float"))
            self.assertEqual(self._expr("x::boolean"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="boolean"))
            self.assertEqual(self._expr("x::INT"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="int"))
            self.assertEqual(self._expr("x::Text"), ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="text"))
            self.assertEqual(
                self._expr("a.b::int"),
                ast.TypeCast(expr=ast.Field(chain=["a", "b"]), type_name="int"),
            )
            self.assertEqual(
                self._expr("x::int + 1"),
                ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Add,
                    left=ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="int"),
                    right=ast.Constant(value=1),
                ),
            )

        def test_cast_with_nested_and_parametric_types(self):
            self.assertEqual(
                self._expr("CAST(x AS STRUCT(a INTEGER, b VARCHAR))"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="struct(a integer, b varchar)"),
            )
            self.assertEqual(
                self._expr("CAST(x AS DECIMAL(10, 2))"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="decimal(10, 2)"),
            )
            self.assertEqual(
                self._expr("CAST(x AS INTEGER[])"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="integer[]"),
            )
            self.assertEqual(
                self._expr("CAST(x AS VARCHAR[3])"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="varchar[3]"),
            )
            self.assertEqual(
                self._expr("CAST(x AS ARRAY(INTEGER))"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="array(integer)"),
            )
            self.assertEqual(
                self._expr("CAST(x AS TUPLE(INTEGER, VARCHAR))"),
                ast.TypeCast(expr=ast.Field(chain=["x"]), type_name="tuple(integer, varchar)"),
            )

        def test_with_clause_column_name_list(self):
            node = self._select("WITH cte (a, b) AS (SELECT 1, 2) SELECT * FROM cte")
            assert isinstance(node, ast.SelectQuery)
            assert node.ctes is not None and node.ctes.get("cte") is not None
            cte = node.ctes["cte"]
            assert cte.name == "cte"
            assert cte.columns == ["a", "b"]

        def test_with_recursive(self):
            parsed = self._select("WITH RECURSIVE events AS (SELECT * FROM posthog_event) SELECT * FROM events;")

            expected = SelectQuery(
                ctes={
                    "events": ast.CTE(
                        name="events",
                        expr=SelectQuery(
                            select=[Field(chain=["*"], from_asterisk=False)],
                            select_from=JoinExpr(
                                table=Field(chain=["posthog_event"], from_asterisk=False),
                            ),
                        ),
                        cte_type="subquery",
                        recursive=True,
                    )
                },
                select=[Field(chain=["*"], from_asterisk=False)],
                select_from=JoinExpr(table=Field(chain=["events"])),
            )

            self.assertEqual(parsed, expected)

        def test_cte_materialization_hint_is_none_when_omitted(self):
            parsed = self._select("WITH x AS (SELECT 1) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.materialized is None

        def test_cte_materialization_hint_materialized(self):
            parsed = self._select("WITH x AS MATERIALIZED (SELECT 1) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.materialized is True

        def test_cte_materialization_hint_not_materialized(self):
            parsed = self._select("WITH x AS NOT MATERIALIZED (SELECT 1) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.materialized is False

        def test_with_clause_before_parens_select_set(self):
            self.assertEqual(
                self._select("WITH cte AS (SELECT 1 AS a) (SELECT a FROM cte UNION ALL SELECT a FROM cte)"),
                ast.SelectSetQuery(
                    initial_select_query=ast.SelectQuery(
                        select=[ast.Field(chain=["a"])],
                        select_from=ast.JoinExpr(table=ast.Field(chain=["cte"])),
                        ctes={
                            "cte": ast.CTE(
                                name="cte",
                                expr=ast.SelectQuery(
                                    select=[ast.Alias(alias="a", expr=ast.Constant(value=1))],
                                ),
                                cte_type="subquery",
                            )
                        },
                    ),
                    subsequent_select_queries=[
                        ast.SelectSetNode(
                            set_operator="UNION ALL",
                            select_query=ast.SelectQuery(
                                select=[ast.Field(chain=["a"])],
                                select_from=ast.JoinExpr(table=ast.Field(chain=["cte"])),
                            ),
                        )
                    ],
                ),
            )

        def test_cte_using_key_is_none_when_omitted(self):
            parsed = self._select("WITH RECURSIVE x(a, b) AS (SELECT 1, 2) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.using_key is None

        def test_cte_using_key_single_column(self):
            parsed = self._select("WITH RECURSIVE x(a, b) USING KEY (a) AS (SELECT 1, 2) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.using_key == ["a"]
            assert cte.columns == ["a", "b"]

        def test_cte_using_key_multiple_columns(self):
            parsed = self._select("WITH RECURSIVE x(a, b, c) USING KEY (a, b) AS (SELECT 1, 2, 3) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.using_key == ["a", "b"]
            assert cte.columns == ["a", "b", "c"]

        def test_cte_using_key_without_column_name_list(self):
            parsed = self._select("WITH RECURSIVE x USING KEY (a) AS (SELECT 1) SELECT * FROM x;")
            assert isinstance(parsed, SelectQuery) and parsed.ctes is not None
            cte = parsed.ctes.get("x")
            assert cte is not None
            assert cte.using_key == ["a"]
            assert cte.columns is None

        def test_select_from_values(self):
            self.assertEqual(
                self._select("SELECT * FROM (VALUES (1, 'a'), (2, 'b')) AS v(id, name)"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.ValuesQuery(
                            rows=[
                                [ast.Constant(value=1), ast.Constant(value="a")],
                                [ast.Constant(value=2), ast.Constant(value="b")],
                            ]
                        ),
                        alias="v",
                        column_aliases=["id", "name"],
                    ),
                ),
            )

        def test_select_from_values_no_column_aliases(self):
            self.assertEqual(
                self._select("SELECT * FROM (VALUES (1), (2)) AS v"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.ValuesQuery(
                            rows=[
                                [ast.Constant(value=1)],
                                [ast.Constant(value=2)],
                            ]
                        ),
                        alias="v",
                    ),
                ),
            )

        def test_select_from_unpivot(self):
            self.assertEqual(
                self._select(
                    "SELECT field_name, field_value FROM events UNPIVOT (field_value FOR field_name IN (event))"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["field_name"]), ast.Field(chain=["field_value"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.Field(chain=["events"]),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["event"])],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_from_unpivot_tuple(self):
            self.assertEqual(
                self._select(
                    "SELECT * FROM events UNPIVOT ((value_a, value_b) FOR (name_a, name_b) IN ((event, uuid)))"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.Field(chain=["events"]),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Tuple(
                                        exprs=[ast.Field(chain=["value_a"]), ast.Field(chain=["value_b"])]
                                    ),
                                    name_columns=ast.Tuple(
                                        exprs=[ast.Field(chain=["name_a"]), ast.Field(chain=["name_b"])]
                                    ),
                                    unpivot_values=[
                                        ast.Tuple(exprs=[ast.Field(chain=["event"]), ast.Field(chain=["uuid"])])
                                    ],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_from_unpivot_multiple_in(self):
            self.assertEqual(
                self._select("SELECT * FROM events UNPIVOT (field_value FOR field_name IN (event, uuid))"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.Field(chain=["events"]),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["event"]), ast.Field(chain=["uuid"])],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_from_unpivot_with_table_alias(self):
            self.assertEqual(
                self._select("SELECT * FROM events e UNPIVOT (field_value FOR field_name IN (event))"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.JoinExpr(table=ast.Field(chain=["events"]), alias="e"),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["event"])],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_from_pivot(self):
            self.assertEqual(
                self._select("SELECT * FROM events PIVOT (count() FOR event IN ('a', 'b'))"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.PivotExpr(
                            table=ast.Field(chain=["events"]),
                            aggregates=[ast.Call(name="count", args=[])],
                            columns=[
                                ast.PivotColumn(
                                    column=ast.Field(chain=["event"]),
                                    values=[ast.Constant(value="a"), ast.Constant(value="b")],
                                )
                            ],
                            group_by=None,
                        )
                    ),
                ),
            )

        def test_select_from_pivot_multiple_columns(self):
            self.assertEqual(
                self._select(
                    "SELECT * FROM events PIVOT (count() FOR event IN ('a') person_id IN (1, 2) GROUP BY distinct_id)"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.PivotExpr(
                            table=ast.Field(chain=["events"]),
                            aggregates=[ast.Call(name="count", args=[])],
                            columns=[
                                ast.PivotColumn(
                                    column=ast.Field(chain=["event"]),
                                    values=[ast.Constant(value="a")],
                                ),
                                ast.PivotColumn(
                                    column=ast.Field(chain=["person_id"]),
                                    values=[ast.Constant(value=1), ast.Constant(value=2)],
                                ),
                            ],
                            group_by=[ast.Field(chain=["distinct_id"])],
                        )
                    ),
                ),
            )

        def test_select_from_join_pivot(self):
            self.assertEqual(
                self._select("SELECT 1 FROM events JOIN events AS e2 ON 1 PIVOT (count() FOR events.event IN ('a'))"),
                ast.SelectQuery(
                    select=[ast.Constant(value=1)],
                    select_from=ast.JoinExpr(
                        table=ast.PivotExpr(
                            table=ast.JoinExpr(
                                table=ast.Field(chain=["events"]),
                                next_join=ast.JoinExpr(
                                    join_type="JOIN",
                                    table=ast.Field(chain=["events"]),
                                    alias="e2",
                                    constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                                ),
                            ),
                            aggregates=[ast.Call(name="count", args=[])],
                            columns=[
                                ast.PivotColumn(
                                    column=ast.Field(chain=["events", "event"]),
                                    values=[ast.Constant(value="a")],
                                )
                            ],
                            group_by=None,
                        )
                    ),
                ),
            )

        def test_select_from_unpivot_include_nulls(self):
            self.assertEqual(
                self._select(
                    "SELECT field_name, field_value FROM events UNPIVOT INCLUDE NULLS (field_value FOR field_name IN (event))"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["field_name"]), ast.Field(chain=["field_value"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.Field(chain=["events"]),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["event"])],
                                )
                            ],
                            include_nulls=True,
                        )
                    ),
                ),
            )

        def test_select_from_join_unpivot(self):
            self.assertEqual(
                self._select(
                    "SELECT field_name, field_value FROM events JOIN events AS e2 ON 1 "
                    "UNPIVOT (field_value FOR field_name IN (events.event))"
                ),
                ast.SelectQuery(
                    select=[ast.Field(chain=["field_name"]), ast.Field(chain=["field_value"])],
                    select_from=ast.JoinExpr(
                        table=ast.UnpivotExpr(
                            table=ast.JoinExpr(
                                table=ast.Field(chain=["events"]),
                                next_join=ast.JoinExpr(
                                    join_type="JOIN",
                                    table=ast.Field(chain=["events"]),
                                    alias="e2",
                                    constraint=ast.JoinConstraint(expr=ast.Constant(value=1), constraint_type="ON"),
                                ),
                            ),
                            columns=[
                                ast.UnpivotColumn(
                                    value_columns=ast.Field(chain=["field_value"]),
                                    name_columns=ast.Field(chain=["field_name"]),
                                    unpivot_values=[ast.Field(chain=["events", "event"])],
                                )
                            ],
                        )
                    ),
                ),
            )

        def test_select_positional_join(self):
            self.assertEqual(
                self._select("SELECT * FROM events POSITIONAL JOIN persons"),
                ast.SelectQuery(
                    select=[ast.Field(chain=["*"])],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(table=ast.Field(chain=["persons"]), join_type="POSITIONAL JOIN"),
                    ),
                ),
            )

        def test_select_positional_refs(self):
            self.assertEqual(
                self._select("SELECT #1, #2 FROM events"),
                ast.SelectQuery(
                    select=[ast.PositionalRef(index=1), ast.PositionalRef(index=2)],
                    select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                ),
            )

        @no_memory_leak_check
        def test_statement_keywords_rejected_as_expressions(self):
            # `fn`, `let`, `while`, … cannot stand as a Field or call head
            # in an expression (unlike `if` / `for` / `return`, which the
            # `keyword` rule does include).
            for kw in ("fn", "fun", "let", "while", "throw", "try", "catch", "finally"):
                with self.assertRaises(ExposedHogQLError, msg=f"{backend}: {kw!r} should reject"):
                    parse_expr(kw, backend=backend)

        @no_memory_leak_check
        def test_exponent_float_without_fractional_digits(self):
            # `1.e5` is one FLOATING_LITERAL token in the grammar
            # (`DECIMAL_LITERAL DOT DEC_DIGIT* E (PLUS|DASH)? DEC_DIGIT+`),
            # i.e. the fractional digits are optional. The Rust lexer used
            # to stop at the `.` and let the Pratt postfix loop fold
            # `1.e5` into `ArrayAccess(Constant(1), Constant('e5'))`.
            cases = {
                "1.e5": 100000.0,
                "1.E5": 100000.0,
                "1.e+5": 100000.0,
                "1.e-5": 1e-05,
                "12.e2": 1200.0,
            }
            for src, expected in cases.items():
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertEqual(node.value, expected, msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_clause_keyword_after_comma_in_select_columns(self):
            # A clause keyword after the trailing comma starts its clause
            # when a valid body follows: `select a, where b` is one column
            # plus a WHERE clause, not two columns. With no body the
            # keyword stays a column: `select a, where` is two columns.
            # The Rust parser used to always keep it as a column.
            # clause keyword + body → trailing comma, clause starts.
            # `where * columns('x')` is also a valid multiplication
            # column, but cpp's ALL(*) prefers the clause; the Rust
            # parser used to keep the (valid) column interpretation.
            for src, attr in (
                ("select a, where b", "where"),
                ("select a, having b", "having"),
                ("select a, prewhere c", "prewhere"),
                ("select a, qualify d", "qualify"),
                ("select columns('gk'), where * columns('gk') with totals", "where"),
                ("select a, prewhere * columns('y')", "prewhere"),
            ):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 1, msg=f"{backend}: {src!r}")
                self.assertIsNotNone(getattr(node, attr), msg=f"{backend}: {src!r}")
            # bare clause keyword (no body) → stays a column;
            # `window from events` is `window` the Field then a FROM
            # clause, not a malformed WINDOW clause.
            for src in (
                "select a, where",
                "select a, having",
                "select a, window x",
                "select 1, window from events",
            ):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 2, msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_limit_percent_marker_with_compound_body(self):
            # `%` is overloaded: modulo operator and the `LIMIT … PERCENT`
            # marker. When the LIMIT body is a compound expression the
            # marker `%` lands after a lower-precedence operator; the Rust
            # parser used to bind it as modulo and choke on `WITH TIES`.
            # The cpp-json oracle is the source of truth; assert all three
            # backends agree on the parsed AST.
            cases = (
                "SELECT 1 LIMIT 1+1 % WITH TIES",
                "SELECT a, b LIMIT c AND d % WITH TIES",
                "SELECT 1 LIMIT 1+1 % 2 WITH TIES",
                "SELECT 1 LIMIT a%b % WITH TIES",
                "SELECT 1 LIMIT 5 % 2 + 3",
                "SELECT 1 LIMIT 1+1 % OFFSET 3",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_assignment_lhs_is_any_expression(self):
            # `exprStmt: expression (COLONEQUALS expression)?` puts no
            # target restriction on the `:=` left-hand side — cpp builds a
            # `VariableAssignment` for any `<expr> := <expr>`. The Rust
            # parser rejected non-place LHSs ("cannot assign to this
            # expression"); a rejected `:=` body inside a `for` then made
            # the whole `for` fail and mis-report "unexpected Let".
            cases = (
                "1 := 1",
                "[] := 1",
                "{} := 1",
                "'s' := 1",
                "return 1 := 1",
                "for (let m in 488614) 1 := 1",
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_call_as_assignment_target(self):
            # A statement's leading expression folds its own postfix `(…)`
            # call even when `:=` follows — `f() := 1` is
            # `Call(f) := 1`, `if(x) := y` is `Call(if,[x]) := y`. The
            # Rust parser ran the leading expr through the
            # `stop_postfix_call_before_colon_equals` guard (which is meant
            # only for RHS parsing) and split it into two statements.
            cases = (
                "f() := 1",
                "f(x) := 1",
                "f()(g) := h",
                "if(x) := y",
                # the guard's real RHS scenario must still hold
                "(a) := (b) (c) := (d)",
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_assignment_statement_consumes_trailing_semicolon(self):
            # `exprStmt: expression (COLONEQUALS expression)? SEMICOLON?` —
            # the `:=` form is an exprStmt and consumes its optional
            # trailing `;`. Without that, `if (c) a := b ; else d` strands
            # the `;` and the `else` is parsed as a bare Field instead of
            # binding to the `if`. (`varDecl`'s `LET …` form has no
            # `SEMICOLON?` and must not consume it.)
            cases = (
                "if (c) a := b ; else d",
                "if (c) (a) := b ; else d",
                "if (c) a := b ;; else d",
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_trailing_limit_offset_compound_body(self):
            # The `LIMIT`/`OFFSET` that may follow a `LIMIT BY` clause takes
            # a full `columnExpr` body. The Rust parser parsed it bounded
            # at BP_MULT+1, stranding any lower-precedence tail
            # (`limit (x) ?? y`, `offset a ?? b`).
            cases = (
                "select x limit a by c limit d ?? e",
                "select x limit a by c offset d ?? e",
                "select x limit a by c limit 1 + 1",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_zero_arg_lambda_as_clause_body(self):
            # `() -> body` is a zero-arg lambda. After a trailing comma a
            # clause keyword followed by `( )` is normally an empty call on
            # the keyword-as-Field (`select 1, where ()`), but `( ) ->` is
            # a lambda parameter list — a valid clause body — so the
            # keyword stays a clause introducer.
            cases = (
                "select 1, limit () -> 2",
                "select 1, where () -> 2",
                "select 1, offset () -> 3",
                "select 1, limit ()",  # bare () — keyword is a column
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_set_level_offset_compound_body(self):
            # `offsetOnlyClause: OFFSET columnExpr` at the selectSetStmt
            # level takes a full `columnExpr`. The Rust parser parsed it
            # bounded at BP_MULT+1, stranding a lower-precedence tail
            # (`offset (x) or y`, `offset (x) ignore nulls`).
            cases = (
                "select 1 offset a or b",
                "select 1 offset a ignore nulls",
                "(select 1) offset a ?? b",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_pivot_tuple_or_single_parenthesised_operand(self):
            # `columnExprTupleOrSingle: LPAREN columnExprList RPAREN |
            # columnExpr` — a parenthesised PIVOT/UNPIVOT operand is always
            # a `Tuple`, even for one element (`(x)` → Tuple([x])). The
            # Rust parser stripped the parens for the single-element case.
            cases = (
                "select 1 from a unpivot ((x) for (c) in (d))",
                "select 1 from a pivot (s for (c) in (1))",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_pivot_binds_to_last_joined_table(self):
            # `joinExpr PIVOT` is left-recursive on the immediately
            # preceding joinExpr: `a JOIN b PIVOT (…)` pivots `b` alone,
            # not the whole `a JOIN b` chain. A PIVOT after a join
            # constraint (`a JOIN b ON x PIVOT (…)`) or explicit parens
            # (`(a JOIN b) PIVOT (…)`) does apply to the whole chain. The
            # Rust parser wrapped the entire chain unconditionally.
            cases = (
                "select 1 from a join b pivot (x for y in (z))",
                "select 1 from a, b pivot (x for y in (z))",
                "select 1 from a join b on x pivot (s for t in (u))",
                "select 1 from (a join b) pivot (x for y in (z))",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_columns_macro_asterisk_form_as_list_element(self):
            # `COLUMNS (…)` resolves `columnExprList` before the dedicated
            # `* EXCLUDE` / `id.* …` alternatives. An asterisk-form
            # followed by a postfix `(…)` call (`columns(q.*())`,
            # `columns(* exclude(a) ())`) is a `ColumnsList` whose element
            # is an `ExprCall` over the asterisk-form — not a plain
            # `Call(columns, …)`. The Rust parser committed to the
            # dedicated form and then fell back to a function call when the
            # trailing `(…)` would not parse.
            cases = (
                "columns(q.*())",
                "columns(* exclude(a) ())",
                # guard: the plain forms must keep their shape
                "columns(*)",
                "columns(a, b)",
                "columns(q.*)",
                "columns(* exclude(a))",
                "columns('re')",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_columns_replace_item_name_is_the_as_keyword(self):
            # `columnsReplace: columnExpr AS identifier` — the replacement
            # name can itself be the keyword `as` (`* replace(a AS as)`).
            # The Rust parser located the separator `AS` as the last `Kw::As`
            # token of the item, which is the *name* in that case; it must
            # use the second-to-last token instead.
            cases = (
                "(* replace(a as as))",
                "columns(* replace(a as as))",
                "(* replace(a as b as as))",
                "columns(* replace(x as y, z as as))",
                # guard: ordinary names still work
                "(* replace(a as b))",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_clause_keyword_then_postfix_op_is_a_column(self):
            # A clause keyword after the trailing comma followed by a
            # postfix operator (`?.`, `::`) is a column — `qualify?.q`,
            # `prewhere::q` — because a clause body cannot *start* with an
            # operator token. `peek_can_start_clause_body` wrongly accepted
            # pure infix/postfix tokens, so the Rust parser treated the
            # keyword as a clause and rejected the stranded operator.
            for src in (
                "select q, qualify ?. q",
                "select q, prewhere ?. q",
                "select q, prewhere :: q",
                "select q, having ?. r",
            ):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 2, msg=f"{backend}: {src!r}")
            # guard: a real expression-starter still opens the clause
            node = parse_select("select q, having y", backend=backend)
            self.assertEqual(len(node.select), 1, msg=f"{backend}: having y")

        @no_memory_leak_check
        def test_from_after_comma_needs_a_table_reference(self):
            # FROM's clause body is a `joinExpr` (a table reference), not a
            # `columnExpr`. After a trailing comma `from` only opens the
            # FROM clause when a table-reference starter follows; otherwise
            # it stays a Field column (`select q, from` → two columns,
            # `select q, from + 1` → `q` and `from + 1`). The Rust parser
            # broke the column list on `from` unconditionally.
            for src in ("select q, from", "select q, from + 1", "select q, from()"):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 2, msg=f"{backend}: {src!r}")
                self.assertIsNone(node.select_from, msg=f"{backend}: {src!r}")
            # guard: a real table reference still opens the FROM clause
            node = parse_select("select q, from t", backend=backend)
            self.assertEqual(len(node.select), 1, msg=f"{backend}: from t")
            self.assertIsNotNone(node.select_from, msg=f"{backend}: from t")

        @no_memory_leak_check
        def test_clause_keyword_asterisk_then_postfix_is_a_clause(self):
            # `<clause-kw> * <postfix-op>` — `qualify * ?. q` — is the
            # clause whose body is the asterisk-spread `*` extended by the
            # postfix op, not `<clause-kw-field> * …` arithmetic: the `*`'s
            # multiplication RHS cannot begin with a postfix operator. The
            # Rust `asterisk_after_offset_continues_arith` probe answered
            # "continues arithmetic" for an operator token after `*`.
            for src in (
                "select q, qualify * ?. q",
                "select q, where * :: r",
                "select q, having * ?. r",
                "select q, offset * ?. r",
            ):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 1, msg=f"{backend}: {src!r}")
            # guard: `where * r` is `where` the column times `r`
            node = parse_select("select q, where * r", backend=backend)
            self.assertEqual(len(node.select), 2, msg=f"{backend}: where * r")

        @no_memory_leak_check
        def test_pivot_tuple_or_single_operand_with_postfix(self):
            # `columnExprTupleOrSingle: LPAREN columnExprList RPAREN |
            # columnExpr`. A parenthesised PIVOT/UNPIVOT operand is a
            # `Tuple` only when the matching `)` is followed by `FOR` /
            # `IN` (the operand boundary). When a postfix follows — `(n)()`
            # — it is the `columnExpr` alternative: a parenthesised
            # expression extended by the postfix call. The Rust parser
            # always took the Tuple branch and stranded the `()`.
            cases = (
                "select 1 from a unpivot (m for (n)() in (p))",
                "select 1 from a pivot (m for (n)() in (p))",
                # guard: a bare parenthesised operand stays a Tuple
                "select 1 from a unpivot (m for (n) in (p))",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_window_frame_between_falls_back_to_field(self):
            # `winFrameExtend: winFrameBound | BETWEEN winFrameBound AND
            # winFrameBound`. After ROWS / RANGE a `between` is ambiguous:
            # the `frameBetween` alt, or a `frameStart` bound whose
            # `columnExpr` is the `between` keyword used as a Field
            # (`RANGE BETWEEN PRECEDING` → frame expr = Field(between)).
            # The Rust parser committed to the `frameBetween` alt on
            # seeing `between` and rejected the un-`AND`ed frame.
            cases = (
                "select 1 from a window w as (range between preceding)",
                # guard: a real BETWEEN frame still parses
                "select 1 from a window w as (range between 1 preceding and 2 following)",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_pivot_operand_containing_in(self):
            # A PIVOT/UNPIVOT `columnExprTupleOrSingle` operand is a full
            # `columnExpr` and may contain the `in` comparison operator
            # (`for n in p in (r)` → operand `n in p`, then the structural
            # `IN (r)`). The Rust parser bounded the operand above `IN`'s
            # binding power, dropping any operand-internal `in` (and the
            # `for`-operand's too).
            cases = (
                "select 1 from a unpivot (m for n in p in (r))",
                "select 1 from a pivot (m for n in p in (r))",
                "select 1 from a unpivot (m in n for p in (r))",
                # guard: the simple form still parses
                "select 1 from a pivot (m for n in (r))",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_decoration_after_pivot(self):
            # `tableExpr PIVOT (…)` is itself a `tableExpr`, so the result
            # can still take a `TableExprAlias` alias and a `JoinExprTable`
            # `FINAL? sampleClause?`, and a further PIVOT / JOIN can follow.
            # The Rust parser parsed PIVOT as a one-shot at the join level
            # and stopped, rejecting the trailing tokens.
            cases = (
                "SELECT 1 FROM (t PIVOT (a FOR b IN (c)) FINAL)",
                "SELECT 1 FROM (t PIVOT (a FOR b IN (c)) SAMPLE 1)",
                "SELECT 1 FROM (t UNPIVOT (a FOR b IN (c)) FINAL)",
                "SELECT 1 FROM t PIVOT (a FOR b IN (c)) FINAL",
                "SELECT 1 FROM t PIVOT (a FOR b IN (c)) AS x",
                "SELECT 1 FROM t PIVOT (a FOR b IN (c)) x",
                "SELECT 1 FROM t PIVOT (a FOR b IN (c)) AS x PIVOT (d FOR e IN (f))",
                "SELECT 1 FROM t PIVOT (a FOR b IN (c)) JOIN u ON x",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_clause_keyword_as_last_group_by_key(self):
            # `GROUP BY tool, window HAVING …` — `window` is the WINDOW
            # clause keyword and also a valid Field. As the last GROUP BY
            # key (after a comma, immediately followed by another clause)
            # it must stay a group_by key, not flip the parser into WINDOW
            # clause parsing. The eight-token shape is taken straight from
            # a production query rendered 232x in 7 days.
            for kw in ("window", "having", "qualify"):
                node = parse_select(
                    f"SELECT a FROM events GROUP BY tool, {kw} HAVING call_count >= 5",
                    backend=backend,
                )
                self.assertIsInstance(node, ast.SelectQuery, msg=f"{backend}: {kw}")
                self.assertEqual(len(node.group_by or []), 2, msg=f"{backend}: {kw}")
                self.assertIsNotNone(node.having, msg=f"{backend}: {kw}")

        @no_memory_leak_check
        def test_integer_literal_above_i64_max(self):
            # An integer literal wider than i64 is kept lossless — never
            # narrowed to a float, all the way up through u64 and into
            # arbitrary-precision bigints. The value can't round-trip as a
            # native JSON number (orjson rejects >64-bit number tokens), so
            # the JSON backends carry the exact digits as a string in the
            # `value_type: "number"` envelope; all three backends must
            # agree on the exact int.
            cases = {
                "9223372036854775808": 9223372036854775808,  # i64::MAX + 1
                "18446744073709551615": 18446744073709551615,  # u64::MAX
                "18446744073709551616": 18446744073709551616,  # u64::MAX + 1
                "99999999999999999999999999": 99999999999999999999999999,
                "-9223372036854775809": -9223372036854775809,  # i64::MIN - 1
                "0x8000000000000000": 0x8000000000000000,
                "0xFFFFFFFFFFFFFFFFFF": 0xFFFFFFFFFFFFFFFFFF,
            }
            for src, expected in cases.items():
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertEqual(node.value, expected, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.value, int, msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_string_escape_nul_bel_vtab(self):
            # cpp's string.cpp drops `\0` (NUL ignored) and decodes
            # `\a`→0x07, `\v`→0x0B. The Rust decode_quoted_body emitted a
            # real NUL for `\0` and left `\a`/`\v` as literal backslash
            # sequences. `\0` also affects quoted identifiers.
            cases = (
                r"'a\0b'",
                r"'\a'",
                r"'\v'",
                r"`a\0b`",
                r'"a\0b"',
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_reserved_keyword_alias_rejected(self):
            # cpp calls assertValidAlias at all four alias sites, rejecting
            # an unquoted `true`/`false`/`null`/`team_id`. The Rust parser
            # only checked the `AS`-infix path; the alias-before
            # (`x : 1`), implicit-alias and table-alias sites were
            # unchecked. Quoted forms opt out and must still parse.
            for src in (
                "select 1 as team_id from t",  # AS-infix (already checked)
                "select 1 team_id from t",  # implicit alias
                "select team_id : 1 from t",  # alias-before
                "select * from t as team_id",  # table alias (AS)
                "select * from t team_id",  # table alias (bare)
            ):
                with self.assertRaises(ExposedHogQLError, msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Quoted aliases opt out of the reserved-keyword check.
            for src in (
                'select 1 as "team_id" from t',
                'select 1 "team_id" from t',
                'select * from t as "team_id"',
            ):
                parse_select(src, backend=backend)

        @no_memory_leak_check
        def test_settings_and_top_clause_error_class(self):
            # SETTINGS and TOP are accepted by the grammar but rejected by
            # the visitor as unsupported — cpp throws NotImplementedError,
            # surfaced by the JSON backend as a bare ExposedHogQLError. The
            # Rust parser never consumed either clause and fell out with a
            # generic SyntaxError; the error *class* must match cpp's. The
            # python backend has no JSON wrapper layer and leaks the raw
            # NotImplementedError, so it's skipped here.
            if backend == "python":
                self.skipTest("python visitor has no JSON wrapper, leaks NotImplementedError directly")
            for src in ("SELECT 1 SETTINGS x = 1", "SELECT TOP 5 x FROM t"):
                with self.assertRaises(ExposedHogQLError) as cpp_cm:
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError) as backend_cm:
                    parse_select(src, backend=backend)
                self.assertIs(type(backend_cm.exception), type(cpp_cm.exception), msg=f"{backend}: {src!r}")
                self.assertNotIsInstance(backend_cm.exception, SyntaxError, msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_window_frame_non_int_bound_keeps_constant(self):
            # cpp's VISIT(WinFrameBound) unwraps a frame-bound Constant to a
            # bare number only when the value is an integer; a float or
            # string Constant keeps its full object form. The Rust parser
            # unwrapped any Constant. (The pure-Python backend diverges from
            # cpp on a non-int bound too — a separate cpp-vs-python issue —
            # so this pins rust against cpp.)
            if backend == "python":
                self.skipTest("python visitor diverges from cpp on non-int frame bounds")
            cases = (
                "SELECT count() OVER (ROWS 1.5 PRECEDING) FROM t",
                "SELECT count() OVER (ROWS '5' PRECEDING) FROM t",
                "SELECT count() OVER (ROWS 2 PRECEDING) FROM t",  # guard: int still bare
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_boolean_keyword_as_call_name(self):
            # `true`/`false` are ordinary identifiers in the grammar, not
            # lexer tokens — they become Bool Constants only as a bare
            # columnIdentifier. As a function-call name cpp builds a
            # `Call(name=...)`. The Rust lexer makes them keywords, so the
            # parser folded `true(1)` into `ExprCall(Constant(true), …)`.
            # `null` differs — `NULL` is a real keyword, so `null(1)` stays
            # an `ExprCall` on the Null constant in both parsers.
            for src in ("true(1)", "false(1)", "null(1)"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # guard: bare true/false/null are still Constants
            for src, val in (("true", True), ("false", False), ("null", None)):
                node = parse_expr(src, backend="rust-json")
                self.assertIsInstance(node, ast.Constant, msg=src)
                self.assertEqual(node.value, val, msg=src)

        @no_memory_leak_check
        def test_hex_integer_literal_baseline(self):
            # Pins existing hex integer behaviour so the hex-float lexer
            # changes can't accidentally regress plain `0x…` parsing. `e`
            # and `E` are hex digits in this context (not exponent markers
            # — that only kicks in when a `[+-]?<dec>+` exponent suffix
            # follows them).
            cases = {
                "0x0": 0,
                "0x1": 1,
                "0xff": 255,
                "0xFF": 255,
                "0XFF": 255,
                "0xe": 14,  # `e` alone is a hex digit, not an exp marker
                "0xE": 14,
                "0x1e": 30,
                "0x1E": 30,
                "0x1e5": 485,  # three hex digits, NOT a float
                "0xabc": 2748,
                "0xABC": 2748,
                "0xfe": 254,
                "0xae": 174,
                # signed
                "-0x1": -1,
                "+0xff": 255,
                "-0xff": -255,
                # lossless past i64 (preserved by the recent lossless-int fix)
                "0xFFFFFFFFFFFFFFFF": 18446744073709551615,
                "0xFFFFFFFFFFFFFFFFFF": 4722366482869645213695,
            }
            for src, expected in cases.items():
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertEqual(node.value, expected, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.value, int, msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_hex_float_literal_c99(self):
            # `FLOATING_LITERAL` for hex-floats: strict C99 `HEX P [+-]? DEC+`
            # and `HEX DOT HEX* P [+-]? DEC+`. `p`/`P` is the *only* hex-float
            # exponent marker — `e`/`E` is always a hex digit in this
            # context. cpp used to route hex through `stoll` and return only
            # the leading hex integer; rust and python rejected entirely.
            cases = {
                # P-marker, no fraction
                "0x1p4": float.fromhex("0x1p4"),  # 16.0
                "0x1p+4": float.fromhex("0x1p+4"),  # 16.0
                "0x1p-4": float.fromhex("0x1p-4"),  # 0.0625
                "0xAp1": float.fromhex("0xap1"),  # 20.0
                "0xap1": float.fromhex("0xap1"),  # 20.0
                "0x0p0": float.fromhex("0x0p0"),  # 0.0
                "0xffp10": float.fromhex("0xffp10"),  # 261120.0
                # P-marker, with fraction
                "0x1.8p3": float.fromhex("0x1.8p3"),  # 12.0
                "0x1.0p3": float.fromhex("0x1.0p3"),  # 8.0
                "0xab.cdp4": float.fromhex("0xab.cdp4"),
                "0xff.fp-4": float.fromhex("0xff.fp-4"),
                # `e`/`E` is a hex digit even when adjacent to `p`. `0xep1`
                # is hex mantissa `0xe` (14) + `p1` exponent → 28.0.
                "0xep1": float.fromhex("0xep1"),  # 28.0
                "0xEp1": float.fromhex("0xep1"),
                "0xeep1": float.fromhex("0xeep1"),  # 476.0
                # Signed
                "-0x1p4": -float.fromhex("0x1p4"),  # -16.0
                "+0x1p4": float.fromhex("0x1p4"),  # 16.0
            }
            for src, expected in cases.items():
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.value, float, msg=f"{backend}: {src!r}")
                self.assertEqual(node.value, expected, msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_hex_e_is_hex_digit_not_exponent_marker(self):
            # `e`/`E` after a hex digit run does NOT act as a hex-float
            # exponent marker. `0x1e+4` is the hex integer `0x1e` (=30)
            # followed by an arithmetic `+4`, NOT the hex-float
            # `0x1 × 2^4` = 16. Only `p`/`P` marks a hex-float exponent;
            # this matches strict C99 and ClickHouse runtime semantics.
            for src, op, lhs, rhs in (
                ("0x1e+4", "+", 30, 4),
                ("0x1e-4", "-", 30, 4),
                ("0x1E+4", "+", 30, 4),
                ("0xe+5", "+", 14, 5),
                ("0xff-1", "-", 255, 1),
            ):
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.ArithmeticOperation, msg=f"{backend}: {src!r}")
                self.assertEqual(node.op, op, msg=f"{backend}: {src!r}")
                self.assertEqual(node.left.value, lhs, msg=f"{backend}: {src!r}")
                self.assertEqual(node.right.value, rhs, msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_hex_float_in_expression_context(self):
            # A hex-float literal participates in surrounding expressions
            # like any other Constant. Pins that the lexer recognises the
            # whole hex-float as one token.
            for src, op, lhs, rhs in (
                ("0x1p4 + 1", "+", float.fromhex("0x1p4"), 1),
                ("1 + 0x1p4", "+", 1, float.fromhex("0x1p4")),
                ("0x1p4 * 2", "*", float.fromhex("0x1p4"), 2),
            ):
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.ArithmeticOperation, msg=f"{backend}: {src!r}")
                self.assertEqual(node.op, op, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.left, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertIsInstance(node.right, ast.Constant, msg=f"{backend}: {src!r}")
                self.assertEqual(node.left.value, lhs, msg=f"{backend}: {src!r}")
                self.assertEqual(node.right.value, rhs, msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_hex_float_no_integer_part_rejected(self):
            # `0x.8p3` lacks a HEX_DIGIT+ before the dot — invalid per
            # both the FLOATING_LITERAL and HEXADECIMAL_LITERAL grammar.
            # All three backends must reject.
            with self.assertRaises(ExposedHogQLError, msg=f"{backend}: '0x.8p3'"):
                parse_expr("0x.8p3", backend=backend)

        @no_memory_leak_check
        def test_cast_type_arg_with_parenthesized_expr(self):
            # `CAST(x AS name(...))` parses the type as a columnTypeExpr; the
            # `ColumnTypeExprParam` form (`identifier LPAREN columnExprList?
            # RPAREN`) admits arbitrary column exprs in its argument list,
            # including ones with their own `(…)` groups. cpp builds a
            # TypeCast and captures the raw type text; the Rust parser fell
            # out of the CAST type-expr path when the type arg contained a
            # parenthesised expression and re-parsed the whole thing as a
            # plain `cast(...)` function call.
            cases = (
                "cast(x as a((b)))",
                "cast(x as a(case when (c) then d end))",
                "cast(x as a(if((c), d, e)))",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_subquery_arg_call_then_second_call(self):
            # `f(select 1)` is a `ColumnExprCallSelect` (`columnExpr LPAREN
            # selectSetStmt RPAREN`); a trailing `()` is a separate
            # `ColumnExprCall` postfix that nests on top — cpp builds
            # `ExprCall(Call(f, [SelectQuery]), [])`. The Rust parser folded
            # both groups into a single parametric `Call(params=[…], args=[…])`,
            # which is only valid when the first group is a columnExprList
            # (a SelectQuery is not).
            cases = (
                "f(select 1)()",
                "a(select 1)(2)",
                "f(select 1)(x)(y)",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_between_not_lambda_lower_bound(self):
            # `a BETWEEN <low> AND <high>` requires the low-bound parse to
            # leave its own AND available for the BETWEEN. With a bare
            # lambda low bound the Rust parser gets this right, but with
            # `NOT` wrapping the lambda the AND-reservation context is lost
            # across the `NOT` prefix into the lambda body, so the lambda
            # over-consumes `… and c` and the BETWEEN has no AND left.
            cases = (
                "a between not lambda x: b and c",
                "a between not x -> y and z",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_bare_asterisk_clause_body_after_comma(self):
            # A clause keyword after a trailing comma with a bare `*` body
            # starts its clause; the following LIMIT / WITH TOTALS / GROUP
            # BY is a normal subsequent clause. Same family as the existing
            # `test_clause_keyword_after_comma_in_select_columns`, but
            # uncovered for the bare-`*` body. The Rust parser used to keep
            # `where *` as a select column and choke on the trailing clause.
            cases = (
                "select a, where * limit 1",
                "select a, where * with totals",
                "select a, prewhere * with totals",
                "select a, where * group by x",
                "select a, where * order by x",
                "select a, having * limit 1",
                "select a, qualify * limit 1",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_placeholder_statement_then_postfix_call_or_property(self):
            # `{expr}` at statement start is a placeholder expression; a
            # trailing `(…)` call or `.x` property access is a postfix on
            # it. The Rust parser committed `{1}` to a `block` statement
            # and failed on the dangling postfix token. It already
            # reconsiders for `[` and `+`, so the disambiguation set is
            # incomplete (`(` and `.` were missing).
            cases = (
                "{1}()",
                "{1}.x",
                "{a}()",
                "{ {1}() }",
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_window_frame_bound_low_precedence_value(self):
            # A window frame bound's value is a full `columnExpr`, so it
            # admits comparison / AND / OR operators. The Rust parser
            # parsed it above comparison binding power and rejected
            # `ROWS a = b PRECEDING`.
            cases = (
                "SELECT count() OVER (ROWS a = b PRECEDING) FROM t",
                "SELECT count() OVER (ROWS a AND b FOLLOWING) FROM t",
                # guard: a BETWEEN frame still splits on its own AND
                "SELECT count() OVER (ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_join_op_modifier_arity_validation(self):
            # Per `HogQLParser.g4:127-134`, each joinOp alt restricts
            # ALL/ANY/ASOF to at most one occurrence; ANTI/SEMI combine
            # only with ASOF in inner-style and only as `ASOF (ANTI|SEMI)`
            # (the reverse order is invalid).
            from posthog.hogql.errors import BaseHogQLError

            invalid = (
                "SELECT 1 FROM a ANTI ASOF JOIN b ON 1",
                "SELECT 1 FROM a SEMI ASOF JOIN b ON 1",
                "SELECT 1 FROM a SEMI ANTI JOIN b ON 1",
                "SELECT 1 FROM a ALL ANTI JOIN b ON 1",
                "SELECT 1 FROM a ALL ASOF JOIN b ON 1",
                "SELECT 1 FROM a ALL ANY JOIN b ON 1",
            )
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Valid combinations still parse.
            for src in (
                "SELECT 1 FROM a ASOF JOIN b ON 1",
                "SELECT 1 FROM a ASOF ANTI JOIN b ON 1",
                "SELECT 1 FROM a ASOF SEMI JOIN b ON 1",
                "SELECT 1 FROM a ASOF LEFT JOIN b ON 1",
                "SELECT 1 FROM a SEMI LEFT JOIN b ON 1",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_group_by_all_falls_back_to_columns_on_postfix(self):
            # `groupByClause: GROUP BY (ALL | (CUBE|ROLLUP) LPAREN … |
            # GROUPING SETS LPAREN … | columnExprList)`. `ALL` is also a
            # keyword-as-identifier per the grammar's `keyword` rule, so
            # any postfix token after `ALL` makes cpp's ALL(*) fall back
            # to `columnExprList` with `Field('ALL')` as the first item.
            # Rust eagerly committed to the all-mode marker.
            for src in (
                "SELECT a FROM t GROUP BY ALL, b",
                "SELECT a FROM t GROUP BY ALL.x",
                "SELECT a FROM t GROUP BY ALL + 1",
                "SELECT a FROM t GROUP BY ALL[1]",
                "SELECT a FROM t GROUP BY ALL()",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guard: bare `ALL` (followed by a clause terminator) still
            # hits the all-mode marker.
            oracle = parse_select("SELECT a FROM t GROUP BY ALL", backend="cpp-json")
            got = parse_select("SELECT a FROM t GROUP BY ALL", backend=backend)
            self.assertEqual(clear_locations(got), clear_locations(oracle), msg=backend)

        @no_memory_leak_check
        def test_with_rollup_cube_totals_chain_grammar(self):
            # cpp: `groupByClause … (WITH (CUBE|ROLLUP))? (WITH TOTALS)?`.
            # At most one CUBE/ROLLUP, then optionally TOTALS, in order.
            # Rust accepted any number/order via an unbounded loop.
            from posthog.hogql.errors import BaseHogQLError

            invalid = (
                "SELECT a FROM t GROUP BY a WITH ROLLUP WITH CUBE",
                "SELECT a FROM t GROUP BY a WITH ROLLUP WITH ROLLUP",
                "SELECT a FROM t GROUP BY a WITH TOTALS WITH ROLLUP",
                "SELECT a FROM t GROUP BY a WITH TOTALS WITH TOTALS",
            )
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Valid combinations still parse.
            for src in (
                "SELECT a FROM t GROUP BY a WITH ROLLUP",
                "SELECT a FROM t GROUP BY a WITH CUBE",
                "SELECT a FROM t GROUP BY a WITH TOTALS",
                "SELECT a FROM t GROUP BY a WITH ROLLUP WITH TOTALS",
                "SELECT a FROM t GROUP BY a WITH CUBE WITH TOTALS",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_pivot_in_list_must_be_non_empty(self):
            # `pivotColumn: columnExprTupleOrSingle IN LPAREN columnExprList
            # RPAREN` — the columnExprList is non-empty. cpp rejects
            # empty `IN ()`; rust was silently producing an empty list.
            from posthog.hogql.errors import BaseHogQLError

            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT 1 FROM t PIVOT (sum(x) FOR y IN ())", backend="rust-json")
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT 1 FROM t PIVOT (sum(x) FOR y IN ())", backend="cpp-json")
            # Guard: populated list still parses.
            src = "SELECT 1 FROM t PIVOT (sum(x) FOR y IN (1, 2))"
            oracle = parse_select(src, backend="cpp-json")
            got = parse_select(src, backend=backend)
            self.assertEqual(clear_locations(got), clear_locations(oracle), msg=backend)

        @no_memory_leak_check
        def test_trim_substring_must_be_string_literal(self):
            # `TRIM (LEADING|TRAILING|BOTH string FROM columnExpr)` where
            # `string: STRING_LITERAL | templateString`. Rust accepted any
            # columnExpr in the substring slot; cpp rejects everything
            # except a string literal or template string.
            from posthog.hogql.errors import BaseHogQLError

            invalid = (
                "TRIM(BOTH x FROM y)",
                "TRIM(BOTH 1 FROM y)",
                "TRIM(BOTH f() FROM y)",
                "TRIM(LEADING (a) FROM y)",
            )
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # Guards: string literal + template string still parse.
            for src in ("TRIM(BOTH 'x' FROM y)", "TRIM(LEADING f'x' FROM y)"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_cte_list_paren_after_non_paren_cte(self):
            # A column-form CTE followed by a CTE whose head token is `(`
            # (paren-wrapped subquery or paren'd expression) must continue
            # the CTE list, not terminate it. The Rust parser used to break
            # the loop on the leading `(` because of the trailing-comma
            # tolerance for `, SELECT`.
            for src in (
                "WITH 1 AS x, (SELECT 1) AS y SELECT x, y",
                "WITH (SELECT 1) AS x, (SELECT 2) AS y SELECT x, y",
                "WITH 1 AS x, (a + b) AS y SELECT y",
                "WITH 1 AS x, (1) AS y SELECT y",
                "WITH 1 AS a, (x -> x + 1) AS f SELECT f(a)",
                "WITH count() AS c, (x -> x + 1) AS f SELECT f(c)",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_group_by_cube_rollup_continues_list(self):
            # cpp's ALL(*) treats `CUBE(...)` / `ROLLUP(...)` as ordinary
            # function calls when followed by `, <more>` keys; the
            # specialised `(CUBE|ROLLUP) LPAREN ... RPAREN` mode commits
            # only when no list continuation follows. Rust's eager commit
            # to the specialised branch swallowed the parens and left the
            # trailing `,` stranded.
            for src in (
                "SELECT * FROM t GROUP BY CUBE(a), ROLLUP(b)",
                "SELECT * FROM t GROUP BY CUBE(a), b",
                "SELECT * FROM t GROUP BY ROLLUP(a), b",
                "SELECT * FROM t GROUP BY a, CUBE(b)",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Bare `GROUP BY CUBE(...)` (no trailing keys) still uses the mode.
            for src in (
                "SELECT * FROM t GROUP BY CUBE(a)",
                "SELECT * FROM t GROUP BY ROLLUP(a)",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_trailing_comma_after_joined_table_chain(self):
            # cpp tolerates a stray trailing comma after a constrained JOIN
            # chain (`FROM a JOIN b ON 1,`) — the comma falls off the end
            # of the joinExpr without a following table atom. Rust's join
            # loop treated the comma unconditionally as a cross-join start
            # and demanded a following table atom.
            for src in (
                "SELECT * FROM a JOIN b ON 1,",
                "SELECT * FROM a JOIN b USING (x),",
                "SELECT * FROM a JOIN b ON 1 JOIN c ON 1,",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_unterminated_block_comment_lexes_as_div_asterisk(self):
            # cpp's ANTLR lexer only matches the `/* ... */` comment rule
            # when a closing `*/` is found. An unterminated `/*` falls back
            # to `/` and `*` tokens, which the parser then evaluates per
            # the normal expression grammar. Rust used to commit eagerly
            # to the comment-skip path and silently advance to EOF, so
            # `1 /* unclosed` was happily returning `Constant(1)` and
            # dropping the trailing garbage.
            for src in ("1 /*", "1 /* "):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

            # Unterminated `/*` followed by ident content lexes as
            # `1 / * ident`, which fails the expression parse with a
            # trailing-tokens / extraneous-input error in all three
            # backends (rather than silently consuming the rest as a
            # comment).
            from posthog.hogql.errors import BaseHogQLError

            for src in ("1 /* unclosed", "a /* unclosed"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)

            # Closed `/* ... */` is still trivia in all three backends.
            oracle = parse_expr("1 /* ok */ + 2", backend="cpp-json")
            got = parse_expr("1 /* ok */ + 2", backend=backend)
            self.assertEqual(clear_locations(got), clear_locations(oracle), msg=backend)

        @no_memory_leak_check
        def test_interpolate_no_trailing_comma(self):
            # `INTERPOLATE LPAREN interpolateExpr (COMMA interpolateExpr)*
            # RPAREN` — no trailing comma. cpp rejects; rust was accepting.
            from posthog.hogql.errors import BaseHogQLError

            with self.assertRaises((BaseHogQLError, SyntaxError), msg=backend):
                parse_select(
                    "SELECT 1 FROM t ORDER BY x WITH FILL INTERPOLATE (y,)",
                    backend=backend,
                )

        @no_memory_leak_check
        def test_boolean_dot_chain_is_field_not_array_access(self):
            # `true.x` / `false.x` is a property chain — cpp treats `true` /
            # `false` as ordinary identifiers in `columnIdentifier` chain
            # position and builds `Field(['true', 'x'])`. Rust was committing
            # the bool as `Constant(true)` first, then wrapping in
            # `ArrayAccess` via the Pratt `.` postfix.
            cases = ("true.x", "false.x", "TRUE.x", "true.x.y", "false.foo.bar")
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guards: bare `true` / `false` stay Bool constants; `true(1)` is
            # a function call (ident path).
            for src in ("true", "false", "true(1)"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_using_empty_parens_rejected(self):
            # `joinConstraintClause`: `USING LPAREN columnExprList RPAREN`
            # / `USING columnExprList` — both require a non-empty list. cpp
            # rejects `USING ()`; rust was producing an empty list.
            from posthog.hogql.errors import BaseHogQLError

            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT * FROM a JOIN b USING ()", backend="rust-json")
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT * FROM a JOIN b USING ()", backend="cpp-json")
            # Populated USING still parses.
            src = "SELECT * FROM a JOIN b USING (x)"
            oracle = parse_select(src, backend="cpp-json")
            got = parse_select(src, backend=backend)
            self.assertEqual(clear_locations(got), clear_locations(oracle), msg=backend)

        @no_memory_leak_check
        def test_group_by_cube_rollup_empty_is_function_call(self):
            # Empty `CUBE()` / `ROLLUP()` — cpp parses these as function
            # calls (the GROUP BY position carries one Call element, no
            # group_by_mode); rust's dedicated CUBE / ROLLUP handler ate
            # the empty parens and emitted `group_by=[]` + the mode marker.
            for src in ("SELECT 1 GROUP BY CUBE()", "SELECT 1 GROUP BY ROLLUP()"):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Populated CUBE / ROLLUP still uses the mode marker.
            src = "SELECT 1 GROUP BY CUBE(a, b)"
            oracle = parse_select(src, backend="cpp-json")
            got = parse_select(src, backend=backend)
            self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_quoted_identifier_backslash_escapes(self):
            # `QUOTED_IDENTIFIER` grammar (`HogQLLexer.common.g4:160-163`):
            #   QUOTE_DOUBLE (~([\\"]) | ESCAPE_CHAR_COMMON | BACKSLASH QUOTE_DOUBLE | QUOTE_DOUBLE QUOTE_DOUBLE)* QUOTE_DOUBLE
            # — so `\"` inside `"..."` is a valid escape. Rust's lex_quoted_ident
            # treated `\` as just another body byte, terminating the ident
            # at the next unescaped `"` and rejecting the trailing `"`.
            cases = (
                '"\\""',
                '"a\\"b"',
                '"\\\\"',
                '"a"',
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_reserved_keywords_rejected_as_identifiers(self):
            # Grammar's `identifier` rule (`IDENTIFIER | QUOTED_IDENTIFIER |
            # interval | keyword`) excludes NULL_SQL / INF / NAN_SQL /
            # EXCEPT / INTERSECT and the Hog-statement keywords (FN / FUN /
            # LET / WHILE / THROW / TRY / CATCH / FINALLY) — `keyword` lists
            # them out. cpp therefore rejects these as Field-chain links,
            # aliases, table identifiers, CTE column names, etc. Rust's
            # dotted-chain / alias / table-ident / columnAliases handlers
            # were accepting any `Keyword(_)` token without gating, so all
            # of these slipped through as identifiers.
            from posthog.hogql.errors import BaseHogQLError

            expr_invalid = (
                # Postfix DOT
                "a.except",
                "a.intersect",
                "a.null",
                "a.inf",
                "a.nan",
                "a.fn",
                "a.fun",
                "a.let",
                "a.while",
                "a.throw",
                "a.try",
                "a.catch",
                "a.finally",
                "a.b.except",
                # Postfix `?.`
                "a?.except",
                "a?.null",
                "a?.inf",
            )
            for src in expr_invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)

            select_invalid = (
                # Alias position
                "SELECT a AS except FROM t",
                "SELECT a AS intersect FROM t",
                "SELECT a AS inf FROM t",
                "SELECT a AS nan FROM t",
                "SELECT a AS fn FROM t",
                "SELECT a AS let FROM t",
                # Table identifier
                "SELECT * FROM except.x",
                "SELECT * FROM x.except",
                "SELECT * FROM null.x",
                "SELECT * FROM fn.x",
                # WHERE / columnExpr position
                "SELECT 1 FROM t WHERE a.except",
                # CTE column-name list
                "WITH x (except, intersect) AS (SELECT 1, 2) SELECT * FROM x",
                "WITH x (a, null) AS (SELECT 1, 2) SELECT * FROM x",
                # columnAliases on subquery
                "SELECT a FROM (SELECT 1) AS x (except)",
            )
            for src in select_invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Guard: keywords that ARE valid identifiers per cpp's grammar
            # (interval units, plain keywords like CASE/DAY) still parse.
            for src in (
                "a.case",
                "a.day",
                "day.minute",
                "select.from",
                "SELECT a AS case FROM t",
                "SELECT a AS day FROM t",
            ):
                if "SELECT" in src:
                    self.assertIsNotNone(parse_select(src, backend=backend), msg=f"{backend}: {src!r}")
                else:
                    self.assertIsNotNone(parse_expr(src, backend=backend), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_bare_asterisk_replace_only_inside_parens(self):
            # `ColumnExprAsterisk` (grammar line 289) admits ONLY an optional
            # trailing EXCLUDE on a bare `*`. `REPLACE` after `*` is valid
            # exclusively inside the paren-wrapped forms `(* REPLACE (…))`,
            # `(* EXCLUDE (…) REPLACE (…))`, and the `COLUMNS(* … REPLACE …)`
            # family. cpp rejects bare-`*` REPLACE at the top level; rust
            # was accepting it via the universal columns-decorator parse.
            from posthog.hogql.errors import BaseHogQLError

            invalid_select = ("SELECT * REPLACE (b AS a) FROM t",)
            for src in invalid_select:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_expr("* REPLACE (a AS b)", backend="rust-json")
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_expr("* REPLACE (a AS b)", backend="cpp-json")
            # Paren-wrapped form (and `EXCLUDE` decoration alone) still parse.
            for src in (
                "(* REPLACE (1 AS event))",
                "(* EXCLUDE (a) REPLACE (b AS c))",
                "* EXCLUDE (a)",
            ):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_filter_clause_invalid_before_within_group(self):
            # `ColumnExprFunctionWithinGroup` (grammar line 234) is
            # `identifier LPAREN columnExprList? RPAREN withinGroupClause`
            # — no FILTER slot. cpp rejects
            # `f(args) FILTER (WHERE ...) WITHIN GROUP (...)`; rust was
            # silently dropping the FILTER expression.
            from posthog.hogql.errors import BaseHogQLError

            for src in (
                "median(x) FILTER (WHERE z) WITHIN GROUP (ORDER BY y)",
                "quantile(x) FILTER (WHERE z > 0) WITHIN GROUP (ORDER BY y)",
            ):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # WITHIN GROUP alone still parses.
            oracle = parse_expr("median(x) WITHIN GROUP (ORDER BY y)", backend="cpp-json")
            got = parse_expr("median(x) WITHIN GROUP (ORDER BY y)", backend=backend)
            self.assertEqual(clear_locations(got), clear_locations(oracle), msg=backend)

        @no_memory_leak_check
        def test_window_function_args_no_distinct_no_inline_order_by(self):
            # `ColumnExprWinFunction` (grammar line 235) takes a plain
            # `columnExprList` — no DISTINCT, no in-args ORDER BY. cpp
            # rejects `foo(DISTINCT a) OVER ()` and `foo(a ORDER BY b)
            # OVER ()`; rust was accepting and silently dropping the
            # DISTINCT / ORDER BY.
            from posthog.hogql.errors import BaseHogQLError

            for src in (
                "foo(a ORDER BY b) OVER ()",
                "foo(DISTINCT a) OVER ()",
                "foo(DISTINCT a ORDER BY b) OVER ()",
            ):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # Plain forms still parse.
            for src in ("foo(a) OVER ()", "foo(DISTINCT a)", "foo(a ORDER BY b)"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_unary_plus_only_on_numeric_literal(self):
            # `numberLiteral` grammar (line 380) makes `+` a sign prefix on
            # number / INF / NAN — not a general unary operator. cpp rejects
            # `+a`, `+f(x)`, `+(a)`, etc.; rust was bumping the `+` as a
            # no-op prefix and returning the RHS unchanged.
            from posthog.hogql.errors import BaseHogQLError

            invalid = ("+a", "+(a)", "+(+a)", "+f(x)")
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # Numeric / INF / NAN forms still parse identically.
            for src in ("+1", "+1.5", "+inf", "+nan"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                # NaN comparison is identity-only; pin parsing-success and
                # node-type rather than full equality.
                self.assertIsNotNone(got, msg=f"{backend}: {src!r}")
                if src not in ("+nan",):
                    self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_column_cte_requires_identifier_after_as(self):
            # `withExpr: columnExpr AS identifier` — the post-AS token must
            # be a valid identifier (incl. allowed keywords), not a number
            # / string / parenthesised group. cpp rejects; rust was using
            # the raw token text as the CTE name (e.g. `name='1'` for a
            # `WITH a AS 1` CTE).
            from posthog.hogql.errors import BaseHogQLError

            invalid = (
                "WITH a AS 1 SELECT a",
                "WITH 1 + 1 AS 1 SELECT 1",
                "WITH 1 + 1 AS 'foo' SELECT 'foo'",
            )
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Identifier names continue to work.
            oracle = parse_select("WITH a AS b SELECT b", backend="cpp-json")
            got = parse_select("WITH a AS b SELECT b", backend=backend)
            self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}")

        @no_memory_leak_check
        def test_limit_offset_with_ties_must_precede_offset(self):
            # `limitAndOffsetClause` has two alternatives:
            #   compact: `LIMIT n PERCENT? (COMMA n)? (WITH TIES)?`
            #   verbose: `LIMIT n PERCENT? (WITH TIES)? OFFSET n`
            # `LIMIT n OFFSET m WITH TIES` doesn't match either — WITH TIES
            # must precede OFFSET in the verbose form. cpp rejects; rust
            # was accepting because `parse_limit_clauses` checked for WITH
            # TIES after both the Comma and Offset tails.
            from posthog.hogql.errors import BaseHogQLError

            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT a FROM t LIMIT 1 OFFSET 2 WITH TIES", backend="rust-json")
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT a FROM t LIMIT 1 OFFSET 2 WITH TIES", backend="cpp-json")
            # Both valid forms still parse.
            for src in (
                "SELECT a FROM t LIMIT 1 WITH TIES OFFSET 2",
                "SELECT a FROM t LIMIT 1, 2 WITH TIES",
                "SELECT a FROM t LIMIT 1 WITH TIES",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_pivot_in_separator_extends_via_postfix_call(self):
            # `pivotColumn: columnExprTupleOrSingle IN LPAREN columnExprList
            # RPAREN`. The LHS columnExprTupleOrSingle is a full columnExpr,
            # so cpp's ALL(*) greedy-extends it past any `IN (...)` group
            # whose closing `)` is followed by another `(` (a postfix call
            # on whatever LHS has built so far). Only the LAST `IN (...)`
            # — the one NOT followed by `(` — is the structural separator.
            # Rust's prior heuristic locked the FIRST depth-0 IN as the
            # structural one, mis-splitting `y IN (1) (2) IN (3)`.
            cases = (
                # Same shape, two pivotColumns split at the FIRST IN (b
                # after the first close means LHS-extension fails, so the
                # first IN is structural).
                "SELECT 1 FROM t PIVOT (s FOR a IN (1) b IN (2))",
                # ONE pivotColumn — LHS = `y IN (1)(2)` (CompareOperation
                # with postfix-call right), structural IN at the SECOND
                # depth-0 position.
                "SELECT 1 FROM t PIVOT (sum(x) FOR y IN (1) (2) IN (3))",
                # Baselines that must keep working.
                "SELECT 1 FROM t PIVOT (sum(x) FOR y IN (1, 2))",
                "SELECT 1 FROM t PIVOT (sum(x) FOR (y, z) IN ((a, b), (c, d)))",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_return_expr_prefix_shortened_when_assignment_follows(self):
            # `returnStmt: RETURN columnExpr? SEMICOLON?` — the columnExpr is
            # optional. When the full following expression would strand a
            # `:=`, cpp's ANTLR ALL(*) backtracks to the shortest expression
            # PREFIX that leaves the rest parseable as the next statement.
            # The shortenings cpp prefers:
            #
            #   `return * columns(…) := X` → expr = Field(['*']); the
            #     `columns(…) := X` is a VarAssignment with the columns
            #     call as its lvalue.
            #   `return columns(…) := X` → expr = Field(['columns']); the
            #     parens become a parenthesised columnExpr that takes `:=`.
            #
            # Rust's prior lookahead bailed all the way to a bare return,
            # producing a divergent AST shape.
            cases = (
                "fn f() { return * columns('a') := columns('b') }",
                "fn f() { return columns('a') := columns('b') }",
                "fn f() { return * x := y }",
                "fn f() { return *x := y }",
                # Guard cases that should *not* shorten:
                "fn f() { return X := Y }",  # NamedArgument inside return
                "fn f() { return a.b := c }",  # No valid prefix; bare return
                "fn f() { return * }",  # Bare asterisk
                "fn f() { return *columns('a') }",  # No `:=`; full SpreadExpr
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_interpolate_as_lambda_value(self):
            # `interpolateExpr: columnExpr (AS columnExpr)?` — both sides
            # are full `columnExpr`s, so the AS-value may be a lambda
            # (`LAMBDA y: y+1` or `y -> y+1`). cpp's ALL(*) sees the
            # lambda body after AS and backtracks the alias alternative;
            # rust's Pratt parser greedy-folded `a AS LAMBDA` into a
            # ColumnExprAlias before the outer INTERPOLATE rule got the
            # AS, leaving the lambda body stranded.
            cases = (
                "SELECT 1 ORDER BY x INTERPOLATE (a AS LAMBDA y: y+1)",
                "SELECT 1 ORDER BY x INTERPOLATE (a AS y -> y+1)",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guard: AS with a non-lambda RHS still folds as an alias
            # (`AS 5` in INTERPOLATE keeps AS for the outer); AS with
            # a regular identifier RHS is a normal column alias.
            for src in (
                "SELECT a AS my_alias FROM t",
                'SELECT a AS "my alias" FROM t',
                "SELECT 1 ORDER BY x INTERPOLATE (a AS 5)",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_hogqlx_tag_in_from_paren_decorations(self):
            # `(<Tag/>)` parses as `LPAREN joinExpr RPAREN` where the inner
            # `joinExpr → tableExpr → hogqlxTagElement`. Per the grammar:
            #   - Inside the parens: `tableExpr (alias | AS identifier)` and
            #     `JoinExprTable (... FINAL? sampleClause?)` bind to the tag.
            #   - Outside the parens: the wrapper is `JoinExprParens` (a
            #     joinExpr alt), not a `tableExpr` — alias / FINAL / SAMPLE
            #     cannot bind (same root cause as the parens-alias fix).
            # Rust had a `(<Tag />)` shortcut that returned a bare tag,
            # bypassing both sides — accepting outer decorations and
            # rejecting inner ones.
            from posthog.hogql.errors import BaseHogQLError

            accept = (
                "SELECT 1 FROM (<Tag /> AS y)",
                "SELECT 1 FROM (<Tag /> JOIN b ON x)",
                "SELECT 1 FROM (<Tag /> FINAL)",
            )
            for src in accept:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

            reject = (
                "SELECT 1 FROM (<Tag />) AS x",
                "SELECT 1 FROM (<Tag />) x",
                "SELECT 1 FROM (<Tag />) FINAL",
            )
            for src in reject:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)

        @no_memory_leak_check
        def test_hogqlx_tag_text_accepts_arbitrary_non_brace_non_lt(self):
            # cpp's `HOGQLX_TEXT_TEXT: ~[<{]+` — any byte except `<` and `{`
            # is valid tag-body text. Rust's mode-less lexer rejected `&`,
            # `!`, `@`, etc. when pre-loading peek1 across the `>` / `/>` /
            # closing `>` boundary, before `consume_hogqlx_text` could
            # byte-walk the body.
            cases = (
                "<a>foo&bar</a>",
                "<a>foo!</a>",
                "<a>foo@bar</a>",
                "<a>1 + 2</a>",
                "<a>!@#%^*()</a>",
                "<outer><inner>foo!bar</inner>baz&qux</outer>",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_hogqlx_tag_identifier_allows_hyphens(self):
            # The grammar's `HOGQLX_TAG_OPEN` / `HOGQLX_TAG_CLOSE` lexer modes
            # (`HogQLLexer.common.g4:315 + 326`) admit
            # `[a-zA-Z_][a-zA-Z0-9_-]*` for tag names AND attribute names,
            # so hyphens are part of the identifier inside tag delimiters.
            # Rust's mode-less lexer split `a-b` into Ident-Dash-Ident, and
            # `parse_hogqlx_identifier` returned only the first chunk.
            cases = (
                "<a-b />",
                "<a-b-c />",
                "<my-tag a-b={1}>x</my-tag>",
                "<tag a-b={1}/>",
                "<tag><my-child/></tag>",
                "<a-b>{1}</a-b>",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_join_expr_parens_does_not_take_outer_alias(self):
            # Grammar:
            #   joinExpr  : ... | LPAREN joinExpr RPAREN  # JoinExprParens
            #   tableExpr : ... | tableExpr (alias | AS identifier) columnAliases?
            #                                            # TableExprAlias
            # `TableExprAlias` requires a `tableExpr` head — `LPAREN joinExpr
            # RPAREN` is a `joinExpr`, not a `tableExpr`. cpp rejects the
            # alias / FINAL / SAMPLE after the closing paren; rust was
            # attaching the alias onto the inner JoinExpr.
            from posthog.hogql.errors import BaseHogQLError

            invalid = (
                "SELECT 1 FROM (t) AS x",
                "SELECT 1 FROM (t) x",
                "SELECT 1 FROM ((t)) AS x",
                "SELECT 1 FROM (t JOIN b ON x) AS y",
                "SELECT 1 FROM (t) FINAL",
            )
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Guards: subquery and non-parenthesised aliases still parse.
            valid = (
                "SELECT 1 FROM t",
                "SELECT 1 FROM t AS x",
                "SELECT 1 FROM (SELECT 1)",
                "SELECT 1 FROM (SELECT 1) AS x",
            )
            for src in valid:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_string_literal_unknown_backslash_escapes_rejected(self):
            # `ESCAPE_CHAR_COMMON` (`HogQLLexer.common.g4:145`) is a closed
            # set: `\b \f \r \n \t \0 \a \v \\ \xNN`, plus `\'` (escape
            # quote) inside a STRING_LITERAL. Anything else — `\g`, `\u…`,
            # `\1`, bare `\x` without two hex digits — is a lexer error.
            # Rust's `lex_string` silently accepted any two-byte escape,
            # keeping `\g` as literal `\g` etc.
            from posthog.hogql.errors import BaseHogQLError

            invalid = (
                r"'\x'",  # \x without two hex digits
                r"'\g'",  # unknown escape letter
                "'\\u00AB'",  # \u not in cpp grammar
                r"'\1'",  # \1 not in cpp grammar
                r"'\999'",  # \9 not in cpp grammar
            )
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # Guard: every grammar-allowed escape still parses.
            valid = (
                r"'\n'",
                r"'\t'",
                r"'\\'",
                r"'\''",
                r"'\xAB'",
                r"'\b'",
                r"'\xFF'",
            )
            for src in valid:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_sample_clause_leading_dot_float_value(self):
            # Leading-dot floats (`.5`, `.04`) are valid `floatingLiteral`s
            # in the grammar (`DOT DECIMAL_LITERAL E?...`). The lexer
            # tokenises them as `Dot` + `Number`, so the SAMPLE ratio gate
            # must admit `Dot` when it leads a Number.
            # (NaN-bearing case kept finite — NaN != NaN under == comparison.)
            cases = (
                "SELECT 1 FROM t SAMPLE .5",
                "SELECT 1 FROM t SAMPLE .04",
                "SELECT 1 FROM t SAMPLE .5 / 2",
                "SELECT 1 FROM t SAMPLE 1 / .04",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_sample_clause_only_accepts_number_literals(self):
            # `ratioExpr: placeholder | numberLiteral (SLASH numberLiteral)?`
            # — each side of the ratio is a `numberLiteral`, not a generic
            # `columnExpr`. Rust's `consume_ratio_value` called the prefix
            # parser so Fields, TupleAccess, and placeholder-as-RHS all
            # landed in the ratio slot.
            from posthog.hogql.errors import BaseHogQLError

            invalid = (
                "SELECT * FROM t SAMPLE a",
                "SELECT * FROM t SAMPLE x.y",
                "SELECT * FROM t SAMPLE 1/{p}",
                "SELECT * FROM t SAMPLE 1+1",
            )
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Guard: every grammar-allowed SAMPLE form still parses.
            valid = (
                "SELECT * FROM t SAMPLE 1",
                "SELECT * FROM t SAMPLE 1/2",
                "SELECT * FROM t SAMPLE {p}",
                "SELECT * FROM t SAMPLE 0.5",
                "SELECT * FROM t SAMPLE 1 OFFSET 2",
            )
            for src in valid:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_join_op_grammar_alts_validation(self):
            # `joinOp` has three disjoint alts (`HogQLParser.g4:127-134`):
            # JoinOpInner, JoinOpLeftRight, JoinOpFull. Each keyword appears
            # at most once per alt, and the three alts don't share INNER /
            # LEFT / RIGHT / FULL. Rust's source-order loop set booleans
            # without de-duplicating or cross-validating, so it accepted
            # `INNER LEFT`, `LEFT OUTER LEFT`, `FULL INNER`, etc.
            from posthog.hogql.errors import BaseHogQLError

            invalid = (
                "SELECT 1 FROM a INNER LEFT JOIN b ON 1",
                "SELECT 1 FROM a INNER OUTER JOIN b ON 1",
                "SELECT 1 FROM a INNER INNER JOIN b ON 1",
                "SELECT 1 FROM a LEFT OUTER LEFT JOIN b ON 1",
                "SELECT 1 FROM a FULL INNER JOIN b ON 1",
            )
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Guard: every grammar-allowed JOIN op still parses.
            valid = (
                "SELECT 1 FROM a JOIN b ON 1",
                "SELECT 1 FROM a INNER JOIN b ON 1",
                "SELECT 1 FROM a LEFT JOIN b ON 1",
                "SELECT 1 FROM a RIGHT JOIN b ON 1",
                "SELECT 1 FROM a LEFT OUTER JOIN b ON 1",
                "SELECT 1 FROM a FULL JOIN b ON 1",
                "SELECT 1 FROM a FULL OUTER JOIN b ON 1",
                "SELECT 1 FROM a INNER ALL JOIN b ON 1",
                "SELECT 1 FROM a ALL INNER JOIN b ON 1",
                "SELECT 1 FROM a ASOF JOIN b ON 1",
                "SELECT 1 FROM a ASOF LEFT JOIN b ON 1",
            )
            for src in valid:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_capital_F_template_string_only_in_full_template_context(self):
            # The grammar has two template-string tokens:
            #   `QUOTE_SINGLE_TEMPLATE: 'f\'' -> pushMode(IN_TEMPLATE_STRING);`
            #   `QUOTE_SINGLE_TEMPLATE_FULL: 'F\'' -> pushMode(IN_FULL_TEMPLATE_STRING);`
            # The lowercase `f'` is reachable from `templateString` (a valid
            # `columnExpr`); the uppercase `F'` is reachable only via the
            # `fullTemplateString` entry rule (e.g. SQL template files), never
            # as a column expression. Rust's lexer collapsed both into the same
            # token and the parser accepted `F'…'` anywhere `f'…'` is allowed.
            from posthog.hogql.errors import BaseHogQLError

            for src in ("F'hello'", "F''", "F'{1+2}'"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # Guard: lowercase form remains a valid column expression.
            for src in ("f'hello'", "f'{1+2}'"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_empty_paren_only_clauses_rejected(self):
            # Three places where the grammar requires at least one body element
            # when parens are present, but rust was accepting bare `()`:
            #   `columnAliases: LPAREN identifier (COMMA identifier)* RPAREN`
            #   `interpolateClause: INTERPOLATE (LPAREN interpolateExpr (COMMA
            #     interpolateExpr)* RPAREN)?`
            #   `columnsReplaceList: columnsReplaceItem (COMMA
            #     columnsReplaceItem)*` (no trailing comma)
            from posthog.hogql.errors import BaseHogQLError

            invalid_select = (
                "SELECT * FROM t AS x ()",
                "SELECT 1 ORDER BY x INTERPOLATE ()",
            )
            for src in invalid_select:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)

            invalid_expr = (
                "COLUMNS(* REPLACE (b AS c,))",
                "COLUMNS(* EXCLUDE (a) REPLACE (b AS c,))",
            )
            for src in invalid_expr:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)

            # Guards: populated / bare-keyword forms still parse.
            for src in (
                "SELECT * FROM t AS x (a)",
                "SELECT * FROM t AS x (a, b)",
                "SELECT 1 ORDER BY x INTERPOLATE (a AS b)",
                "SELECT 1 ORDER BY x INTERPOLATE",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            for src in (
                "COLUMNS(* REPLACE (a AS b, c AS d))",
                "COLUMNS(* REPLACE (a AS b))",
            ):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_bare_zero_x_prefix_lexes_as_zero_plus_ident(self):
            # `HEXADECIMAL_LITERAL: '0' X HEX_DIGIT+` — the grammar requires
            # at least one hex digit after `0x`. Rust's `lex_number` was
            # committing the `0x` prefix unconditionally and emitting an
            # empty-body hex token, so `SELECT 0x AS y` lexed as `0x AS y`
            # (an empty hex aliased to `y`) instead of `0 x AS y` (which cpp
            # rejects because `x` is an ident in mid-expression position).
            from posthog.hogql.errors import BaseHogQLError

            cases = (
                "SELECT 0x AS y",
                "SELECT 0x + 1",
            )
            for src in cases:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=src):
                    parse_select(src, backend="rust-json")
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=src):
                    parse_select(src, backend="python")
            # Valid hex literals (≥ 1 hex digit) must keep working.
            for src in ("SELECT 0x1", "SELECT 0xFF", "SELECT 0xaB"):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_cast_type_param_group_mode_classification(self):
            # cpp's ANTLR commits an `IDENT(...)` type expression to a single
            # alternative — Nested / Complex / Param / Enum — based on what's
            # inside. Param (visited via `ctx->getText()`) preserves case,
            # keeps quoted identifiers' quotes, and concatenates spacelessly.
            # Complex / Nested (recursive visit) lowercases idents and joins
            # with `, `. The Rust parser was deciding mode per-item, so a mix
            # of `#1` + a type-shaped sibling rendered the type-shaped sibling
            # with `, ` joining instead of the Param-mode spaceless form.
            cases = (
                # All items expr-shaped — Param mode end-to-end.
                "cast(x as DateTime64(3, 'UTC'))",
                'cast(x as DateTime64(3, "UTC"))',
                "cast(x as Foo(#1, ABC))",
                # Mixed: `#1` forces Param mode for the whole group, so the
                # sibling `Bar(a, b)` is rendered via getText (spaceless +
                # case-preserved).
                "cast(x as Foo(#1, Bar(a, b)))",
                "cast(x as Foo(Bar(a, b), #1))",
                "cast(x as Foo(#1, f(g(a, b), h(c, d))))",
                # Depth-1 `8` inside `FixedString(8)` doesn't escalate the
                # outer Foo to Param — Foo stays Complex.
                "cast(x as Foo(FixedString(8)))",
                "cast(x as Foo(g(#1)))",
                # All items type-shaped — Complex mode (lowercased + `, `).
                "cast(x as Foo(a(b, c), d))",
                "cast(x as Tuple(a Int, b Int))",
                # Top-level operator forces Param mode.
                "cast(x as Foo(a, b*c))",
                # Per-item raw fallback: `case when (c) then d end` has no
                # depth-0 expression markers (the `(c)` lives at depth 1),
                # but it's not a valid type — cpp resolves to Param.
                "cast(x as Foo(case when (c) then d end))",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_hogqlx_comments_skipped_between_attributes(self):
            # The HOGQLX_TAG_OPEN / HOGQLX_TAG_CLOSE lexer modes used to
            # have no comment rules and no catch-all, so the lexer's
            # recoverable token-recognition error silently dropped comment
            # delimiters and re-tokenised the identifier-shaped content as
            # phantom attribute names — `<a /*c*/ b={1}/>` emitted both
            # `c` and `b`. Add comment-skip + UNEXPECTED_CHARACTER catch-all
            # to both modes.
            cases = (
                "<a /*c*/ b={1}/>",
                "<a /* c */b={1}/>",
                "<a -- comment\n b={1}/>",
                "<a // comment\n b={1}/>",
                "<a /*c*/ />",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Unknown bytes (`#`, `&`, `@`) inside a tag now reject in cpp
            # via the UNEXPECTED_CHARACTER catch-all, matching rust's
            # existing rejection. Both raise.
            for src in ("<a # comment\n />", "<a @x b={1}/>"):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="rust-json")

        @no_memory_leak_check
        def test_float_subnormal_preserved_not_flattened_to_infinity(self):
            # cpp's `visitNumberLiteral` used to call `std::stod` (which
            # throws `out_of_range` for BOTH overflow and underflow) and
            # mapped any out-of-range exception to `value="Infinity"`,
            # losing the actual subnormal value. Use `strtod` + errno
            # inspection so a true overflow still yields Infinity but an
            # underflow keeps the subnormal value (or `0.0` below the
            # smallest subnormal). Rust always preserved the value
            # via `parse::<f64>()` — this test pins both sides.
            cases_subnormal = (
                ("1e-310", 1e-310),
                ("5e-324", 5e-324),
                ("-1e-310", -1e-310),
            )
            for src, expected in cases_subnormal:
                got = parse_expr(src, backend=backend)
                self.assertEqual(got.value, expected, msg=f"{backend}: {src!r}")
            # Below the smallest subnormal → `0.0` on both sides.
            for src in ("1e-325", "-1e-400"):
                got = parse_expr(src, backend=backend)
                self.assertEqual(got.value, 0.0, msg=f"{backend}: {src!r}")
            # True overflow → `\"Infinity\"` / `\"-Infinity\"` on both.
            for src, expected in (("1e+400", float("inf")), ("-1e+400", float("-inf"))):
                got = parse_expr(src, backend=backend)
                self.assertEqual(got.value, expected, msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_stmt_rhs_pratt_recovers_on_infix_rhs_failure(self):
            # cpp's ALL(*) splits `let x := {} * ()` into two declarations
            # because the `* ()` infix would need a valid columnExpr RHS,
            # and the empty `()` rejects. The trailing operator and its
            # operand become the next statement (`*` as Field, `()` as a
            # postfix call → `Call(Field("*"), [])`). The Rust Pratt loop
            # used to hard-error on the RHS-parse failure and abort the
            # entire varDecl.
            cases = (
                "let x := {} * ()",
                "{ let x := {} * () }",
                "a := {} * ()",
                "return {} * ()",
                "let x := f() * ()",
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guard: the recovery only fires when the RHS actually fails.
            # A valid full expression still parses greedily.
            for src in (
                "let x := {} * (1)",
                "let x := 1 + 2",
                "let x := 1",
            ):
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_unpivot_emits_include_nulls_false_by_default(self):
            # cpp's `VISIT(JoinExprUnpivot)` always emits the
            # `include_nulls` field — default `false` when the
            # `INCLUDE NULLS` modifier isn't present. Rust used to omit
            # the field entirely on the no-NULLS path. Emit
            # unconditionally to match the JSON shape.
            cases = (
                "SELECT * FROM t UNPIVOT (val FOR month IN (a, b))",
                "SELECT * FROM t UNPIVOT INCLUDE NULLS (val FOR month IN (a, b))",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_not_with_keyword_infix_treats_not_as_field(self):
            # cpp's ALL(*) prefers `Field([not]) <kw-infix> <rhs>` over
            # `Not(Field([kw]))` when the infix has a valid trailing RHS.
            # `NOT LIKE 'a'` → `Compare(Field(not), "like", 'a')`; but
            # `not like` alone → `Not(Field(like))`. Same disambiguation
            # for LIKE / ILIKE / BETWEEN and the IS [NOT] NULL / IS
            # DISTINCT FROM shape. Rust used to unconditionally treat
            # `NOT <kw>` as the unary form and choke on the trailing rhs.
            cases = (
                "NOT BETWEEN 1 AND 2",
                "NOT LIKE 'a'",
                "NOT IS NULL",
                "NOT ILIKE 'a'",
                "NOT IS NOT NULL",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guards: the unary-NOT shapes still work when the trailing
            # rhs is a complete columnExpr (no kw-infix gap).
            for src in (
                "NOT x",
                "not like",  # no rhs → unary NOT on Field(like)
                "not in (1,2)",  # IN takes a paren-list, parses as Not(Call(in))
                "NOT IN (1)",
            ):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_multi_join_with_stacked_on_using_clauses(self):
            # cpp's left-recursive `joinExpr: joinExpr JOIN joinExpr
            # joinConstraintClause?` parses `a JOIN b JOIN c ON1 ON2`
            # right-associatively: ON1 attaches to the innermost JOIN
            # (`c`), ON2 to the next outer (`b`). The Rust JOIN loop was
            # left-to-right and only consumed one constraint per JOIN,
            # leaving subsequent ON / USING constraints stranded. After
            # the loop, peel off any extra constraints and attach them
            # inward-to-outward along the chain.
            cases = (
                "SELECT * FROM a JOIN b JOIN c ON 1 ON 2",
                "SELECT * FROM a JOIN b JOIN c ON a.x=b.x ON b.y=c.y",
                "SELECT * FROM a INNER JOIN b INNER JOIN c ON 1 ON 1",
                "SELECT * FROM a JOIN b JOIN c USING (x) USING (y)",
                "SELECT * FROM a JOIN b JOIN c JOIN d ON 1 ON 2 ON 3",
            )
            for src in cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guards: the interleaved / single-constraint shapes still
            # parse the same way.
            for src in (
                "SELECT * FROM a JOIN b ON 1 JOIN c ON 1",
                "SELECT * FROM a JOIN b ON 1",
                "SELECT * FROM a JOIN b USING (x)",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_enum_cast_rejected_as_unsupported(self):
            # cpp's visitor explicitly rejects the `ColumnTypeExprEnum`
            # alternative (`identifier '(' enumValue (',' enumValue)* ')'`
            # where `enumValue: STRING_LITERAL '=' numberLiteral`) with
            # `NotImplementedError: Unsupported rule: ColumnTypeExprEnum`.
            # Rust's raw-text Param fallback used to happily emit the
            # type-name string and silently route Enum casts through to
            # downstream code that may not handle them.
            for src in (
                "cast(x as Enum('a' = 1))",
                "cast(x as Enum8('a' = 1, 'b' = 2))",
                "cast(x as Enum16('a' = 1))",
                "cast(x as Enum8('a' = 1, 'b' = 2,))",  # trailing comma
            ):
                with self.assertRaises(ExposedHogQLError, msg=src) as cpp_cm:
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src) as rust_cm:
                    parse_expr(src, backend="rust-json")
                self.assertIn("ColumnTypeExprEnum", str(cpp_cm.exception), msg=src)
                self.assertIn("ColumnTypeExprEnum", str(rust_cm.exception), msg=src)

        @no_memory_leak_check
        def test_raw_type_param_text_rejects_null_inf_nan_keywords(self):
            # cpp's `columnTypeExpr` Param alt routes identifier-shaped
            # tokens through the `identifier` rule, which omits NULL /
            # INF / NAN. A bare `Int NULL` inside `Tuple(Int NULL)` errors
            # at the outer paren because the inner type can't extend
            # through NULL. Rust's raw-text fallback in
            # `consume_raw_type_param_text` used to concatenate `IntNULL`
            # verbatim, silently accepting and emitting a malformed
            # type-name string.
            for src in (
                "cast(x as Tuple(Int NULL))",
                "cast(x as Array(Int NULL))",
                "cast(x as Map(String NULL, Int))",
                "cast(x as Nested(a Int NULL, b String))",
                "cast(x as FixedString(16 NULL))",
                "cast(x as FixedString(16 INF))",
                "cast(x as FixedString(16 NAN))",
                "cast(x as Decimal(10 NULL, 2))",
                "cast(x as LowCardinality(String NULL))",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="rust-json")
            # Guards: legitimate parametric type casts still parse.
            for src in (
                "cast(x as Tuple(Int, String))",
                "cast(x as Array(Int))",
                "cast(x as Map(String, Int))",
                "cast(x as Nested(a Int, b String))",
                "cast(x as FixedString(16))",
                "cast(x as Decimal(10, 2))",
            ):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_stmt_expression_pratt_recovers_at_statement_level(self):
            # `x *= 2` lexes as `x`, `*`, `=`, `2` — there's no `*=` token
            # in the grammar. cpp's ALL(*) splits the input into TWO
            # statements: `x` (ExprStatement(Field(x))) plus `* = 2`
            # (ExprStatement(Compare(Field(*), "==", 2)) — `*` as a
            # top-level asterisk-primary, `= 2` as the comparison rhs).
            # Rust used to greedy-parse `x *` as a multiplication then
            # hard-error on the failed RHS parse of `=` (not a primary
            # form). Setting the stmt-rhs Pratt-recovery flag at the
            # leading-expression slot of parse_expr_or_assignment_stmt
            # lets rust mirror cpp's split.
            cases = (
                "x *= 2",
                "x * = 2",  # equivalent — same lexing
                "let x := 1; x *= 2;",
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guard: `* = 2` standalone is a valid Compare; `* 2` is two
            # bare ExprStatements; `x * y` is a single multiplication.
            for src in ("* = 2", "* 2", "x * y", "x = 2"):
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_let_decl_shortens_rhs_when_trailing_colon_equals(self):
            # cpp's varDecl grammar (`LET ident (':=' expression)?`) has
            # no place for a trailing `:=` after the expression. When one
            # follows, cpp's ANTLR ALL(*) shortens the expression to the
            # leading PRIMARY form (single token / paren-unwrapped primary)
            # so the trailing `:=` and its rhs become a separate statement.
            # Rust used to greedy-parse the full expression and choke on
            # the dangling `:=`.
            cases = (
                "let x := 1 * 2 := 3",
                "let x := y * (z) := 3",
                "let x := (1) * (2) := 3",
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guard: the ident-chain `let x := y * z := 1` is absorbed
            # via the NamedArgument path inside parse_ident_lead and keeps
            # the full rhs.
            for src in (
                "let x := y",
                "let x := 1 + 2",
                "let x := y * z",
                "let x := y * z := 1",
                "let x := y * z := 1;",
            ):
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_bare_assignment_lead_chains_through_second_colon_equals(self):
            # `IDENT := <rhs> := <outer_rhs>` — cpp's grammar resolves the
            # *second* `:=` as the statement-level varAssignment, with the
            # leading `IDENT := <rhs>` becoming a NamedArgument as the
            # lvalue. The Rust bare-assignment-lead shortcut returned a
            # VariableAssignment immediately after the first `:=` and
            # stranded the trailing tokens.
            cases = (
                "a := 1 := 2",
                "a := 1 * 2 := 3",
                "a := 1 + 2 := 3",
                "a := {} := 2",
                "a := 'str' := 2",
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guards: the existing single- and ident-chain forms still
            # produce the same AST as cpp.
            for src in (
                "a := 1",
                "a := b",
                "a := b := c",
                'a := "str" := 2',
                "a := b := c := d",
                "if (c) a := b",
                "if (c) a := b ; else d",
            ):
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_pivot_column_lhs_extends_past_in_via_infix_operators(self):
            # cpp's `pivotColumn: columnExprTupleOrSingle IN (...)` greedily
            # extends the columnExpr LHS through ANY infix operator after a
            # preceding `IN ( … )` group. The structural IN is the LAST IN
            # whose `)` isn't followed by an extender. Rust's
            # `find_pivot_in_separator` only treated a postfix `(` as
            # extending — bare infix operators (`+`, `*`, `AND`, another
            # `IN`, `LIKE`, etc.) erroneously committed the FIRST IN as
            # structural, splitting one pivotColumn into two.
            same_ast = (
                # `IN` after `IN ( … )` is a Compare infix that extends LHS.
                "SELECT * FROM t PIVOT(1 FOR a IN (b) IN (d))",
                # Arithmetic infix extends.
                "SELECT * FROM t PIVOT(1 FOR a IN (b) + c IN (d))",
                "SELECT * FROM t PIVOT(1 FOR a IN (b) * c IN (d))",
                # Boolean keyword infix extends.
                "SELECT * FROM t PIVOT(1 FOR a IN (b) AND c IN (d))",
                # LIKE keyword infix extends.
                "SELECT * FROM t PIVOT(1 FOR a IN (b) LIKE c IN (d))",
                # Postfix call still extends (pre-existing behaviour).
                "SELECT * FROM t PIVOT(1 FOR a IN (b) (c) IN (d))",
                # NOT is a prefix operator, not infix — it starts a new
                # pivotColumn whose LHS is the bare keyword-as-Field `NOT`.
                "SELECT * FROM t PIVOT(1 FOR a IN (b) NOT IN (d))",
                # Bare identifier always starts a new pivotColumn.
                "SELECT * FROM t PIVOT(1 FOR a IN (b) c IN (d))",
                "SELECT * FROM t PIVOT(1 FOR a IN (b) c IN (d) e IN (f))",
                # Single column still works.
                "SELECT * FROM t PIVOT(1 FOR a IN (b))",
            )
            for src in same_ast:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_parse_order_expr_silently_drops_trailing_tokens(self):
            # cpp's `parse_order_expr_json` entry point parses just one
            # OrderExpr and silently drops anything after it — including
            # whole INTERPOLATE clauses (which actually live one level up
            # at orderByClause). Rust used to `expect_eof` and reject
            # `a ASC extra` with "trailing tokens after expression".
            # Both backends should accept and produce the same AST.
            from posthog.hogql.parser import parse_order_expr

            for src in (
                "a ASC extra",
                "a DESC NULLS FIRST extra trailing junk",
                "a WITH FILL INTERPOLATE (b)",
                "a WITH FILL FROM 1 TO 10 INTERPOLATE (b)",
            ):
                oracle = parse_order_expr(src, backend="cpp-json")
                got = parse_order_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_pivot_group_by_with_empty_list_rejected(self):
            # cpp's `(GROUP BY columnExprList)?` requires a non-empty list
            # when GROUP BY is present — `PIVOT(... GROUP BY)` errors at the
            # trailing `)`. Rust's `parse_expr_list_until_paren` returned an
            # empty Vec on the immediate `)`, silently accepting the PIVOT
            # with `group_by: []`.
            for src in (
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY)",
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY ) AS p",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="rust-json")
            # Guard: the non-empty and trailing-comma forms still parse.
            for src in (
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY a)",
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY a, c)",
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY a,)",
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1))",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_return_expr_prefix_shortening_admits_keyword_head(self):
            # `return <expr> := <rhs>` triggers ANTLR's adaptive prediction:
            # cpp falls back to the shortest expr prefix that leaves the
            # `:=` parseable as a varAssignment statement. The Rust shortener
            # only accepted `*` and `IDENT(` shapes; a leading Keyword like
            # `return return * (...) := …` produced a bare-return + extra
            # ReturnStatement(Field('*')) split instead of cpp's single
            # Field(['return']) shortening.
            cases = (
                "return return * ( 'e' ) := { }",
                "return return * ( 'e' ) := ( 'e' )",
            )
            for src in cases:
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guards: the existing shortening shapes still work.
            for src in (
                "return * columns('a') := 1",
                "return columns('a') := 1",
                "return a := 1",
                "return a.b := 1",
                "return",
                "return x",
                "return 1 + 2",
            ):
                oracle = parse_program(src, backend="cpp-json")
                got = parse_program(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_hogqlx_drops_whitespace_only_children_containing_newline(self):
            # cpp's `VISIT(HogqlxTagElementNested)` filters out child text
            # runs that are entirely whitespace AND contain a newline (or
            # carriage return). Any pretty-printed multi-line HOGQLX literal
            # lands here. Rust used to keep every non-empty text run, so
            # `<a>\n</a>` round-tripped a `Constant("\n")` child that cpp
            # would have dropped. Pure-space / pure-tab runs (no newline) are
            # kept by both; mixed whitespace-with-content runs are too.
            for src in (
                "<a>\n</a>",
                "<a>\r\n</a>",
                "<a>{x}\n</a>",
                "<a>\n  <b/>\n</a>",
            ):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guard: single-space / single-tab without newline is preserved
            # by both; mixed content with whitespace is preserved too.
            for src in (
                "<a> </a>",
                "<a>\t</a>",
                "<a>hello world</a>",
                "<a>\n hello \n</a>",
                "<a></a>",
                "<a/>",
            ):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_interval_combined_string_validates_count_and_unit(self):
            # cpp's `visitColumnExprIntervalString` only accepts a count
            # made of ASCII digits and matches the unit against a literal-
            # lowercase set. Rust used to do `count_str.parse::<i64>()
            # .unwrap_or(0)`, silently substituting `Constant(0)` for any
            # unparseable count ("twenty", "-1", "1.5", overflowing
            # integers), and used `interval_call_name`'s case-insensitive
            # lowercasing so `INTERVAL '1 SECOND'` accepted.
            # Each input must error with the same message in both parsers.
            cases = (
                ("INTERVAL 'twenty days'", "Unsupported interval count: twenty"),
                ("INTERVAL '-1 day'", "Unsupported interval count: -1"),
                ("INTERVAL '1.5 days'", "Unsupported interval count: 1.5"),
                ("INTERVAL '99999999999999999999 day'", "Unknown error: stoi: out of range"),
                ("INTERVAL '1 SECOND'", "Unsupported interval unit: SECOND"),
            )
            for src, expected_msg in cases:
                with self.assertRaises(ExposedHogQLError, msg=src) as cpp_cm:
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src) as rust_cm:
                    parse_expr(src, backend="rust-json")
                self.assertIn(expected_msg, str(cpp_cm.exception), msg=src)
                self.assertIn(expected_msg, str(rust_cm.exception), msg=src)
            # Guard: valid combined-string and expr+unit forms still parse.
            for src in ("INTERVAL '1 day'", "INTERVAL '5 days'", "INTERVAL 1 day", "INTERVAL 1 DAY"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_in_cohort_falls_back_to_identifier_when_rhs_missing(self):
            # cpp's `(NOT)? IN COHORT? columnExpr` only takes the COHORT
            # alternative when a columnExpr follows. With an empty rhs (EOF
            # / comma / clause-keyword next), `cohort` is the IN rhs
            # identifier instead — `a IN cohort` parses as
            # `Compare(a, "in", Field([cohort]))`. The Rust parser greedily
            # ate COHORT and then choked on the missing rhs expression.
            for src in ("a IN COHORT", "a NOT IN COHORT", "a IN cohort"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            for src in (
                "SELECT a IN COHORT, b FROM t",
                "SELECT * FROM t WHERE x IN cohort",
                "SELECT * FROM t WHERE x IN cohort GROUP BY y",
                "SELECT * FROM t WHERE x IN cohort ORDER BY y",
                "SELECT a IN cohort LIMIT 1",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guard: when an expression-starter follows, COHORT remains the
            # marker and the rhs is the expression after it.
            for src in ("a IN COHORT 1", "a IN COHORT t.id", "a NOT IN COHORT 1", "a IN cohort + 1"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_tuple_access_rejects_leading_zero_index(self):
            # cpp's lexer routes `0123` through `OCTAL_PREFIX_LITERAL`, not
            # `DECIMAL_LITERAL`, so the postfix `.<DECIMAL_LITERAL>` tuple
            # access alt grammar-rejects it. Rust's single `Number` token
            # used to silently re-parse the leading-zero text as decimal
            # and emit `TupleAccess(a, 123)` for `a.0123`.
            for src in (
                "a.0123",
                "a.01",
                "a.000123",
                "a?.0123",
                "a?.01",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="rust-json")
            # Guards: single-zero, multi-digit-non-leading-zero, and the
            # repeated float-style chain still parse.
            for src in ("a.0", "a.1", "a.999", "a.1.5", "a.0.5", "a?.0", "a?.1"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_with_cte_admits_primary_form_keywords_as_name(self):
            # cpp's `withExpr: identifier AS LPAREN selectSetStmt RPAREN`
            # admits any keyword in the grammar's `keyword` rule as the CTE
            # name. The Rust probe at parse_with_expr gated on
            # `kw_acts_as_ident_in_primary`, which excludes the primary-form
            # heads (CASE / CAST / SELECT / NOT / etc.) — those names then
            # fell through to the expression-form CTE fallback and choked
            # on `select AS (...)` parsing as a sub-select head. Using
            # `kw_valid_as_identifier` instead matches the grammar exactly.
            for kw in ("select", "case", "cast", "not"):
                src = f"WITH {kw} AS (SELECT 1) SELECT * FROM {kw}"
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guard: NULL / INF / NAN / INTERSECT stay rejected by both
            # parsers (omitted from cpp's `keyword` rule).
            for kw in ("null", "inf", "nan", "intersect"):
                src = f"WITH {kw} AS (SELECT 1) SELECT * FROM {kw}"
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="rust-json")

        @no_memory_leak_check
        def test_join_on_with_comma_separated_exprs_rejected(self):
            # cpp's grammar greedily takes the comma-separated columnExprList
            # after ON, then the visitor raises NotImplementedError because
            # only single-expression ON is supported. The Rust parser used to
            # parse ON's first expr only, then let the outer JOIN-chain
            # treat the trailing comma as a CROSS-JOIN separator — silently
            # accepting and emitting a divergent JoinExpr shape.
            for src in (
                "SELECT * FROM a JOIN b ON x, y",
                "SELECT * FROM a JOIN b ON x = y, z",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="rust-json")
            # Guards: the legitimate single-expression ON / USING / CROSS
            # JOIN / comma-cross-join shapes must still parse.
            for src in (
                "SELECT * FROM a JOIN b ON x",
                "SELECT * FROM a JOIN b ON x = y",
                "SELECT * FROM a JOIN b USING (x, y)",
                "SELECT * FROM a CROSS JOIN b",
                "SELECT * FROM a, b",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_cast_type_compound_loop_stops_at_non_identifier_keyword(self):
            # cpp's `columnTypeExpr` compound alt is `identifier identifier+`,
            # routed through the `identifier` rule that omits NULL / INF /
            # NAN. So `cast(x as Int NULL)` doesn't form a 2-token type — cpp
            # parses `Int` and then chokes on the trailing `NULL` at the
            # outer `)`. The Rust compound loop used to admit any Keyword,
            # silently eating the trailing `NULL` and emitting `int null` as
            # the type name.
            # `Array(Int NULL)` deliberately omitted: it routes through the
            # parametric-type Param fallback (cpp's `ColumnTypeExprParam`'s
            # raw-text `getText()` render), and bare-keyword recovery there
            # is its own separate problem.
            for src in (
                "cast(x as Int NULL)",
                "cast(x as Int NOT NULL)",
                "cast(x as Int32 NULL)",
                "cast(x as UInt64 NOT NULL)",
                "try_cast(x as Int NULL)",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="rust-json")
            # Guards: the valid compound and nested forms must still parse.
            for src in (
                "cast(x as Int)",
                "cast(x as Decimal(10, 2))",
                "cast(x as Array(Int))",
                "cast(x as Time With Time Zone)",
                "cast(x as Foo Bar Baz)",
                "cast(x as Foo Not Bar)",
            ):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_call_arg_select_releases_when_followed_by_keyword_infix(self):
            # `f((SELECT 1) IN [1, 2])` is a call whose first arg is the
            # comparison `(SELECT 1) IN [1, 2]`, not the SELECT alone. The
            # Rust call-arg parser tried the select-set-stmt arm first and
            # then checked `infix_bp` / `postfix_bp` for a continuing operator;
            # those don't cover the keyword-led infixes (IN, LIKE, ILIKE, IS,
            # BETWEEN, and their NOT-prefixed variants), so the select arm
            # kept the SELECT instead of letting the columnExpr arm take it.
            cases = (
                "f((SELECT 1) IN [1, 2])",
                "f((SELECT 1) NOT IN [1, 2])",
                "f((SELECT 1) LIKE 'x')",
                "f((SELECT 1) NOT LIKE 'x')",
                "f((SELECT 1) ILIKE 'x')",
                "f((SELECT 1) NOT ILIKE 'x')",
                "f((SELECT 1) IS NULL)",
                "f((SELECT 1) IS NOT NULL)",
                "f((SELECT 1) BETWEEN 1 AND 2)",
                "f((SELECT 1) NOT BETWEEN 1 AND 2)",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # Guard: the bare-SELECT call-argument shape still works.
            for src in ("f((SELECT 1))", "f(SELECT 1)"):
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_named_argument_admits_identifier_shaped_keywords(self):
            # cpp's `ColumnExprNamedArg: identifier COLONEQUALS columnExpr`
            # admits the full `identifier` rule. `true` / `false` lex to plain
            # IDENTIFIERs in cpp (the lexer has no TRUE / FALSE tokens), and
            # soft keywords like `select` / `return` pass through `keyword`.
            # The Rust call-arg fast-path gated on Ident / QuotedIdent only,
            # so `f(true := 1)` fell through and choked on the trailing `:=`.
            cases = (
                "f(true := 1)",
                "f(false := 1)",
                "f(select := 1)",
                "f(return := 1)",
                # quoted-ident path stays the same
                'f("x" := 1)',
                "f(x := 1)",
            )
            for src in cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            # NULL / INF / NAN aren't in cpp's `identifier` rule and must
            # stay rejected by both backends.
            for src in ("f(null := 1)", "f(inf := 1)", "f(nan := 1)"):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="rust-json")

        @no_memory_leak_check
        def test_null_inf_nan_rejected_in_hog_identifier_slots(self):
            # cpp's `varDecl`, `funcStmt`, `catchBlock`, `forInStmt`, and the
            # lambda heads (`columnLambdaExpr` arrow + `ColumnExprColonLambda`)
            # all use the grammar's `identifier` rule, which OMITS NULL / INF /
            # NAN (and the Hog-statement keywords) from its keyword alternative.
            # cpp rejects these positions; Rust used to match `Keyword(_)`
            # indiscriminately and accept them, producing a divergent AST.
            program_cases = (
                "let null := 1",
                "let inf := 1",
                "let nan := 1",
                "for (let null in xs) {}",
                "for (let a, null in xs) {}",
                "fn null() {}",
                "fn f(null) {}",
                "fn f(inf) {}",
                "fn f(nan) {}",
                "fun null() {}",
                "fun f(null) {}",
                "try {} catch (null) {}",
                "try {} catch (e: null) {}",
                "try {} catch (null: T) {}",
                "try {} catch (inf) {}",
                "(null) -> 1",
                "(a, null) -> 1",
                "null -> 1",
                "lambda null: 1",
                "lambda a, null: 1",
            )
            for src in program_cases:
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_program(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_program(src, backend="rust-json")
            # And ensure the still-valid identifier-shaped slots keep parsing.
            valid_cases = (
                ("let true := 1", "program"),
                ("let select := 1", "program"),
                ("for (let k, v in xs) {}", "program"),
                ("fn f(x, y) {}", "program"),
                ("try {} catch (e) {}", "program"),
                ("try {} catch (e: T) {}", "program"),
                ("(x, y) -> x + y", "expr"),
                ("x -> x", "expr"),
                ("lambda x: x", "expr"),
            )
            for src, kind in valid_cases:
                parse_fn = parse_program if kind == "program" else parse_expr
                oracle = parse_fn(src, backend="cpp-json")
                got = parse_fn(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_true_false_admitted_as_identifier_in_chain_and_table_positions(self):
            # cpp's lexer has no TRUE/FALSE tokens; those source spellings are plain
            # IDENTIFIERs that the visitor lifts into Bool Constants only in the
            # bare-Field branch. In positions that route through `keywordForAlias`
            # or identifier-text rules (postfix `.`, table identifiers, CTE column
            # lists), `true`/`false` round-trip as ordinary identifiers. The Rust
            # `kw_valid_as_identifier` predicate used to exclude them.
            expr_cases = ("x.true", "x.false", "x.true.false")
            for src in expr_cases:
                oracle = parse_expr(src, backend="cpp-json")
                got = parse_expr(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")
            select_cases = (
                "SELECT * FROM x.true",
                "SELECT * FROM x.false",
                "WITH x(true, false) AS (SELECT 1, 2) SELECT * FROM x",
            )
            for src in select_cases:
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_join_constraint_rejected_on_lead_table_and_cross_join(self):
            # cpp's grammar puts `joinConstraintClause` only on `JoinExprOp`
            # and `JoinExprPositional`, NOT on the lead `JoinExprTable` (a
            # bare FROM with optional FINAL/SAMPLE) or `JoinExprCrossOp`.
            # Rust's stacked-constraint peel loop used to attach to any
            # constraint-less JoinExpr in the chain, silently accepting
            # `FROM t ON 1` and `CROSS JOIN b ON 1`.
            for src in (
                "SELECT * FROM t USING (a)",
                "SELECT * FROM t USING (a, b)",
                "SELECT * FROM t ON 1",
                "SELECT * FROM t AS x FINAL USING (a)",
                "SELECT * FROM (SELECT 1) USING (a)",
                "SELECT * FROM numbers(10) USING (a)",
                "SELECT * FROM t SAMPLE 0.5 ON 1",
                "SELECT * FROM t FINAL ON 1",
                "SELECT 1 FROM a CROSS JOIN b ON 1",
                "SELECT 1 FROM a CROSS JOIN b USING (x)",
                # Parens-wrapped JoinExpr: constraints can't penetrate into the
                # inner scope's slots, nor attach to the lead.
                "SELECT * FROM (a JOIN b) ON 1",
                "SELECT * FROM (a JOIN b) USING (x)",
                "SELECT * FROM (a JOIN b) JOIN c ON 1 ON 2",
                # Stacked overflow: more ONs than fillable JOINs.
                "SELECT * FROM a JOIN b ON 1 ON 2",
                "SELECT * FROM a JOIN b JOIN c JOIN d ON 1 ON 2 ON 3 ON 4",
                # Mixed CROSS in a chain — the constraint can't fall through.
                "SELECT * FROM a JOIN b ON 1 CROSS JOIN c ON 2",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="rust-json")
            # Guards: regular JOIN with constraint, stacked ON / ON chain,
            # bare CROSS JOIN, and the SELECT-statement-level `USING SAMPLE`
            # form (which the peel loop must not intercept) all still parse.
            for src in (
                "SELECT * FROM a JOIN b ON 1",
                "SELECT * FROM a JOIN b USING (x)",
                "SELECT * FROM a LEFT JOIN b ON 1",
                "SELECT * FROM a CROSS JOIN b",
                "SELECT * FROM a JOIN b JOIN c ON 1 ON 2",
                "SELECT * FROM a JOIN b JOIN c JOIN d ON 1 ON 2 ON 3",
                "SELECT * FROM t USING SAMPLE 0.5",
                "SELECT * FROM t USING SAMPLE 0.5 OFFSET 0.1",
                # Outer JOIN around a parens-wrapped inner JoinExpr still attaches
                # one constraint at the outer level.
                "SELECT * FROM (a JOIN b) JOIN c ON 1",
                "SELECT * FROM a JOIN (b JOIN c ON 1) ON 2",
                # `sample` as an identifier inside USING (a, …) still works — the
                # USING-SAMPLE guard requires `peek_next == Kw::Sample`, but with
                # a `(` follow-token the constraint parser takes over.
                "SELECT * FROM a JOIN b USING (sample)",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

        @no_memory_leak_check
        def test_columns_exclude_replace_reject_reserved_keywords(self):
            # cpp's `columnsExcludeItem` and `columnsReplaceItem` use the
            # strict `identifier` rule, which excludes NULL / INF / NAN /
            # EXCEPT / INTERSECT and the Hog-statement keywords. Rust's
            # accumulator admitted any `TokenKind::Keyword(_)`, silently
            # accepting `EXCLUDE (null)` and `REPLACE (a AS inf)`.
            for src in (
                "SELECT * EXCLUDE (null) FROM t",
                "SELECT * EXCLUDE (inf) FROM t",
                "SELECT * EXCLUDE (nan) FROM t",
                "SELECT COLUMNS(* EXCLUDE (null)) FROM t",
                "SELECT COLUMNS(* REPLACE (a AS null)) FROM t",
                "SELECT COLUMNS(* REPLACE (a AS inf)) FROM t",
                "SELECT COLUMNS(* REPLACE (a AS nan)) FROM t",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="rust-json")
            # Guard: identifier-shaped EXCLUDE / nested EXCLUDE / REPLACE
            # with admissible alias still work.
            for src in (
                "SELECT * EXCLUDE (a) FROM t",
                "SELECT * EXCLUDE (a.b) FROM t",
                "SELECT COLUMNS(* REPLACE (a AS b)) FROM t",
            ):
                oracle = parse_select(src, backend="cpp-json")
                got = parse_select(src, backend=backend)
                self.assertEqual(clear_locations(got), clear_locations(oracle), msg=f"{backend}: {src!r}")

    return TestParser
