# Parity-regression tests touch `parse_expr` / `parse_select` results as concrete subclasses
# (`ast.Constant.value`, `SelectQuery.select`, …) without `assert isinstance(...)` narrowing on
# every assertion. Each test runs against all 3 backends; a runtime AttributeError surfaces as
# a test failure anyway. Relax the narrowing checks here only so the rest of the codebase
# keeps its strictness.
# mypy: disable-error-code="arg-type, union-attr, attr-defined, assignment, operator"

import re
import math
import hashlib
from typing import Any, Optional, cast

import pytest
from posthog.test.base import BaseTest, MemoryLeakTestMixin, no_memory_leak_check
from unittest.mock import patch

from parameterized import parameterized
from syrupy.extensions.amber import AmberSnapshotExtension

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
from posthog.hogql.errors import BaseHogQLError, ExposedHogQLError, SyntaxError
from posthog.hogql.parser import parse_expr, parse_order_expr, parse_program, parse_select, parse_string_template
from posthog.hogql.test.utils import pretty_dataclasses
from posthog.hogql.visitor import clear_locations


class _SharedParserSnapshotExtension(AmberSnapshotExtension):
    """One shared `.ambr` across all backend subclasses, keyed by test-method name only.

    Every backend (cpp-json / rust-json / rust-py) must construct the identical
    AST — including source positions — so there is exactly one expected snapshot per
    assertion, recorded once and asserted by all three. Default syrupy would key by class
    (`TestParserCppJson` vs `TestParserRustJson`) and write a `.ambr` per test file.
    """

    @classmethod
    def _get_file_basename(cls, *, test_location: Any, index: Any) -> str:
        return "parser_ast"

    @classmethod
    def get_snapshot_name(cls, *, test_location: Any, index: Any = 0) -> str:
        # Strip `parameterized.expand`'s `_<idx>` / `_<idx>_<name>` suffix so
        # `test_foo_0_case_a` keys the same snapshot as the un-parametrized
        # `test_foo`. The `_assert_ast` snapshot key is the SOURCE STRING via
        # `_snapshot_key(src)` — so a parameterized variant carrying the same
        # `src` should reuse the same snapshot regardless of method-name
        # decoration.
        base_method = re.sub(r"_\d+(?:_[A-Za-z0-9_]+)?$", "", test_location.methodname)
        if isinstance(index, str):
            index_suffix = f"[{index}]"
        elif index:
            index_suffix = f".{index}"
        else:
            index_suffix = ""
        return f"{base_method}{index_suffix}"


def _snapshot_key(src: str) -> str:
    """Stable, readable, ambr-safe snapshot key for a source string.

    Keyed purely on `src`, so it is independent of call order: the leak mixin re-runs each
    test 102x, and a source-derived (rather than auto-incrementing) key means every rerun
    re-compares the one stable entry instead of accumulating 102 copies. The short hash keeps
    distinct sources that sanitise to the same prefix from colliding.
    """
    collapsed = re.sub(r"\s+", " ", src.strip())
    safe = re.sub(r"[^0-9A-Za-z]+", "_", collapsed).strip("_")[:60]
    digest = hashlib.sha1(src.encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{digest}" if safe else digest


def parser_test_factory(backend: HogQLParserBackend):
    base_classes = (MemoryLeakTestMixin, BaseTest)

    class TestParser(*base_classes):  # type: ignore
        MEMORY_INCREASE_PER_PARSE_LIMIT_B = 10_000
        MEMORY_INCREASE_INCREMENTAL_FACTOR_LIMIT = 0.1
        MEMORY_PRIMING_RUNS_N = 2
        MEMORY_LEAK_CHECK_RUNS_N = 100

        maxDiff = None

        # syrupy snapshot, injected per test by the `unittest_snapshot` fixture below.
        snapshot: Any
        pytestmark = pytest.mark.usefixtures("unittest_snapshot")

        def _assert_ast(
            self, src: str, rule: str = "select", placeholders: Optional[dict[str, ast.Expr]] = None
        ) -> None:
            # Parse `src` on this backend and check it against the shared cross-backend snapshot.
            # cpp-json / rust-json / rust-py assert the FULL positioned AST (one recorded `.ambr`
            # entry per source — positions verified, cpp regressions caught, no live self-compare).
            parse_fn = {
                "expr": parse_expr,
                "select": parse_select,
                "program": parse_program,
                "order": parse_order_expr,
                "template": parse_string_template,
            }[rule]
            kwargs: dict[str, Any] = {"backend": backend}
            if placeholders is not None:
                kwargs["placeholders"] = placeholders
            # Parse on every rerun so the leak mixin still exercises the parser 102x and a real
            # per-parse leak is caught. Only COMPARE on the first run: syrupy / pretty_dataclasses
            # allocate per call, so comparing on every rerun would trip the leak check with
            # test-machinery growth that isn't a parser leak.
            parsed = parse_fn(src, **kwargs)
            if getattr(self, "_memory_leak_run_index", 0) != 0:
                return
            if not hasattr(self, "_shared_ast_snapshot"):
                self._shared_ast_snapshot = self.snapshot.use_extension(_SharedParserSnapshotExtension)
            assert pretty_dataclasses(parsed) == self._shared_ast_snapshot(name=_snapshot_key(src))

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
                # or "0xfe" is misparsed as a float (a double) instead of an int64.
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
            # A file saved with a leading UTF-8 byte-order mark still parses, AND the BOM is zero-width to cpp's
            # ANTLR lexer: every char offset is reckoned from the char AFTER the BOM. `_assert_ast` pins the exact
            # span (via the cross-backend snapshot) so a parser that counts the BOM as 1 char (rust's natural
            # `byte_to_char_index` behaviour, before the leading-BOM adjustment) fails here.
            self._assert_ast("﻿let x := 1", "program")
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
            # MySQL null-safe equality is sugar for IS NOT DISTINCT FROM
            self.assertEqual(
                self._expr("1 <=> 2"),
                ast.IsDistinctFrom(
                    left=ast.Constant(value=1),
                    right=ast.Constant(value=2),
                    negated=True,
                ),
            )

        def test_mysql_hash_comments(self):
            self.assertEqual(
                self._select("select 1 # mysql comment"),
                ast.SelectQuery(select=[ast.Constant(value=1)]),
            )
            self.assertEqual(
                self._select("select 1 # comment\n, 2"),
                ast.SelectQuery(select=[ast.Constant(value=1), ast.Constant(value=2)]),
            )
            # `#<digit>` stays a positional reference, not a comment
            self.assertEqual(
                self._select("select #1"),
                ast.SelectQuery(select=[ast.PositionalRef(index=1)]),
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

        def test_table_function_arg_rejects_bare_select_subquery(self):
            # A table-function arg is a `columnExpr` (cpp's `tableArgList`), so a
            # bare `SELECT …` is not valid — cpp rejects `FROM a(SELECT 1)`; only
            # `(SELECT …)` paren-wrapped is. (A general call admits a bare subquery
            # via `ColumnExprCallSelect`; a table-function arg does not.)
            for src in (
                "SELECT * FROM a(SELECT 1)",
                "SELECT * FROM events(SELECT 1)",
                "SELECT * FROM numbers(SELECT 1)",
                "SELECT * FROM a(b, SELECT 1)",
            ):
                with self.assertRaises((ExposedHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises((ExposedHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Guards: a paren-wrapped subquery, plain exprs, and named args are
            # all valid table-function args.
            for src in (
                "SELECT * FROM a((SELECT 1))",
                "SELECT * FROM a(1, 2)",
                "SELECT * FROM a(b)",
                "SELECT * FROM a(x := 1)",
            ):
                self._assert_ast(src, "select")

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
            # Set-level LIMIT/OFFSET on a SelectSetQuery initial query must land on the set query, not be dropped.
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

        @parameterized.expand(
            [
                ("using_sample_before_group_by", "select 1 from events using sample 0.1"),
                ("bare_sample_statement_level", "select 1 from events where 1 sample 0.1 group by 1"),
                ("using_sample_after_qualify", "select 1 from events qualify 1 using sample 0.1"),
                ("sample_after_unpivot", "select 1 from (a positional join b) unpivot (m for n in (o)) sample 0.5"),
                ("table_and_statement_sample", "select 1 from events sample 0.1 using sample 0.2"),
            ]
        )
        def test_statement_level_sample_rejected(self, _name: str, query: str):
            # `selectStmt`-level `(USING? sampleClause)?` is DuckDB's `USING SAMPLE`, which HogQL has no AST home for; every backend rejects rather than silently dropping it.
            with self.assertRaises((ExposedHogQLError, SyntaxError)):
                self._select(query)

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

        @parameterized.expand(
            [
                # A non-first CTE whose column-form expression begins with a paren group
                # followed by an operator tail. The CTE-list disambiguation must look past
                # the paren group to the top-level `AS <ident>` alias; an early version of
                # the rust parser stopped at the matching `)` and mis-parsed the remainder
                # as the enclosing SELECT's paren.
                ("operator_tail_after_paren_group", "WITH 5 AS a, 2 AS b, (a - b) * 10 AS c SELECT c", ["a", "b", "c"]),
                ("single_paren_then_operator", "WITH 1 AS a, (a) + 1 AS c SELECT c", ["a", "c"]),
                ("both_ctes_paren_led", "WITH (a - b) AS c, (c) * 2 AS d SELECT d", ["c", "d"]),
                ("scalar_subquery_in_expression", "WITH 1 AS a, (SELECT 2) + 1 AS c SELECT c", ["a", "c"]),
                (
                    "paren_then_property_access",
                    "WITH x AS (SELECT 1 AS n), (x.n) * 2 AS y SELECT y FROM x",
                    ["x", "y"],
                ),
                # Disambiguation that must be preserved: an alias directly after the paren
                # group is still a CTE, and a trailing-comma paren main query (no alias)
                # must terminate the CTE list rather than be swallowed as a CTE.
                ("immediate_alias_after_paren", "WITH 1 AS a, (a) AS c SELECT c", ["a", "c"]),
                ("immediate_alias_after_subquery", "WITH 1 AS a, (SELECT 2) AS c SELECT c", ["a", "c"]),
                ("trailing_comma_paren_main_query", "WITH 1 AS a, (SELECT 2)", ["a"]),
            ]
        )
        def test_paren_led_cte_disambiguation(self, _name: str, query: str, expected_ctes: list[str]):
            node = cast(ast.SelectQuery, self._select(query))
            assert isinstance(node.ctes, dict)
            self.assertEqual(sorted(node.ctes.keys()), sorted(expected_ctes))

        def test_grammar_quirk_invalid_join_type_rejected_on_all_backends(self):
            # `LEFT OUTER SEMI JOIN` passes the rust grammar's per-keyword checks (no rule forbids the combination) but isn't in `VALID_JOIN_TYPES`, so `JoinExpr.__post_init__` raises `ValueError` on every backend. rust-py writes `join_type` post-construction (via `chain_join`), so `PyEmitter::set_field` re-fires `__post_init__` and restores the original exception — surfacing the same `ValueError` the json backends raise from `cls(**kwargs)`.
            q = "SELECT 1 FROM a LEFT OUTER SEMI JOIN b ON a.x = b.x"
            with self.assertRaises(ValueError) as cm:
                self._select(q)
            self.assertIn("Invalid join type", str(cm.exception))

        def test_dataclass_post_init_failure_surfaces_original_exception(self):
            # A dataclass `__post_init__` raising mid-build must surface the ORIGINAL exception on every backend. The json backends raise it straight from `deserialize_ast`; rust-py constructs dataclasses during the parse, so `PyEmitter` restores the exception across its panic/`catch_unwind` boundary instead of wrapping it in an envelope (or leaking a `PanicException`).
            def always_reject(_self: ast.JoinExpr) -> None:
                raise ValueError("synthetic post_init failure for test")

            with patch.object(ast.JoinExpr, "__post_init__", always_reject):
                with self.assertRaises(ValueError) as caught:
                    parse_select("SELECT 1 FROM a JOIN b ON a.x = b.x", backend=backend)
            self.assertIn("synthetic post_init failure", str(caught.exception))

        def test_deeply_nested_input_does_not_stack_overflow(self):
            # Deeply-nested input must surface a clean `SyntaxError`, not a host stack overflow (an uncatchable SIGSEGV) in the recursive-descent loop. One shared counter caps all three recursion dimensions — expression nesting, subquery / set nesting, and Hog statement / block nesting — at `MAX_RECURSION_DEPTH = 1000`, mirroring ClickHouse's `max_parser_depth`. cpp has its own stack characteristics so the assertion is rust-specific. Which guard fires (and so the exact message) depends on how the input routes through the descent, hence the loose substring check.
            if backend not in ("rust-json", "rust-py"):
                self.skipTest("rust-specific recursion cap")
            parse_fns = {"expr": parse_expr, "select": parse_select, "program": parse_program}
            cases = (
                ("expr", "(" * 1500 + "1" + ")" * 1500),
                ("select", "(" * 1500 + "select 1" + ")" * 1500),
                ("program", "{" * 1500 + "}" * 1500),
            )
            for rule, src in cases:
                with self.assertRaises(SyntaxError, msg=rule) as cm:
                    parse_fns[rule](src, backend=backend)
                self.assertIn("too deeply nested", str(cm.exception).lower(), msg=rule)

        def test_ctes_inject_into_paren_wrapped_inner_with(self):
            # An outer WITH attached to a paren-wrapped inner that already has its own WITH must surface both CTEs, with the outer's appended after the inner's (matches cpp's `VISIT(SelectStmtWithParens)` ordering).
            node = cast(
                ast.SelectQuery,
                self._select("WITH a AS (SELECT 1) (WITH b AS (SELECT 2) SELECT * FROM b)"),
            )
            assert isinstance(node.ctes, dict)
            self.assertEqual(list(node.ctes.keys()), ["b", "a"])

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

        def test_return_hogqlx_tag_value(self):
            # `return <Tag/>` is a returnStmt whose value is a HogQLX tag, not the `<` less-than operator binding `return` as a Field. The rust parser's return-guard read the following `<` as less-than and rejected the tag while cpp accepts it; bare `<Tag/>` and `let x := <Tag/>` already worked, so only the return-value position needed the fix (`execute_hog` wraps a bare expression as `return <expr>;`, which is how this surfaced).
            prog = cast(ast.Program, self._program("return <Sparkline />"))
            stmt = cast(ast.ReturnStatement, prog.declarations[0])
            self.assertIsInstance(stmt, ast.ReturnStatement)
            self.assertEqual(stmt.expr, ast.HogQLXTag(kind="Sparkline", attributes=[]))
            nested = cast(ast.ReturnStatement, cast(ast.Program, self._program("return <a>x</a>")).declarations[0])
            self.assertEqual(
                nested.expr,
                ast.HogQLXTag(
                    kind="a",
                    attributes=[ast.HogQLXAttribute(name="children", value=[ast.Constant(value="x")])],
                ),
            )
            self.assertIsInstance(self._program("fn f() { return <em /> }"), ast.Program)
            # The `<`-tag exception must not over-fire: `return < 5` is still a less-than expression statement, not a returnStmt.
            lt = cast(ast.Program, self._program("return < 5"))
            self.assertNotIsInstance(lt.declarations[0], ast.ReturnStatement)

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

        def test_statement_keywords_rejected_as_expressions(self):
            # Hog statement keywords (`fn`, `let`, `while`, …) aren't in the `keyword` rule, unlike `if` / `for` / `return`.
            for kw in ("fn", "fun", "let", "while", "throw", "try", "catch", "finally"):
                with self.assertRaises(ExposedHogQLError, msg=f"{backend}: {kw!r} should reject"):
                    parse_expr(kw, backend=backend)

        def test_exponent_float_without_fractional_digits(self):
            # FLOATING_LITERAL's fractional digits are optional: `1.e5` is one token, not `1` then ArrayAccess on `e5`.
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

        def test_clause_keyword_after_comma_in_select_columns(self):
            # `select a, where b` is one column + WHERE clause; `select a, where` (no body) is two columns.
            # `where * columns('x')` could also be multiplication, but cpp prefers the clause.
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

        def test_limit_percent_marker_with_compound_body(self):
            # `%` is overloaded (modulo + LIMIT PERCENT); compound LIMIT bodies must bind it as the PERCENT marker.
            cases = (
                "SELECT 1 LIMIT 1+1 % WITH TIES",
                "SELECT a, b LIMIT c AND d % WITH TIES",
                "SELECT 1 LIMIT 1+1 % 2 WITH TIES",
                "SELECT 1 LIMIT a%b % WITH TIES",
                "SELECT 1 LIMIT 5 % 2 + 3",
                "SELECT 1 LIMIT 1+1 % OFFSET 3",
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_assignment_lhs_is_any_expression(self):
            # `exprStmt: expression (COLONEQUALS expression)?` — `:=` LHS has no place-expression restriction.
            cases = (
                "1 := 1",
                "[] := 1",
                "{} := 1",
                "'s' := 1",
                "return 1 := 1",
                "for (let m in 488614) 1 := 1",
            )
            for src in cases:
                self._assert_ast(src, "program")

        def test_call_as_assignment_target(self):
            # `f() := 1` is `Call(f) := 1`; a statement's leading expr folds its postfix `(…)` even with `:=` after.
            cases = (
                "f() := 1",
                "f(x) := 1",
                "f()(g) := h",
                "if(x) := y",
                "(a) := (b) (c) := (d)",  # the postfix-stop guard's real RHS scenario must still hold
            )
            for src in cases:
                self._assert_ast(src, "program")

        def test_assignment_statement_consumes_trailing_semicolon(self):
            # `exprStmt: expression (COLONEQUALS expression)? SEMICOLON?` — `:=`-form consumes its trailing `;`.
            # (`varDecl`'s `LET …` form has no `SEMICOLON?` and must not consume it.)
            cases = (
                "if (c) a := b ; else d",
                "if (c) (a) := b ; else d",
                "if (c) a := b ;; else d",
            )
            for src in cases:
                self._assert_ast(src, "program")

        def test_trailing_limit_offset_compound_body(self):
            # `LIMIT`/`OFFSET` after `LIMIT BY` takes a full `columnExpr` body — lower-precedence tails must bind.
            cases = (
                "select x limit a by c limit d ?? e",
                "select x limit a by c offset d ?? e",
                "select x limit a by c limit 1 + 1",
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_limit_by_then_limit_offset_position_stops_before_outer_offset(self):
            # `selectStmt: ... limitByClause? (limitAndOffsetClause | offsetOnlyClause)?`
            # `limitAndOffsetClause` lists compact (no OFFSET) before verbose (with OFFSET),
            # so ANTLR ALL(*) picks compact for the trailing `LIMIT n` after limit-by — the
            # `OFFSET m` belongs to the outer `selectSetStmt`'s `limitAndOffsetClauseOptional`,
            # and the inner SelectQuery's source span stops at the LIMIT, not the OFFSET.
            # Pinned so a regression that greedily eats OFFSET inside selectStmt — extending
            # the SelectQuery end past the trailing OFFSET — fails here.
            self._assert_ast("select 1 from events LIMIT 1 BY event LIMIT 2 OFFSET 3", "select")

        def test_zero_arg_lambda_as_clause_body(self):
            # After `,`, a clause-keyword + `()->` is a lambda clause body; bare `()` makes the keyword a column.
            cases = (
                "select 1, limit () -> 2",
                "select 1, where () -> 2",
                "select 1, offset () -> 3",
                "select 1, limit ()",  # bare () — keyword is a column
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_set_level_offset_compound_body(self):
            # `offsetOnlyClause: OFFSET columnExpr` at selectSetStmt level takes a full columnExpr (lower-precedence tails bind).
            cases = (
                "select 1 offset a or b",
                "select 1 offset a ignore nulls",
                "(select 1) offset a ?? b",
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_pivot_tuple_or_single_parenthesised_operand(self):
            # Per `columnExprTupleOrSingle`, a parenthesised PIVOT/UNPIVOT operand is always a `Tuple`, even for one element.
            cases = (
                "select 1 from a unpivot ((x) for (c) in (d))",
                "select 1 from a pivot (s for (c) in (1))",
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_pivot_binds_to_last_joined_table(self):
            # `joinExpr PIVOT` binds to the immediately-preceding `joinExpr`; after a constraint or explicit parens it wraps the whole chain.
            cases = (
                "select 1 from a join b pivot (x for y in (z))",
                "select 1 from a, b pivot (x for y in (z))",
                "select 1 from a join b on x pivot (s for t in (u))",
                "select 1 from (a join b) pivot (x for y in (z))",
            )
            for src in cases:
                self._assert_ast(src, "select")

        @parameterized.expand(
            [
                # `tableExpr: LPAREN valuesClause RPAREN` — the ValuesQuery node spans the
                # inner `VALUES (...)` (cpp's valuesClause ctx), not the stripped outer
                # parens. Pinned with positions so a regression that drops the span (or
                # wraps the outer parens) fails here on rust / rust-py.
                ("no_alias", "SELECT * FROM (VALUES (1, 'a'))"),
                ("alias_with_columns", "SELECT * FROM (VALUES (1, 'a')) AS v(id, name)"),
                (
                    "multi_row_tuples",
                    "SELECT * FROM (VALUES (1, 'george', 'created'), (2, 'jack', 'deleted'))",
                ),
            ]
        )
        def test_values_clause_in_from_carries_positions(self, _name: str, src: str) -> None:
            self._assert_ast(src, "select")

        @no_memory_leak_check  # re-clears positions per run (allocates); correctness pin, runs once
        def test_internal_parse_emits_no_positions(self):
            # `parse_expr(..., start=None)` is cpp's `is_internal` mode: a synthetic
            # fragment (e.g. an injected database `ExpressionField`) has no meaningful
            # source span, so cpp gates off every `addPositionInfo` and every node is
            # position-less. All backends must match — a backend that emits spans here
            # diverges from cpp on the many queries that join through person overrides.
            src = "if(not(empty(override.distinct_id)), override.person_id, event_person_id)"
            internal = parse_expr(src, start=None, backend=backend)
            positioned = parse_expr(src, start=0, backend=backend)
            self.assertEqual(internal, clear_locations(positioned))
            self.assertIsNone(internal.start)
            self.assertIsNone(internal.end)

        @parameterized.expand(
            [
                # `parse_full_template_string` returns the result of the body splitter — a multi-chunk
                # `concat(...)` or a single chunk. cpp positions by chunk count: the multi-chunk wrapper
                # spans the whole `F'…'` input (rule ctx), but a single-chunk shortcut keeps the inner
                # element's own span (literal text or substitution expr). Both shapes pinned so a
                # regression that wraps unconditionally (clobbering the single-chunk span) — or that
                # drops the multi-chunk wrap — fails here.
                # multi-chunk → outer span (0..len(src))
                ("multi_arraymap_bang", "Hello, {arrayMap(a -> a, [1, 2, 3])}!"),
                ("multi_lib_version", "v={event.properties.$lib_version}"),
                ("multi_typescript_arraymap", "Hello, TypeScript {arrayMap(a -> a, [1, 2, 3])}!"),
                # single literal → wrap_literal_chunk span (body_offset..body_end)
                ("single_literal_hello", "hello"),
                # single substitution → inner expr span (only the placeholder body)
                ("single_substitution_field", "{x}"),
                ("single_substitution_bool", "{true}"),
            ]
        )
        def test_template_string_top_level_carries_outer_span(self, _name: str, src: str) -> None:
            self._assert_ast(src, "template")

        def test_columns_macro_asterisk_form_as_list_element(self):
            # `COLUMNS(…)` tries `columnExprList` before `* EXCLUDE` / `id.* …`, so an asterisk-form + postfix call is `ColumnsList(ExprCall(asterisk-form))`.
            cases = (
                "columns(q.*())",
                "columns(* exclude(a) ())",
                # guard: plain forms keep their shape
                "columns(*)",
                "columns(a, b)",
                "columns(q.*)",
                "columns(* exclude(a))",
                "columns('re')",
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_columns_replace_item_name_is_the_as_keyword(self):
            # `columnsReplace: columnExpr AS identifier` — the replacement name can itself be the keyword `as`.
            cases = (
                "(* replace(a as as))",
                "columns(* replace(a as as))",
                "(* replace(a as b as as))",
                "columns(* replace(x as y, z as as))",
                "(* replace(a as b))",  # guard: ordinary name
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_clause_keyword_then_postfix_op_is_a_column(self):
            # Clause body can't start with a postfix op, so `qualify?.q` / `prewhere::q` keep the keyword as a column.
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

        def test_from_after_comma_needs_a_table_reference(self):
            # FROM's body is a `joinExpr`, not a `columnExpr` — `from` after a comma stays a Field unless a table-ref starter follows.
            for src in ("select q, from", "select q, from + 1", "select q, from()"):
                node = parse_select(src, backend=backend)
                self.assertEqual(len(node.select), 2, msg=f"{backend}: {src!r}")
                self.assertIsNone(node.select_from, msg=f"{backend}: {src!r}")
            # guard: a real table reference still opens the FROM clause
            node = parse_select("select q, from t", backend=backend)
            self.assertEqual(len(node.select), 1, msg=f"{backend}: from t")
            self.assertIsNotNone(node.select_from, msg=f"{backend}: from t")

        def test_clause_keyword_asterisk_then_postfix_is_a_clause(self):
            # `<clause-kw> * <postfix-op>` is the clause with `*` spread + postfix; `*` mult RHS can't begin with a postfix op.
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

        def test_pivot_tuple_or_single_operand_with_postfix(self):
            # PIVOT operand is `Tuple` only when `)` is followed by `FOR`/`IN`; `(n)()` takes the columnExpr branch (paren-expr + postfix call).
            cases = (
                "select 1 from a unpivot (m for (n)() in (p))",
                "select 1 from a pivot (m for (n)() in (p))",
                "select 1 from a unpivot (m for (n) in (p))",  # guard: bare paren stays a Tuple
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_window_frame_between_falls_back_to_field(self):
            # After ROWS/RANGE, `between` is ambiguous: `frameBetween` alt OR `frameStart` whose columnExpr is the `between` Field.
            cases = (
                "select 1 from a window w as (range between preceding)",
                "select 1 from a window w as (range between 1 preceding and 2 following)",  # guard: real BETWEEN frame
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_pivot_operand_containing_in(self):
            # PIVOT operand is full `columnExpr`, so `for n in p in (r)` → operand `n in p` + structural `IN (r)`.
            cases = (
                "select 1 from a unpivot (m for n in p in (r))",
                "select 1 from a pivot (m for n in p in (r))",
                "select 1 from a unpivot (m in n for p in (r))",
                "select 1 from a pivot (m for n in (r))",  # guard: simple form
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_decoration_after_pivot(self):
            # `tableExpr PIVOT (…)` is itself a `tableExpr` — it can chain into alias, FINAL/SAMPLE, further PIVOT, or JOIN.
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
                self._assert_ast(src, "select")

        def test_clause_keyword_as_last_group_by_key(self):
            # The last GROUP BY key can be a clause-keyword Field (e.g. `window`); the next clause then opens normally.
            for kw in ("window", "having", "qualify"):
                node = parse_select(
                    f"SELECT a FROM events GROUP BY tool, {kw} HAVING call_count >= 5",
                    backend=backend,
                )
                self.assertIsInstance(node, ast.SelectQuery, msg=f"{backend}: {kw}")
                self.assertEqual(len(node.group_by or []), 2, msg=f"{backend}: {kw}")
                self.assertIsNotNone(node.having, msg=f"{backend}: {kw}")

        def test_integer_literal_above_i64_max(self):
            # Above-i64 ints are kept lossless via the `value_type: "number"` string envelope (orjson rejects >64-bit number tokens).
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

        def test_string_escape_nul_bel_vtab(self):
            # cpp drops `\0` (NUL ignored), decodes `\a`→0x07, `\v`→0x0B; `\0` also affects quoted identifiers.
            cases = (
                r"'a\0b'",
                r"'\a'",
                r"'\v'",
                r"`a\0b`",
                r'"a\0b"',
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_reserved_keyword_alias_rejected(self):
            # `assertValidAlias` fires at all four alias sites (AS-infix, alias-before, implicit, table); quoted forms opt out.
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

        def test_settings_and_top_clause_error_class(self):
            # SETTINGS/TOP parse but the visitor rejects them — `NotImplementedError` is `InternalHogQLError` and is rewritten to `ExposedHogQLError` at the parser boundary.
            for src in ("SELECT 1 SETTINGS x = 1", "SELECT TOP 5 x FROM t"):
                with self.assertRaises(ExposedHogQLError) as cpp_cm:
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError) as backend_cm:
                    parse_select(src, backend=backend)
                self.assertIs(type(backend_cm.exception), type(cpp_cm.exception), msg=f"{backend}: {src!r}")
                self.assertNotIsInstance(backend_cm.exception, SyntaxError, msg=f"{backend}: {src!r}")

        def test_window_frame_non_int_bound_keeps_constant(self):
            # Unwrap a frame-bound Constant to a bare number only when integer; floats / strings keep the Constant.
            cases = (
                "SELECT count() OVER (ROWS 1.5 PRECEDING) FROM t",
                "SELECT count() OVER (ROWS '5' PRECEDING) FROM t",
                "SELECT count() OVER (ROWS 2 PRECEDING) FROM t",  # guard: int still bare
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_boolean_keyword_as_call_name(self):
            # `true`/`false` are identifiers in the grammar (Bool Constants only as a bare columnIdentifier); as a call name they're `Call(name=...)`.
            # `null` differs — `NULL` is a real lexer keyword, so `null(1)` stays an `ExprCall` on Null Constant.
            for src in ("true(1)", "false(1)", "null(1)"):
                self._assert_ast(src, "expr")
            # guard: bare true/false/null are still Constants
            for src, val in (("true", True), ("false", False), ("null", None)):
                node = parse_expr(src, backend=backend)
                self.assertIsInstance(node, ast.Constant, msg=src)
                self.assertEqual(node.value, val, msg=src)

        def test_hex_integer_literal_baseline(self):
            # Pins plain `0x…` parsing against hex-float-lexer regressions; `e`/`E` are hex digits here, not exponent markers.
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

        def test_hex_float_literal_c99(self):
            # Hex-float `FLOATING_LITERAL` is strict C99 — `p`/`P` is the only exponent marker; `e`/`E` always lexes as a hex digit.
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

        def test_hex_e_is_hex_digit_not_exponent_marker(self):
            # `0x1e+4` is `0x1e` (=30) + `4`, not a hex-float — only `p`/`P` marks the exponent (strict C99, matches ClickHouse).
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

        def test_hex_float_in_expression_context(self):
            # Pins that the lexer recognises a whole hex-float as one token usable inside arithmetic.
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

        def test_hex_float_no_integer_part_rejected(self):
            # `0x.8p3` lacks HEX_DIGIT+ before the dot — invalid per both FLOATING_LITERAL and HEXADECIMAL_LITERAL.
            with self.assertRaises(ExposedHogQLError, msg=f"{backend}: '0x.8p3'"):
                parse_expr("0x.8p3", backend=backend)

        def test_cast_type_arg_with_parenthesized_expr(self):
            # `CAST(x AS name(args))` — the `ColumnTypeExprParam` arglist admits arbitrary columnExprs including ones with their own `(…)`.
            cases = (
                "cast(x as a((b)))",
                "cast(x as a(case when (c) then d end))",
                "cast(x as a(if((c), d, e)))",
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_subquery_arg_call_then_second_call(self):
            # `f(select 1)()` — `(select 1)` is `ColumnExprCallSelect`, the trailing `()` is a separate `ColumnExprCall` postfix nesting on top.
            cases = (
                "f(select 1)()",
                "a(select 1)(2)",
                "f(select 1)(x)(y)",
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_between_not_lambda_lower_bound(self):
            # `BETWEEN <low>`'s AND-reservation must propagate through a `NOT`-wrapped lambda low bound so the lambda doesn't over-consume `…and c`.
            cases = (
                "a between not lambda x: b and c",
                "a between not x -> y and z",
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_chained_between_inner_end_position(self):
            # Left-recursive `between`: `a between L1 and H1 between L2 and H2` parses as `BetweenExpr(BetweenExpr(a, L1, H1), L2, H2)`.
            # The inner BetweenExpr's `.end` must stop at H1 (offset of `2` here), not extend through H2.
            src = "select a between 1 and 2 between 3 and 4"
            node = parse_select(src, backend=backend)
            assert isinstance(node, ast.SelectQuery)
            outer = node.select[0]
            assert isinstance(outer, ast.BetweenExpr), f"{backend}: outer is {type(outer).__name__}"
            inner = outer.expr
            assert isinstance(inner, ast.BetweenExpr), f"{backend}: inner is {type(inner).__name__}"
            # H1 is the constant `2`, which ends at offset 24 in the source.
            self.assertEqual(inner.end, 24, msg=f"{backend}: inner.end={inner.end}, expected 24")
            self.assertEqual(outer.end, 40, msg=f"{backend}: outer.end={outer.end}, expected 40")

        def test_parenthesized_between_high_end_position_with_hoist(self):
            # A BETWEEN whose high operand is parenthesized spans through the
            # trailing `)`, but the high AST node's `end` is paren-stripped. In
            # the hoist case (an alias / ternary / etc. parsed past the parens),
            # the BetweenExpr span must be recovered from the source — else rust's
            # BetweenExpr.end dropped the closing paren and diverged from cpp.
            for src in (
                "0 between 0 and (0) as x",
                "0 not between 0 and (0) as x",
                "0 between 0 and ((0)) as x",
                "1 between 2 and (3) ? 4 : 5",
                "1 between 2 and (3 + 4) as x",
            ):
                self._assert_ast(src, "expr")
            # Guards: simple (no hoist) and a non-parenthesized high are unaffected.
            for src in ("0 between 0 and (0)", "0 between 0 and 5 as x"):
                self._assert_ast(src, "expr")

        def test_bare_asterisk_clause_body_after_comma(self):
            # `select a, where *` opens the WHERE clause with a bare `*` body; later LIMIT / GROUP BY / etc. is a normal subsequent clause.
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
                self._assert_ast(src, "select")

        def test_placeholder_statement_then_postfix_call_or_property(self):
            # `{expr}` at statement start is a placeholder; trailing `(…)` or `.x` is a postfix on it (not a `block` statement).
            cases = (
                "{1}()",
                "{1}.x",
                "{a}()",
                "{ {1}() }",
            )
            for src in cases:
                self._assert_ast(src, "program")

        def test_placeholder_as_alias_inside_call_args(self):
            # `f({placeholder} AS alias, …)` — the placeholder is a columnExpr admitting a trailing `AS alias`, just like any other expression.
            # Caught by the retention query builder emitting `has({start_event_timestamps} as _start_event_timestamps, {min_timestamp})`.
            cases = (
                "has({x} as a)",
                "has({x} as a, y)",
                "f({x} as a, {y} as b)",
                "if(has({x} as _x, {y}), _x, [])",
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_is_only_consumes_known_tails(self):
            # `IS` is only `IS [NOT] NULL` / `IS [NOT] DISTINCT FROM y` per cpp's grammar; in Hog program mode anything else falls back to per-token ExprStatements (e.g. `this is a string` parses as four bare identifier statements).
            # Caught by `test_metadata.py::test_string_template` parsing `"this is a {event} string"` as `HogLanguage.HOG`.
            cases = (
                "this is a string",
                "this is a {event} string",
                "this is a {NONO()} string",
                "x is null",
                "x is not null",
                "x is distinct from y",
                "x is not distinct from y",
            )
            for src in cases:
                self._assert_ast(src, "program")

        def test_window_frame_bound_low_precedence_value(self):
            # Window frame bound is a full `columnExpr` — admits comparison / AND / OR (BETWEEN still splits on its own AND).
            cases = (
                "SELECT count() OVER (ROWS a = b PRECEDING) FROM t",
                "SELECT count() OVER (ROWS a AND b FOLLOWING) FROM t",
                "SELECT count() OVER (ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM t",  # guard: real BETWEEN
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_join_op_modifier_arity_validation(self):
            # Each `joinOp` alt allows at most one ALL/ANY/ASOF; ANTI/SEMI combine only with ASOF as `ASOF (ANTI|SEMI)`.

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
                self._assert_ast(src, "select")

        def test_group_by_all_falls_back_to_columns_on_postfix(self):
            # `ALL` is also in the `keyword` rule — any postfix after `ALL` makes it a `Field('ALL')` columnExpr, not the all-mode marker.
            for src in (
                "SELECT a FROM t GROUP BY ALL, b",
                "SELECT a FROM t GROUP BY ALL.x",
                "SELECT a FROM t GROUP BY ALL + 1",
                "SELECT a FROM t GROUP BY ALL[1]",
                "SELECT a FROM t GROUP BY ALL()",
            ):
                self._assert_ast(src, "select")
            # Guard: bare `ALL` (clause terminator follows) still hits the all-mode marker.
            self._assert_ast("SELECT a FROM t GROUP BY ALL", "select")

        def test_with_rollup_cube_totals_chain_grammar(self):
            # `groupByClause … (WITH (CUBE|ROLLUP))? (WITH TOTALS)?` — at most one CUBE/ROLLUP, then optional TOTALS, in order.

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
                self._assert_ast(src, "select")

        def test_pivot_in_list_must_be_non_empty(self):
            # `pivotColumn`'s `IN ( columnExprList )` is non-empty.

            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT 1 FROM t PIVOT (sum(x) FOR y IN ())", backend=backend)
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT 1 FROM t PIVOT (sum(x) FOR y IN ())", backend="cpp-json")
            # Guard: populated list still parses.
            src = "SELECT 1 FROM t PIVOT (sum(x) FOR y IN (1, 2))"
            self._assert_ast(src, "select")

        def test_trim_substring_must_be_string_literal(self):
            # `TRIM (LEADING|TRAILING|BOTH string FROM columnExpr)` — `string` is `STRING_LITERAL | templateString` only.

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
                self._assert_ast(src, "expr")

        def test_cte_list_paren_after_non_paren_cte(self):
            # `, (` after a CTE continues the list — paren-subquery or paren-expr as next CTE, not a SELECT-start under trailing-comma tolerance.
            for src in (
                "WITH 1 AS x, (SELECT 1) AS y SELECT x, y",
                "WITH (SELECT 1) AS x, (SELECT 2) AS y SELECT x, y",
                "WITH 1 AS x, (a + b) AS y SELECT y",
                "WITH 1 AS x, (1) AS y SELECT y",
                "WITH 1 AS a, (x -> x + 1) AS f SELECT f(a)",
                "WITH count() AS c, (x -> x + 1) AS f SELECT f(c)",
            ):
                self._assert_ast(src, "select")

        def test_group_by_cube_rollup_continues_list(self):
            # `CUBE(...)` / `ROLLUP(...)` followed by `, <more>` is a regular function call; the specialised mode commits only when no list continuation follows.
            for src in (
                "SELECT * FROM t GROUP BY CUBE(a), ROLLUP(b)",
                "SELECT * FROM t GROUP BY CUBE(a), b",
                "SELECT * FROM t GROUP BY ROLLUP(a), b",
                "SELECT * FROM t GROUP BY a, CUBE(b)",
            ):
                self._assert_ast(src, "select")
            # Bare `GROUP BY CUBE(...)` (no trailing keys) still uses the mode.
            for src in (
                "SELECT * FROM t GROUP BY CUBE(a)",
                "SELECT * FROM t GROUP BY ROLLUP(a)",
            ):
                self._assert_ast(src, "select")

        def test_trailing_comma_after_joined_table_chain(self):
            # A stray trailing comma after a constrained JOIN chain (`FROM a JOIN b ON 1,`) falls off the joinExpr without requiring a next table atom.
            for src in (
                "SELECT * FROM a JOIN b ON 1,",
                "SELECT * FROM a JOIN b USING (x),",
                "SELECT * FROM a JOIN b ON 1 JOIN c ON 1,",
            ):
                self._assert_ast(src, "select")

        def test_unterminated_block_comment_lexes_as_div_asterisk(self):
            # `/* … */` only matches with a closing `*/`; unterminated `/*` falls back to `/ *` tokens that the grammar then evaluates normally.
            for src in ("1 /*", "1 /* "):
                self._assert_ast(src, "expr")

            # Unterminated `/*` + ident lexes as `1 / * ident`; expression parse fails on the extraneous tokens.

            for src in ("1 /* unclosed", "a /* unclosed"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)

            # Guard: closed `/* … */` is still trivia.
            self._assert_ast("1 /* ok */ + 2", "expr")

        def test_interpolate_no_trailing_comma(self):
            # `INTERPOLATE (…)` body is `interpolateExpr (COMMA interpolateExpr)*` — no trailing comma.

            with self.assertRaises((BaseHogQLError, SyntaxError), msg=backend):
                parse_select(
                    "SELECT 1 FROM t ORDER BY x WITH FILL INTERPOLATE (y,)",
                    backend=backend,
                )

        def test_boolean_dot_chain_is_field_not_array_access(self):
            # `true.x` is `Field(['true','x'])` — bools act as identifiers in `columnIdentifier` chain position, not Bool Constant + `.x` postfix.
            cases = ("true.x", "false.x", "TRUE.x", "true.x.y", "false.foo.bar")
            for src in cases:
                self._assert_ast(src, "expr")
            # Guards: bare `true`/`false` stay Bool Constants; `true(1)` is an ident-path Call.
            for src in ("true", "false", "true(1)"):
                self._assert_ast(src, "expr")

        def test_using_empty_parens_rejected(self):
            # `joinConstraintClause` requires a non-empty `columnExprList` in both `USING (…)` and `USING …` forms.

            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT * FROM a JOIN b USING ()", backend=backend)
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT * FROM a JOIN b USING ()", backend="cpp-json")
            # Populated USING still parses.
            src = "SELECT * FROM a JOIN b USING (x)"
            self._assert_ast(src, "select")

        def test_group_by_cube_rollup_empty_is_function_call(self):
            # Empty `CUBE()`/`ROLLUP()` are ordinary Calls in the GROUP BY position, not mode markers.
            for src in ("SELECT 1 GROUP BY CUBE()", "SELECT 1 GROUP BY ROLLUP()"):
                self._assert_ast(src, "select")
            # Populated CUBE / ROLLUP still uses the mode marker.
            src = "SELECT 1 GROUP BY CUBE(a, b)"
            self._assert_ast(src, "select")

        def test_quoted_identifier_backslash_escapes(self):
            # `QUOTED_IDENTIFIER` admits `\"`, `\\`, and `""` escapes inside `"…"`.
            cases = (
                '"\\""',
                '"a\\"b"',
                '"\\\\"',
                '"a"',
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_reserved_keywords_rejected_as_identifiers(self):
            # `identifier` excludes NULL_SQL/INF/NAN_SQL/EXCEPT/INTERSECT and Hog-statement keywords (FN/FUN/LET/WHILE/THROW/TRY/CATCH/FINALLY).

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
            # Guard: interval units / plain identifier-keywords (CASE/DAY/…) still parse.
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

        def test_bare_asterisk_replace_only_inside_parens(self):
            # `ColumnExprAsterisk` only admits trailing EXCLUDE; `REPLACE` after `*` is valid only inside `(*…)` or `COLUMNS(*…)`.

            invalid_select = ("SELECT * REPLACE (b AS a) FROM t",)
            for src in invalid_select:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_expr("* REPLACE (a AS b)", backend=backend)
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_expr("* REPLACE (a AS b)", backend="cpp-json")
            # Guard: paren-wrapped REPLACE and bare-`*` EXCLUDE still parse.
            for src in (
                "(* REPLACE (1 AS event))",
                "(* EXCLUDE (a) REPLACE (b AS c))",
                "* EXCLUDE (a)",
            ):
                self._assert_ast(src, "expr")

        def test_filter_clause_invalid_before_within_group(self):
            # `ColumnExprFunctionWithinGroup` has no FILTER slot.

            for src in (
                "median(x) FILTER (WHERE z) WITHIN GROUP (ORDER BY y)",
                "quantile(x) FILTER (WHERE z > 0) WITHIN GROUP (ORDER BY y)",
            ):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # WITHIN GROUP alone still parses.
            self._assert_ast("median(x) WITHIN GROUP (ORDER BY y)", "expr")

        def test_window_function_args_no_distinct_no_inline_order_by(self):
            # `ColumnExprWinFunction` takes a plain `columnExprList` — no DISTINCT, no in-args ORDER BY.

            for src in (
                "foo(a ORDER BY b) OVER ()",
                "foo(DISTINCT a) OVER ()",
                "foo(DISTINCT a ORDER BY b) OVER ()",
            ):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # Plain forms still parse.
            for src in ("foo(a) OVER ()", "foo(DISTINCT a)", "foo(a ORDER BY b)"):
                self._assert_ast(src, "expr")

        def test_unary_plus_only_on_numeric_literal(self):
            # `numberLiteral`'s `+` is a sign prefix on number/INF/NAN, not a general unary op.

            invalid = ("+a", "+(a)", "+(+a)", "+f(x)")
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # Guards: numeric / INF parse and pin the AST. NaN can't be equality-compared, so just assert it parses.
            for src in ("+1", "+1.5", "+inf"):
                self._assert_ast(src, "expr")
            self.assertIsNotNone(parse_expr("+nan", backend=backend))

        def test_column_cte_requires_identifier_after_as(self):
            # `withExpr: columnExpr AS identifier` — post-AS must be a real identifier, not a number / string / paren group.

            invalid = (
                "WITH a AS 1 SELECT a",
                "WITH 1 + 1 AS 1 SELECT 1",
                "WITH 1 + 1 AS 'foo' SELECT 'foo'",
            )
            for src in invalid:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Identifier names continue to work.
            self._assert_ast("WITH a AS b SELECT b", "select")

        def test_limit_offset_with_ties_must_precede_offset(self):
            # `limitAndOffsetClause` is either `LIMIT n PERCENT? (COMMA n)? (WITH TIES)?` (compact) or `LIMIT n PERCENT? (WITH TIES)? OFFSET n` (verbose);
            # `LIMIT n OFFSET m WITH TIES` matches neither — WITH TIES must precede OFFSET in the verbose form.

            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT a FROM t LIMIT 1 OFFSET 2 WITH TIES", backend=backend)
            with self.assertRaises((BaseHogQLError, SyntaxError)):
                parse_select("SELECT a FROM t LIMIT 1 OFFSET 2 WITH TIES", backend="cpp-json")
            # Both valid forms still parse.
            for src in (
                "SELECT a FROM t LIMIT 1 WITH TIES OFFSET 2",
                "SELECT a FROM t LIMIT 1, 2 WITH TIES",
                "SELECT a FROM t LIMIT 1 WITH TIES",
            ):
                self._assert_ast(src, "select")

        def test_pivot_in_separator_extends_via_postfix_call(self):
            # `pivotColumn`'s LHS extends past any `IN (…) (` (postfix-call on LHS); only the LAST `IN (…)` not followed by `(` is structural.
            cases = (
                "SELECT 1 FROM t PIVOT (s FOR a IN (1) b IN (2))",  # splits at first IN — `b` after close fails LHS-extension
                "SELECT 1 FROM t PIVOT (sum(x) FOR y IN (1) (2) IN (3))",  # one column, structural IN at second depth-0
                "SELECT 1 FROM t PIVOT (sum(x) FOR y IN (1, 2))",
                "SELECT 1 FROM t PIVOT (sum(x) FOR (y, z) IN ((a, b), (c, d)))",
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_return_expr_prefix_shortened_when_assignment_follows(self):
            # `return <expr>? <stmt>` where stmt starts with `:=` — cpp backtracks the expr to the shortest prefix that leaves `:=` parseable as the next stmt.
            cases = (
                "fn f() { return * columns('a') := columns('b') }",  # expr = `*`, then columns(…) := …
                "fn f() { return columns('a') := columns('b') }",  # expr = `columns`, paren-expr takes `:=`
                "fn f() { return * x := y }",
                "fn f() { return *x := y }",
                # Guards: cases that should NOT shorten.
                "fn f() { return X := Y }",  # NamedArgument inside return
                "fn f() { return a.b := c }",  # no valid prefix; bare return
                "fn f() { return * }",  # bare asterisk
                "fn f() { return *columns('a') }",  # no `:=`; full SpreadExpr
            )
            for src in cases:
                self._assert_ast(src, "program")

        def test_interpolate_as_lambda_value(self):
            # `interpolateExpr: columnExpr (AS columnExpr)?` — AS RHS is a full columnExpr, so a lambda body is valid.
            cases = (
                "SELECT 1 ORDER BY x INTERPOLATE (a AS LAMBDA y: y+1)",
                "SELECT 1 ORDER BY x INTERPOLATE (a AS y -> y+1)",
            )
            for src in cases:
                self._assert_ast(src, "select")
            # Guards: AS with a non-lambda RHS still folds as a normal column alias.
            for src in (
                "SELECT a AS my_alias FROM t",
                'SELECT a AS "my alias" FROM t',
                "SELECT 1 ORDER BY x INTERPOLATE (a AS 5)",
            ):
                self._assert_ast(src, "select")

        def test_hogqlx_tag_in_from_paren_decorations(self):
            # `(<Tag/>)` is `LPAREN joinExpr RPAREN`: alias / FINAL / SAMPLE bind to the tag inside the parens (tableExpr) but not outside (JoinExprParens isn't a tableExpr).

            accept = (
                "SELECT 1 FROM (<Tag /> AS y)",
                "SELECT 1 FROM (<Tag /> JOIN b ON x)",
                "SELECT 1 FROM (<Tag /> FINAL)",
            )
            for src in accept:
                self._assert_ast(src, "select")

            reject = (
                "SELECT 1 FROM (<Tag />) AS x",
                "SELECT 1 FROM (<Tag />) x",
                "SELECT 1 FROM (<Tag />) FINAL",
            )
            for src in reject:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)

        def test_hogqlx_tag_text_accepts_arbitrary_non_brace_non_lt(self):
            # `HOGQLX_TEXT_TEXT: ~[<{]+` — any byte except `<` and `{` is valid tag-body text.
            cases = (
                "<a>foo&bar</a>",
                "<a>foo!</a>",
                "<a>foo@bar</a>",
                "<a>1 + 2</a>",
                "<a>!@#%^*()</a>",
                "<outer><inner>foo!bar</inner>baz&qux</outer>",
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_hogqlx_tag_identifier_allows_hyphens(self):
            # `HOGQLX_TAG_OPEN`/`_CLOSE` modes admit `[a-zA-Z_][a-zA-Z0-9_-]*` for tag and attribute names — hyphens are part of the ident.
            cases = (
                "<a-b />",
                "<a-b-c />",
                "<my-tag a-b={1}>x</my-tag>",
                "<tag a-b={1}/>",
                "<tag><my-child/></tag>",
                "<a-b>{1}</a-b>",
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_hogqlx_tight_vs_loose_tags(self):
            # cpp lexes `<ident…` ("tight") through dedicated tag/text lexer modes
            # and `< ident…` ("loose") through the default mode, and the two
            # diverge: tight captures child text (incl. whitespace); loose admits
            # only nested tags / `{expr}` children (stray text rejected, whitespace
            # dropped); loose attribute values may be `f'…'` templates (tight
            # rejects them); a loose opening name may be quoted (`< "x" />`) but a
            # closing name never is (so `< "x" ></ "x" >` rejects).
            accept = (
                "<a></a>",
                "< a ></ a >",
                "<a>x</a>",
                "<a> </a>",
                "< a > </ a >",
                "< a b=f'x' />",
                "<a b={1}/>",
                "< a b={1} />",
                "< a >< b /></ a >",
                '< "x" />',
            )
            for src in accept:
                self._assert_ast(src, "expr")
            reject = (
                "< a >x</ a >",
                "<a b=f'x'/>",
                '< "x" ></ "x" >',
            )
            for src in reject:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)

        def test_cast_type_param_admits_date_literal_as_raw_text(self):
            # A `date ''` / `timestamp ''` literal inside a `ColumnTypeExprParam`
            # is `getText()`'d, never visited, so cpp accepts it as raw param
            # text; the visitor-level "not supported" rejection must not fire.
            for src in (
                "cast(0 as a(date ''))",
                "cast(0 as a(date '', date '', ))",
                "cast(0 as a(a(date '', date '', ), ))",
                "cast(0 as a(timestamp ''))",
            ):
                self._assert_ast(src, "expr")
            # Guards: a genuine ColumnTypeExprEnum and a bare `date ''` cast type
            # still reject on every backend.
            for src in ("cast(0 as a(f''=0))", "cast(0 as a('x'=1))", "cast(0 as date '')"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)

        def test_placeholder_discarded_interpolate_must_be_terminated(self):
            # A `{placeholder}` select's trailing ORDER BY is grammar-parsed but
            # never visited, so its INTERPOLATE is consume-dropped. An
            # unterminated clause — e.g. a `#`-comment swallowing the `)` to
            # end-of-line — must still reject, matching cpp's "mismatched input
            # '<EOF>'", not be silently accepted.
            for src in (
                "{x} order by 1 interpolate ( # 6 )",
                "{x} order by 1 interpolate ( a # 6 )",
                "{x} order by 1 interpolate ( a",
            ):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)
            # Guards: a well-formed interpolate (and a `#6` positional ref) parse.
            for src in ("{x} order by 1 interpolate ( a )", "{x} order by 1 interpolate ( #6 )"):
                self._assert_ast(src, "select")

        def test_join_expr_parens_does_not_take_outer_alias(self):
            # `JoinExprParens` isn't a `tableExpr`, so alias / FINAL / SAMPLE can't bind to a `(joinExpr)` from outside.

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
                self._assert_ast(src, "select")

        def test_string_literal_unknown_backslash_escapes_rejected(self):
            # `ESCAPE_CHAR_COMMON` is closed: `\b \f \r \n \t \0 \a \v \\ \xNN` plus `\'`; anything else is a lexer error.

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
                self._assert_ast(src, "expr")

        def test_sample_clause_leading_dot_float_value(self):
            # Leading-dot floats `.5` lex as `Dot` + `Number`, so SAMPLE's ratio gate must admit `Dot` when followed by a Number.
            cases = (
                "SELECT 1 FROM t SAMPLE .5",
                "SELECT 1 FROM t SAMPLE .04",
                "SELECT 1 FROM t SAMPLE .5 / 2",
                "SELECT 1 FROM t SAMPLE 1 / .04",
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_sample_clause_only_accepts_number_literals(self):
            # `ratioExpr: placeholder | numberLiteral (SLASH numberLiteral)?` — each side is a `numberLiteral` only, not a general columnExpr.

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
                self._assert_ast(src, "select")

        def test_join_op_grammar_alts_validation(self):
            # `joinOp` has three disjoint alts:
            # JoinOpInner, JoinOpLeftRight, JoinOpFull. Each keyword appears
            # at most once per alt, and the three alts don't share INNER /
            # LEFT / RIGHT / FULL. Rust's source-order loop set booleans
            # without de-duplicating or cross-validating, so it accepted
            # `INNER LEFT`, `LEFT OUTER LEFT`, `FULL INNER`, etc.

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
                self._assert_ast(src, "select")

        def test_capital_F_template_string_only_in_full_template_context(self):
            # `f'…'` is reachable from `templateString` (a `columnExpr`); `F'…'` only from the `fullTemplateString` entry rule.

            for src in ("F'hello'", "F''", "F'{1+2}'"):
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_expr(src, backend=backend)
            # Guard: lowercase form remains a valid column expression.
            for src in ("f'hello'", "f'{1+2}'"):
                self._assert_ast(src, "expr")

        def test_full_template_string_empty_body_span(self):
            # The standalone `parse_string_template` entry has no trailing quote,
            # so an empty body spans the whole synthetic `F'` token `[0, len]`,
            # not one byte past it like an inline `f''` would. Position-sensitive.
            self._assert_ast("", "template")
            # Guards: a non-empty literal body and a `{ … }` substitution.
            self._assert_ast("x", "template")
            self._assert_ast("{1}", "template")

        def test_empty_paren_only_clauses_rejected(self):
            # `columnAliases`, `interpolateClause`'s paren body, and `columnsReplaceList` each require ≥ 1 element when parens are present.

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
                self._assert_ast(src, "select")
            for src in (
                "COLUMNS(* REPLACE (a AS b, c AS d))",
                "COLUMNS(* REPLACE (a AS b))",
            ):
                self._assert_ast(src, "expr")

        def test_bare_zero_x_prefix_lexes_as_zero_plus_ident(self):
            # `HEXADECIMAL_LITERAL` requires ≥ 1 hex digit after `0x`; otherwise the lexer falls back to `0` then ident `x`.

            cases = (
                "SELECT 0x AS y",
                "SELECT 0x + 1",
            )
            for src in cases:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=src):
                    parse_select(src, backend=backend)
            # Valid hex literals (≥ 1 hex digit) must keep working.
            for src in ("SELECT 0x1", "SELECT 0xFF", "SELECT 0xaB"):
                self._assert_ast(src, "select")

        def test_cast_type_param_group_mode_classification(self):
            # `IDENT(...)` type expr commits per-group: Param renders via raw text (case-preserved, spaceless), Complex / Nested lowercase + `, `-join.
            # Any depth-0 expr-shaped sibling forces Param mode for the entire group.
            cases = (
                # All items expr-shaped — Param mode end-to-end.
                "cast(x as DateTime64(3, 'UTC'))",
                'cast(x as DateTime64(3, "UTC"))',
                "cast(x as Foo(#1, ABC))",
                # Mixed: `#1` forces Param for the whole group; sibling `Bar(a, b)` renders spaceless + case-preserved.
                "cast(x as Foo(#1, Bar(a, b)))",
                "cast(x as Foo(Bar(a, b), #1))",
                "cast(x as Foo(#1, f(g(a, b), h(c, d))))",
                # Depth-1 `8` inside `FixedString(8)` doesn't escalate outer Foo to Param.
                "cast(x as Foo(FixedString(8)))",
                "cast(x as Foo(g(#1)))",
                # All items type-shaped — Complex mode.
                "cast(x as Foo(a(b, c), d))",
                "cast(x as Tuple(a Int, b Int))",
                # Top-level operator forces Param.
                "cast(x as Foo(a, b*c))",
                # `case when … end` has no depth-0 markers but isn't a type — falls to Param.
                "cast(x as Foo(case when (c) then d end))",
            )
            for src in cases:
                self._assert_ast(src, "expr")

        def test_hogqlx_comments_skipped_between_attributes(self):
            # `HOGQLX_TAG_OPEN`/`_CLOSE` modes skip block + line comments and route unknown bytes to UNEXPECTED_CHARACTER.
            cases = (
                "<a /*c*/ b={1}/>",
                "<a /* c */b={1}/>",
                "<a -- comment\n b={1}/>",
                "<a // comment\n b={1}/>",
                "<a /*c*/ />",
            )
            for src in cases:
                self._assert_ast(src, "expr")
            # Guard: unknown bytes (`#`, `@`) inside a tag now reject via UNEXPECTED_CHARACTER.
            for src in ("<a # comment\n />", "<a @x b={1}/>"):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend=backend)

        def test_float_subnormal_preserved_not_flattened_to_infinity(self):
            # Subnormal floats keep their value (cpp's `strtod`+errno distinguishes underflow from overflow); below the smallest subnormal → 0.0; true overflow → ±Infinity.
            cases_subnormal = (
                ("1e-310", 1e-310),
                ("5e-324", 5e-324),
                ("-1e-310", -1e-310),
            )
            for src, expected in cases_subnormal:
                got = parse_expr(src, backend=backend)
                self.assertEqual(got.value, expected, msg=f"{backend}: {src!r}")
            for src in ("1e-325", "-1e-400"):
                got = parse_expr(src, backend=backend)
                self.assertEqual(got.value, 0.0, msg=f"{backend}: {src!r}")
            for src, expected in (("1e+400", float("inf")), ("-1e+400", float("-inf"))):
                got = parse_expr(src, backend=backend)
                self.assertEqual(got.value, expected, msg=f"{backend}: {src!r}")

        def test_stmt_rhs_pratt_recovers_on_infix_rhs_failure(self):
            # cpp splits `let x := {} * ()` into two stmts when the `*` infix RHS rejects — the stranded operator + operand become the next stmt.
            cases = (
                "let x := {} * ()",
                "{ let x := {} * () }",
                "a := {} * ()",
                "return {} * ()",
                "let x := f() * ()",
            )
            for src in cases:
                self._assert_ast(src, "program")
            # Guard: a valid full expression still parses greedily — recovery only fires when RHS rejects.
            for src in (
                "let x := {} * (1)",
                "let x := 1 + 2",
                "let x := 1",
            ):
                self._assert_ast(src, "program")

        def test_unpivot_emits_include_nulls_false_by_default(self):
            # `JoinExprUnpivot` always emits `include_nulls` — `false` by default, `true` when `INCLUDE NULLS` is present.
            cases = (
                "SELECT * FROM t UNPIVOT (val FOR month IN (a, b))",
                "SELECT * FROM t UNPIVOT INCLUDE NULLS (val FOR month IN (a, b))",
            )
            for src in cases:
                self._assert_ast(src, "select")

        def test_not_with_keyword_infix_treats_not_as_field(self):
            # `NOT <kw-infix> <rhs>` is `Field([not]) <kw-infix> <rhs>` when the infix RHS is valid; otherwise `Not(Field(kw))`.
            cases = (
                "NOT BETWEEN 1 AND 2",
                "NOT LIKE 'a'",
                "NOT IS NULL",
                "NOT ILIKE 'a'",
                "NOT IS NOT NULL",
            )
            for src in cases:
                self._assert_ast(src, "expr")
            # Guards: unary-NOT shapes work when the rhs is a complete columnExpr (no kw-infix gap).
            for src in (
                "NOT x",
                "not like",  # no rhs → unary NOT on Field(like)
                "not in (1,2)",  # IN takes a paren-list, parses as Not(Call(in))
                "NOT IN (1)",
            ):
                self._assert_ast(src, "expr")

        def test_multi_join_with_stacked_on_using_clauses(self):
            # Multi-JOIN with stacked constraints binds right-associatively: in `a JOIN b JOIN c ON1 ON2`, ON1 attaches to `c`, ON2 to `b`.
            cases = (
                "SELECT * FROM a JOIN b JOIN c ON 1 ON 2",
                "SELECT * FROM a JOIN b JOIN c ON a.x=b.x ON b.y=c.y",
                "SELECT * FROM a INNER JOIN b INNER JOIN c ON 1 ON 1",
                "SELECT * FROM a JOIN b JOIN c USING (x) USING (y)",
                "SELECT * FROM a JOIN b JOIN c JOIN d ON 1 ON 2 ON 3",
            )
            for src in cases:
                self._assert_ast(src, "select")
            # Guards: the interleaved / single-constraint shapes still
            # parse the same way.
            for src in (
                "SELECT * FROM a JOIN b ON 1 JOIN c ON 1",
                "SELECT * FROM a JOIN b ON 1",
                "SELECT * FROM a JOIN b USING (x)",
            ):
                self._assert_ast(src, "select")

        def test_enum_cast_rejected_as_unsupported(self):
            # `ColumnTypeExprEnum` (`ident(enumValue,…)` where `enumValue: STRING = number`) is explicitly unsupported by the visitor.
            for src in (
                "cast(x as Enum('a' = 1))",
                "cast(x as Enum8('a' = 1, 'b' = 2))",
                "cast(x as Enum16('a' = 1))",
                "cast(x as Enum8('a' = 1, 'b' = 2,))",  # trailing comma
            ):
                with self.assertRaises(ExposedHogQLError, msg=src) as cpp_cm:
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src) as rust_cm:
                    parse_expr(src, backend=backend)
                self.assertIn("ColumnTypeExprEnum", str(cpp_cm.exception), msg=src)
                self.assertIn("ColumnTypeExprEnum", str(rust_cm.exception), msg=src)

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
                    parse_expr(src, backend=backend)
            # Guards: legitimate parametric type casts still parse.
            for src in (
                "cast(x as Tuple(Int, String))",
                "cast(x as Array(Int))",
                "cast(x as Map(String, Int))",
                "cast(x as Nested(a Int, b String))",
                "cast(x as FixedString(16))",
                "cast(x as Decimal(10, 2))",
            ):
                self._assert_ast(src, "expr")

        def test_stmt_expression_pratt_recovers_at_statement_level(self):
            # `x *= 2` has no `*=` token: splits into two stmts (`x` and `* = 2` → Compare(Field('*'), '==', 2)).
            cases = (
                "x *= 2",
                "x * = 2",  # equivalent lexing
                "let x := 1; x *= 2;",
            )
            for src in cases:
                self._assert_ast(src, "program")
            # Guards: `* = 2` is a Compare; `* 2` is two ExprStatements; `x * y` is a single multiplication.
            for src in ("* = 2", "* 2", "x * y", "x = 2"):
                self._assert_ast(src, "program")

        def test_let_decl_shortens_rhs_when_trailing_colon_equals(self):
            # `LET ident := <expr>` has no slot for a trailing `:=`; cpp shortens the expr to its leading primary so the trailing `:=` opens a new stmt.
            cases = (
                "let x := 1 * 2 := 3",
                "let x := y * (z) := 3",
                "let x := (1) * (2) := 3",
            )
            for src in cases:
                self._assert_ast(src, "program")
            # Guards: ident-chain RHS keeps the full expression via the NamedArgument path.
            for src in (
                "let x := y",
                "let x := 1 + 2",
                "let x := y * z",
                "let x := y * z := 1",
                "let x := y * z := 1;",
            ):
                self._assert_ast(src, "program")

        def test_bare_assignment_lead_chains_through_second_colon_equals(self):
            # `IDENT := <rhs> := <outer>` — the *second* `:=` is the stmt-level varAssignment; the leading `IDENT := <rhs>` becomes a NamedArgument lvalue.
            cases = (
                "a := 1 := 2",
                "a := 1 * 2 := 3",
                "a := 1 + 2 := 3",
                "a := {} := 2",
                "a := 'str' := 2",
            )
            for src in cases:
                self._assert_ast(src, "program")
            # Guards: existing single- and ident-chain forms.
            for src in (
                "a := 1",
                "a := b",
                "a := b := c",
                'a := "str" := 2',
                "a := b := c := d",
                "if (c) a := b",
                "if (c) a := b ; else d",
            ):
                self._assert_ast(src, "program")

        def test_pivot_column_lhs_extends_past_in_via_infix_operators(self):
            # `pivotColumn`'s LHS extends through ANY infix operator after an `IN(…)`; the structural IN is the LAST one not followed by an extender.
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
                self._assert_ast(src, "select")

        def test_parse_order_expr_silently_drops_trailing_tokens(self):
            # `parse_order_expr_json` parses one OrderExpr and silently drops anything trailing (incl. INTERPOLATE, which is one level up).

            for src in (
                "a ASC extra",
                "a DESC NULLS FIRST extra trailing junk",
                "a WITH FILL INTERPOLATE (b)",
                "a WITH FILL FROM 1 TO 10 INTERPOLATE (b)",
            ):
                self._assert_ast(src, "order")

        def test_pivot_group_by_with_empty_list_rejected(self):
            # `GROUP BY` (PIVOT-level included) requires a non-empty `columnExprList`.
            for src in (
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY)",
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY ) AS p",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend=backend)
            # Guard: the non-empty and trailing-comma forms still parse.
            for src in (
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY a)",
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY a, c)",
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1) GROUP BY a,)",
                "SELECT * FROM t PIVOT(sum(a) FOR b IN (1))",
            ):
                self._assert_ast(src, "select")

        def test_return_expr_prefix_shortening_admits_keyword_head(self):
            # A leading keyword (`return return *(...) := X`) is a valid shortening head: expr = Field(['return']), `* (...) := X` is the next stmt.
            cases = (
                "return return * ( 'e' ) := { }",
                "return return * ( 'e' ) := ( 'e' )",
            )
            for src in cases:
                self._assert_ast(src, "program")
            # Guards: existing shortening shapes still work.
            for src in (
                "return * columns('a') := 1",
                "return columns('a') := 1",
                "return a := 1",
                "return a.b := 1",
                "return",
                "return x",
                "return 1 + 2",
            ):
                self._assert_ast(src, "program")

        def test_hogqlx_drops_whitespace_only_children_containing_newline(self):
            # `HogqlxTagElementNested` drops child text runs that are all-whitespace AND contain a newline (so pretty-printed HOGQLX has no spurious Constant children).
            for src in (
                "<a>\n</a>",
                "<a>\r\n</a>",
                "<a>{x}\n</a>",
                "<a>\n  <b/>\n</a>",
            ):
                self._assert_ast(src, "expr")
            # Guards: pure-space/tab (no newline) and mixed-content runs are kept.
            for src in (
                "<a> </a>",
                "<a>\t</a>",
                "<a>hello world</a>",
                "<a>\n hello \n</a>",
                "<a></a>",
                "<a/>",
            ):
                self._assert_ast(src, "expr")

        def test_interval_combined_string_validates_count_and_unit(self):
            # `INTERVAL '<count> <unit>'` requires an ASCII-digit count and a literal-lowercase unit; each invalid input must surface the same error string in both parsers.
            cases = (
                ("INTERVAL 'twenty days'", "Unsupported interval count: 'twenty' is not a valid integer"),
                ("INTERVAL '-1 day'", "Unsupported interval count: '-1' is not a valid integer"),
                ("INTERVAL '1.5 days'", "Unsupported interval count: '1.5' is not a valid integer"),
                # A space-but-empty count (`' '`, `' day'`) is reported the same way — the count before the space isn't a valid integer.
                ("INTERVAL ' '", "Unsupported interval count: '' is not a valid integer"),
                ("INTERVAL ' day'", "Unsupported interval count: '' is not a valid integer"),
                # ClickHouse stores intervals as Int64, so both parsers convert the count with `std::stoll` (i64); a value past Int64 max is rejected as too large. Both parsers emit this exact message (no leaked stdlib `stoll` text), so assert it in full.
                (
                    "INTERVAL '9223372036854775808 day'",
                    "Unsupported interval count: '9223372036854775808' is too large",
                ),
                (
                    "INTERVAL '99999999999999999999 day'",
                    "Unsupported interval count: '99999999999999999999' is too large",
                ),
                ("INTERVAL '1 SECOND'", "Unsupported interval unit: SECOND"),
                # cpp accepts only the singular or single-`s` plural unit; a doubled plural is rejected. rust used to strip every trailing `s` and silently accept `dayss` as `day`.
                ("INTERVAL '1 dayss'", "Unsupported interval unit: dayss"),
                ("INTERVAL '1 secondss'", "Unsupported interval unit: secondss"),
                # A string with no internal space can't be `<count> <unit>`: cpp commits to ColumnExprIntervalString and its visitor rejects with this message. rust used to fall through to the expr+unit form and raise a "expected interval unit keyword" SyntaxError instead — same base class, so only the message asserts the divergence.
                ("INTERVAL ''", "Unsupported interval type: must be in the format '<count> <unit>'"),
                ("INTERVAL 'x'", "Unsupported interval type: must be in the format '<count> <unit>'"),
                ("now() - INTERVAL ''", "Unsupported interval type: must be in the format '<count> <unit>'"),
                # A nested string-valued interval (`INTERVAL INTERVAL '<count> <unit>' <unit>`) reaches the same count/unit validation through a different call site; assert the edge cases there too so the two sites can't drift.
                ("INTERVAL INTERVAL ' day' MONTH", "Unsupported interval count: '' is not a valid integer"),
                (
                    "INTERVAL INTERVAL '9223372036854775808 day' MONTH",
                    "Unsupported interval count: '9223372036854775808' is too large",
                ),
                ("INTERVAL INTERVAL '1 dayss' MONTH", "Unsupported interval unit: dayss"),
            )
            for src, expected_msg in cases:
                with self.assertRaises(ExposedHogQLError, msg=src) as cpp_cm:
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src) as rust_cm:
                    parse_expr(src, backend=backend)
                self.assertIn(expected_msg, str(cpp_cm.exception), msg=src)
                self.assertIn(expected_msg, str(rust_cm.exception), msg=src)
            # Guard: valid combined-string and expr+unit forms still parse.
            for src in ("INTERVAL '1 day'", "INTERVAL '5 days'", "INTERVAL 1 day", "INTERVAL 1 DAY"):
                self._assert_ast(src, "expr")
            # Guard: a no-space string that is only the HEAD of a longer
            # unit-terminated value still parses as `ColumnExprInterval` (expr+unit)
            # on both backends — the fall-back to the string-form rejection must not
            # pre-empt these. `interval 'x' day` takes the same path with the unit
            # immediately after the string.
            # Counts past int32 (`2147483648`) up to Int64 max (`9223372036854775807`) must parse — ClickHouse stores intervals as Int64, so `std::stoll` accepts the whole range. This guards the boundary against the out_of_range reject case above.
            for src in (
                "INTERVAL 'a' || 'b' hour",
                "INTERVAL 'x' day",
                "INTERVAL '2147483648 day'",
                "INTERVAL '9223372036854775807 day'",
            ):
                self.assertEqual(parse_expr(src, backend="cpp-json"), parse_expr(src, backend=backend), msg=src)

        def test_in_cohort_falls_back_to_identifier_when_rhs_missing(self):
            # `IN COHORT` only commits when a columnExpr follows; otherwise `cohort` is the IN rhs identifier (`a IN cohort` → Compare(a, "in", Field('cohort'))).
            for src in ("a IN COHORT", "a NOT IN COHORT", "a IN cohort"):
                self._assert_ast(src, "expr")
            for src in (
                "SELECT a IN COHORT, b FROM t",
                "SELECT * FROM t WHERE x IN cohort",
                "SELECT * FROM t WHERE x IN cohort GROUP BY y",
                "SELECT * FROM t WHERE x IN cohort ORDER BY y",
                "SELECT a IN cohort LIMIT 1",
            ):
                self._assert_ast(src, "select")
            # Guard: when an expression-starter follows, COHORT remains the marker.
            for src in ("a IN COHORT 1", "a IN COHORT t.id", "a NOT IN COHORT 1", "a IN cohort + 1"):
                self._assert_ast(src, "expr")

        def test_tuple_access_rejects_leading_zero_index(self):
            # Postfix `.<index>` requires `DECIMAL_LITERAL`; leading-zero numbers lex as `OCTAL_PREFIX_LITERAL` and are rejected.
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
                    parse_expr(src, backend=backend)
            # Guards: single-zero, multi-digit, and float-style chains.
            for src in ("a.0", "a.1", "a.999", "a.1.5", "a.0.5", "a?.0", "a?.1"):
                self._assert_ast(src, "expr")

        def test_with_cte_admits_primary_form_keywords_as_name(self):
            # CTE names can be any keyword in `identifier` — including primary-form heads (CASE / CAST / SELECT / NOT).
            for kw in ("select", "case", "cast", "not"):
                src = f"WITH {kw} AS (SELECT 1) SELECT * FROM {kw}"
                self._assert_ast(src, "select")
            # Guard: NULL / INF / NAN / INTERSECT stay rejected — omitted from `keyword`.
            for kw in ("null", "inf", "nan", "intersect"):
                src = f"WITH {kw} AS (SELECT 1) SELECT * FROM {kw}"
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend=backend)

        def test_join_on_with_comma_separated_exprs_rejected(self):
            # ON takes a comma-separated `columnExprList` per the grammar; the visitor then rejects multi-expr ON as unsupported.
            for src in (
                "SELECT * FROM a JOIN b ON x, y",
                "SELECT * FROM a JOIN b ON x = y, z",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend=backend)
            # Guards: single-expr ON, USING, CROSS JOIN, and comma-cross-join.
            for src in (
                "SELECT * FROM a JOIN b ON x",
                "SELECT * FROM a JOIN b ON x = y",
                "SELECT * FROM a JOIN b USING (x, y)",
                "SELECT * FROM a CROSS JOIN b",
                "SELECT * FROM a, b",
            ):
                self._assert_ast(src, "select")

        def test_cross_join_after_join_on_constraint(self):
            # A comma after `JOIN … ON expr` is a CROSS JOIN (single-expr ON) when
            # the post-comma table carries an alias or `FINAL`: cpp reads
            # `ON expr, t alias` / `…, t FINAL` that way, not as a multi-expr ON.
            for src in (
                "SELECT 0 FROM a JOIN a ON '', a a",
                "SELECT 1 FROM a JOIN b ON 1, c c",
                "SELECT 0 FROM a JOIN a ON x = y, b b",
                "SELECT * FROM a JOIN b ON x, y FINAL",
                "SELECT * FROM a JOIN b ON x, y z, w",
                "SELECT * FROM a JOIN b ON x, (select 1) s",
            ):
                self._assert_ast(src, "select")
            # The comma stays a multi-expression ON (rejected on all backends)
            # when the post-comma element fully consumes as a columnExpr: a bare
            # column / `AS` alias / field chain, or a trailing `SAMPLE` (taken at
            # the statement level). `y team_id` is a reserved alias (rejected on
            # both); `c JOIN d ON y` has no alias/FINAL so it stays multi-expr ON.
            for src in (
                "SELECT * FROM a JOIN b ON x, y AS z",
                "SELECT * FROM a JOIN b ON x, y.z",
                "SELECT * FROM a JOIN b ON x, y SAMPLE 0.1",
                "SELECT * FROM a JOIN b ON x, y, z",
                "SELECT * FROM a JOIN b ON x, y team_id",
                "SELECT * FROM a JOIN b ON x, c JOIN d ON y",
            ):
                with self.assertRaises((ExposedHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises((ExposedHogQLError, SyntaxError), msg=f"{backend}: {src!r}"):
                    parse_select(src, backend=backend)

        def test_cast_type_compound_loop_stops_at_non_identifier_keyword(self):
            # `columnTypeExpr`'s compound alt is `identifier identifier+`; NULL / INF / NAN aren't in `identifier`, so `cast(x as Int NULL)` rejects.
            # `Array(Int NULL)` is intentionally omitted — that routes through ColumnTypeExprParam's raw-text fallback (separate problem).
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
                    parse_expr(src, backend=backend)
            # Guards: valid compound and nested forms.
            for src in (
                "cast(x as Int)",
                "cast(x as Decimal(10, 2))",
                "cast(x as Array(Int))",
                "cast(x as Time With Time Zone)",
                "cast(x as Foo Bar Baz)",
                "cast(x as Foo Not Bar)",
            ):
                self._assert_ast(src, "expr")

        def test_call_arg_select_releases_when_followed_by_keyword_infix(self):
            # `f((SELECT 1) IN [1,2])` — the first call arg is the full Compare; keyword-led infixes (IN/LIKE/IS/BETWEEN + NOT-variants) must release the SELECT-as-arg arm.
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
                self._assert_ast(src, "expr")
            # Guard: bare-SELECT call argument.
            for src in ("f((SELECT 1))", "f(SELECT 1)"):
                self._assert_ast(src, "expr")

        def test_named_argument_admits_identifier_shaped_keywords(self):
            # `ColumnExprNamedArg: identifier COLONEQUALS columnExpr` — `true`/`false` are plain IDENTIFIERs in the lexer; soft keywords pass via `keyword`.
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
                self._assert_ast(src, "expr")
            # Guard: NULL / INF / NAN aren't in `identifier`, so they stay rejected.
            for src in ("f(null := 1)", "f(inf := 1)", "f(nan := 1)"):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_expr(src, backend=backend)

        def test_null_inf_nan_rejected_in_hog_identifier_slots(self):
            # `varDecl`, `funcStmt`, `catchBlock`, `forInStmt`, and lambda heads all route through `identifier`, which omits NULL / INF / NAN / Hog-stmt keywords.
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
                    parse_program(src, backend=backend)
            # Guards: identifier-shaped slots still parse.
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
                self._assert_ast(src, kind)

        def test_true_false_admitted_as_identifier_in_chain_and_table_positions(self):
            # `true`/`false` are plain IDENTIFIERs in the lexer; they lift to Bool Constants only in the bare-Field branch.
            expr_cases = ("x.true", "x.false", "x.true.false")
            for src in expr_cases:
                self._assert_ast(src, "expr")
            select_cases = (
                "SELECT * FROM x.true",
                "SELECT * FROM x.false",
                "WITH x(true, false) AS (SELECT 1, 2) SELECT * FROM x",
            )
            for src in select_cases:
                self._assert_ast(src, "select")

        def test_join_constraint_rejected_on_lead_table_and_cross_join(self):
            # `joinConstraintClause` attaches to `JoinExprOp` / `JoinExprPositional` only — not to the lead `JoinExprTable` or `JoinExprCrossOp`.
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
                # Parens-wrapped JoinExpr: constraints can't penetrate / attach to lead.
                "SELECT * FROM (a JOIN b) ON 1",
                "SELECT * FROM (a JOIN b) USING (x)",
                "SELECT * FROM (a JOIN b) JOIN c ON 1 ON 2",
                # Stacked overflow: more ONs than fillable JOINs.
                "SELECT * FROM a JOIN b ON 1 ON 2",
                "SELECT * FROM a JOIN b JOIN c JOIN d ON 1 ON 2 ON 3 ON 4",
                # Mixed CROSS in chain: constraint can't fall through.
                "SELECT * FROM a JOIN b ON 1 CROSS JOIN c ON 2",
                # Statement-level `USING SAMPLE` (the peel loop must not treat the `USING` as a join constraint): it's DuckDB's statement-level sample, which HogQL doesn't implement, so it's rejected rather than silently dropped.
                "SELECT * FROM t USING SAMPLE 0.5",
                "SELECT * FROM t USING SAMPLE 0.5 OFFSET 0.1",
            ):
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend="cpp-json")
                with self.assertRaises(ExposedHogQLError, msg=src):
                    parse_select(src, backend=backend)
            # Guards: regular JOIN+constraint, stacked ON chains, bare CROSS JOIN.
            for src in (
                "SELECT * FROM a JOIN b ON 1",
                "SELECT * FROM a JOIN b USING (x)",
                "SELECT * FROM a LEFT JOIN b ON 1",
                "SELECT * FROM a CROSS JOIN b",
                "SELECT * FROM a JOIN b JOIN c ON 1 ON 2",
                "SELECT * FROM a JOIN b JOIN c JOIN d ON 1 ON 2 ON 3",
                # Outer JOIN around a parens-wrapped inner JoinExpr still attaches one constraint at the outer level.
                "SELECT * FROM (a JOIN b) JOIN c ON 1",
                "SELECT * FROM a JOIN (b JOIN c ON 1) ON 2",
                # `sample` as an ident inside USING(…) — the `(` follow-token defers to the constraint parser, not the USING-SAMPLE guard.
                "SELECT * FROM a JOIN b USING (sample)",
            ):
                self._assert_ast(src, "select")

        def test_columns_exclude_replace_reject_reserved_keywords(self):
            # `columnsExcludeItem` and `columnsReplaceItem` use the strict `identifier` rule (excludes NULL/INF/NAN/EXCEPT/INTERSECT + Hog-stmt keywords).
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
                    parse_select(src, backend=backend)
            # Guards: identifier-shaped EXCLUDE / REPLACE with admissible alias.
            for src in (
                "SELECT * EXCLUDE (a) FROM t",
                "SELECT * EXCLUDE (a.b) FROM t",
                "SELECT COLUMNS(* REPLACE (a AS b)) FROM t",
            ):
                self._assert_ast(src, "select")

        def test_invalid_interval_in_block_body_rejected(self):
            # Once `interval` is followed by a primary value it commits to the INTERVAL
            # form: a missing / bad unit is a hard error, never a fall-back to
            # `interval`-as-Field. Inside a Hog `{ … }` block body the fall-back would
            # strand the string as a second statement, so `x -> { interval 'ln' }` would
            # parse as `interval; 'ln'` — accepting input the cpp oracle rejects.
            with self.assertRaises(BaseHogQLError):
                parse_expr("x -> { interval 'ln' }", backend=backend)

        def test_date_timestamp_literal_in_block_body_rejected(self):
            # `DATE STRING` / `TIMESTAMP STRING` (the date/timestamp literal forms) are
            # rejected — cpp parses them but its visitor has no literal node for them.
            # rust must commit to the literal form, not treat `date` / `timestamp` as an
            # identifier and strand the string; otherwise inside a Hog `{ … }` block body
            # `{ date 'x' }` parses as the two statements `date; 'x'` and accepts input
            # the cpp oracle rejects.
            for query in ("x -> { date 'ddg' }", "x -> { timestamp 'x' }"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)

        def test_from_table_implicit_alias_rejected(self):
            # `from <implicit-alias>` in table position is the grammar's
            # ColumnExprInvalidFromImplicitAlias footgun — cpp rejects it. rust
            # parsed `select a, from b, from c` as a comma-join whose second table
            # is `from` aliased `c`, accepting input cpp rejects. `from AS c` (explicit
            # alias) and a plain comma-join (`select a, from b, c`) stay valid.
            with self.assertRaises(BaseHogQLError):
                parse_select("select a, from b, from c", backend=backend)
            parse_select("select a, from b, c", backend=backend)
            parse_select("select a, from b as c", backend=backend)

        def test_invalid_cast_type_param_rejected(self):
            # A parametric type's params are `columnExpr`s. rust's raw-text Param
            # path concatenated tokens verbatim without checking the item parsed as
            # an expression, so `cast(1 as d(()))` (empty group), `d(a() b)`
            # (juxtaposition), and friends were accepted where cpp rejects. Each
            # param must now validate as a columnExpr.
            invalid = [
                "cast(1 as d(()))",
                "cast(1 as d(a() b))",
                "cast(1 as d((),1))",
                "cast(1 as Tuple(()))",
            ]
            for query in invalid:
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            # Valid parametric-type params still parse on both backends.
            for query in ("cast(1 as d())", "cast(1 as d(#1))", "cast(1 as d([1]))", "cast(1 as Array(Int))"):
                parse_expr(query, backend="cpp-json")
                parse_expr(query, backend=backend)

        def test_brace_placeholder_only_positions_reject_dict(self):
            # `tableExpr`, `ratioExpr` (SAMPLE) and the `selectStmtWithParens`
            # placeholder arm all admit only a placeholder `{ columnExpr }`, never
            # a Dict. rust shared one brace parser across these slots and the expr
            # position, so it built a Dict for `{}` / `{k: v}` and accepted input
            # cpp rejects. Each placeholder-only slot must reject the Dict while
            # still accepting the `{x}` placeholder.
            dict_in_placeholder_slot = [
                "select 1 from {}",
                "select 1 from {1: 2}",
                "select 1 from t sample {}",
                "select 1 from t sample {1: 2}",
                "{}",
                "{1: 2}",
                "({})",
            ]
            valid_placeholder = [
                "select 1 from {x}",
                "select 1 from t sample {x}",
                "{x}",
                "({x})",
            ]
            for query in dict_in_placeholder_slot:
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)
            for query in valid_placeholder:
                parse_select(query, backend=backend)

        def test_empty_columns_call_and_star_spread_rejected(self):
            # Empty `columns()` matches no `ColumnExprColumns*` production. rust
            # built an empty-list ColumnsExpr and accepted it; it must instead let
            # bare `columns()` fall back to a function call (cpp's behaviour). The
            # `* columns()` spread is then invalid as a single expression — a
            # for-in iterable / if / while condition — where cpp rejects it too.
            invalid_single_expr = [
                "for (let y in * columns()) {}",
                "while (* columns()) {}",
                "if (* columns()) {}",
            ]
            for query in invalid_single_expr:
                with self.assertRaises(BaseHogQLError):
                    parse_program(query, backend=backend)
            # `* columns()` as two statements (`*` then a `columns()` call), bare
            # `columns()` / regex / list, and a non-empty `* columns('re')` spread
            # all still parse on both backends.
            valid = [
                "* columns()",
                "columns()",
                "columns('re')",
                "columns(a, b)",
                "for (let y in * columns('re')) {}",
            ]
            for query in valid:
                parse_program(query, backend=backend)

        def test_window_name_rejects_hog_statement_keywords(self):
            # A window name is an `identifier`, which admits only the keywords in
            # cpp's `keyword` rule; the Hog-statement keywords are excluded, so they
            # are not valid window names. rust accepted any keyword there. Both
            # window-name positions are the same `identifier` rule: the `OVER <name>`
            # target and the `WINDOW <name> AS (...)` clause. Both must reject the
            # excluded keywords while still accepting an ordinary keyword/identifier.
            excluded = ("finally", "try", "catch", "while", "let", "fn", "fun", "throw")
            valid = ("select", "from", "with", "where", "w")
            for name in excluded:
                with self.assertRaises(BaseHogQLError):
                    parse_expr(f"f() over {name}", backend=backend)
                with self.assertRaises(BaseHogQLError):
                    parse_select(f"select 1 from t window {name} as (order by x)", backend=backend)
            for name in valid:
                parse_expr(f"f() over {name}", backend=backend)
                parse_select(f"select 1 from t window {name} as (order by x)", backend=backend)

        def test_materialized_keyword_rejected_as_identifier(self):
            # MATERIALIZED is a lexer keyword used only in `WITH x AS MATERIALIZED
            # (...)`; the grammar's `keyword` rule omits it, so it is not a valid
            # identifier. rust admitted it via `kw_valid_as_identifier` /
            # `kw_acts_as_ident_in_primary`, accepting `x.materialized`,
            # `select materialized`, `exclude(materialized)` etc. where cpp rejects.
            for query in ("x.materialized", "materialized", "columns(* exclude(materialized))"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            for query in ("select 1 as materialized", "select x from t as materialized", "select materialized from t"):
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)
            # The legitimate MATERIALIZED keyword usage (CTE materialization) still parses.
            for query in (
                "with x as materialized (select 1) select 1 from x",
                "with x as not materialized (select 1) select 1 from x",
            ):
                parse_select(query, backend=backend)

        def test_bare_star_replace_rejected_outside_wrapper(self):
            # `* REPLACE(...)` is a columnExpr only inside the paren forms
            # `(* REPLACE(...))` / `(* EXCLUDE(...) REPLACE(...))` or `COLUMNS(* REPLACE(...))`.
            # rust accepted a bare `* replace(...)` whenever a `)` followed (e.g. as a
            # function argument or tuple element), since its guard couldn't tell a wrapper
            # paren from a borrowed function-call one. Both must reject the bare form.
            for query in ("full(* replace(a as b))", "* replace(a as b)", "(a, * replace(b as c))"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            with self.assertRaises(BaseHogQLError):
                parse_select("select * replace(a as b) from t", backend=backend)
            # Wrapped REPLACE forms (including nested) and a bare `* EXCLUDE` still parse.
            valid = [
                "(* replace(a as b))",
                "(* exclude(x) replace(a as b))",
                "columns(* replace(a as b))",
                "((* replace(a as b)))",
                "* exclude(a)",
            ]
            for query in valid:
                parse_expr(query, backend=backend)

        def test_wrapped_columns_replace_span_excludes_outer_parens(self):
            # Only the BARE `(* [exclude] replace(...))` form has its wrapping parens
            # in the ColumnsExpr ctx. When the ColumnsExpr instead comes from a
            # `columns(...)` call or sits inside an EXTRA wrapping paren, cpp treats
            # those parens as a separate `ColumnExprParens` (stripped) — the
            # ColumnsExpr span stays inner. rust used to over-extend the span to the
            # outer parens for every REPLACE-bearing ColumnsExpr; assert full AST
            # parity (positions included) on both the bare and wrapped shapes.
            for query in (
                "(* replace(a as b))",
                "(* exclude(x) replace(a as b))",
                "columns(* replace(a as b))",
                "((* replace(a as b)))",
                "(((* replace(a as b))))",
                "(columns(* replace(a as b)))",
                "((columns(* replace(a as b))))",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_between_hoist_inner_wrapper_spans(self):
            # When 2+ wrappers stack outside a BETWEEN (`1 between 2 and 3 as l :: Int`),
            # the hoist-apply loop built each position-less and only the OUTERMOST got
            # the outer pratt `wrap_pos` — the inner wrappers (here the Alias) stayed
            # position-less. cpp spans each at `[lhs_start, end-of-its-own-token]`.
            # The split now records each hoist's end and the apply loop stamps it.
            for query in (
                "1 between 2 and 3 as l :: Int",
                "1 between 2 and 3 as l :: Int :: Float",
                "1 between 2 and 3 as l [ 1 ]",
                "1 between 2 and 3 as l . 1",
                "1 between 2 and 3 as l ( x )",
                "1 between 2 and 3 as l is null",
                "1 between 2 and 3 as l or w",
                "1 between 2 and 3 as l ? x : y",
                "1 between 2 and 3 as l + 5",
                "1 between 2 and 3 as l is distinct from w",
                "1 between 2 and 3 as l",
                "1 between 2 and 3 :: Int",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_arrow_lambda_block_body_span_with_trailing_postfix(self):
            # An arrow lambda with a Hog BLOCK body (`x -> { … }`) ends at `}`, so a
            # trailing postfix (`. 1`, `[1]`, `:: Int`) cannot fold into the body and
            # binds OUTSIDE the lambda. The Lambda was then an intermediate pratt-loop
            # lhs that the outer wrap never reached, leaving it position-less; cpp
            # spans the Lambda over `args -> { … }`. The builder now stamps the span.
            # (An expression body absorbs the postfix, so it never hit this.)
            for query in (
                "x -> { throw 0 } . 1",
                "x, y -> { throw 0 } . 2",
                "(a, b) -> { let z := 1 return z } . 1",
                "x -> { throw 0 } [ 1 ]",
                "x -> { throw 0 } :: Int",
                "x -> { throw 0 }",
                "x -> 1",
                "f(x -> { throw 0 })",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_statement_leading_brace_block_vs_call(self):
            # A statement-leading `{...}` is a Block, except when a postfix that
            # cannot itself begin a statement follows the matching `}`: a `.` or an
            # EMPTY `()` make the whole thing one called / accessed expression
            # (`{1}.x`, `{1}()`). A non-empty `(expr)` IS a valid next statement, so
            # the brace stays a Block and the `(expr)` is parsed separately
            # (`{1} (a)` -> Block + ExprStatement). rust merged `{block} (expr)` into
            # a single call. Both accept here, so assert full AST parity (positions
            # included, no clear_locations) rather than just accept/reject.
            for query in (
                "{1} (a)",
                "{} ('b')",
                "{x} ('b')",
                "{1}(a, b)",
                "{1} ('b') ('c')",
                "{1}(a).b",
                "{1}()",
                "{}()",
                "{1}.x",
                "{1:2} ('b')",
                "{1}[1]",
                # `.x` property access forces the call parse, but a leading-dot
                # number `.5` is a valid next statement, so the brace stays a Block.
                "{} .x",
                "{ } .5",
                "{ } .5.5",
            ):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )

        def test_columns_qualifier_rejects_invalid_identifier_keywords(self):
            # The qualifier before `.*` inside `COLUMNS(...)` is the grammar's
            # `identifier` (`COLUMNS LPAREN identifier DOT ASTERISK ...`), so only
            # keywords admitted by `kw_valid_as_identifier` qualify. rust admitted any
            # keyword there, accepting `columns(try.*)` where cpp rejects. The chain
            # links (`columns(a.try.*)`) are `identifier` too and need the same gate.
            excluded = (
                "try",
                "catch",
                "finally",
                "null",
                "inf",
                "nan",
                "intersect",
                "except",
                "fn",
                "fun",
                "let",
                "while",
                "throw",
                "materialized",
            )
            for name in excluded:
                with self.assertRaises(BaseHogQLError):
                    parse_expr(f"columns({name}.*)", backend=backend)
            for query in ("columns(a.try.*)", "columns(a.b.catch.*)"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            # `kw_valid_as_identifier` keywords (and `true`/`false`, plain
            # idents, and multi-level chains) remain valid qualifiers.
            for query in (
                "columns(week.*)",
                "columns(select.*)",
                "columns(interval.*)",
                "columns(true.*)",
                "columns(false.*)",
                "columns(x.*)",
                "columns(a.b.*)",
                "columns(a.b.c.*)",
            ):
                parse_expr(query, backend=backend)

        def test_bare_qualified_star_replace_rejected(self):
            # A bare (unwrapped) `ColumnExprAsterisk` (grammar line 289) admits an
            # optional trailing EXCLUDE but never REPLACE — REPLACE is a columnExpr
            # only inside `columns(...)` / `(*...)`. rust consumed a trailing REPLACE
            # in the bare qualified-asterisk postfix path and silently dropped it,
            # accepting `a.* exclude(z) replace(1 as b)` where cpp rejects.
            for query in (
                "a.* replace(1 as b)",
                "a.* exclude(z) replace(1 as b)",
                "a.b.* exclude(z) replace(1 as b)",
            ):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            # Exclude-only bare forms and the wrapped REPLACE forms still parse.
            for query in (
                "a.* exclude(z)",
                "a.b.* exclude(z)",
                "a.*",
                "columns(a.* replace(1 as b))",
                "columns(a.* exclude(z) replace(1 as b))",
                "(* exclude(z) replace(1 as b))",
            ):
                parse_expr(query, backend=backend)

        def test_columns_qualified_asterisk_continuation_positions(self):
            # When a qualified asterisk (`a.*`) is the LHS of a postfix call or infix
            # op inside `COLUMNS(...)`, the continuation node's span must start at the
            # qualifier's start, not at the token after the asterisk. rust stamped the
            # call/arith node start at the `(` / operator instead of at `a`, so both
            # accepted but `columns[0].start` diverged. Assert full AST parity
            # (positions included) rather than just accept/reject.
            for query in (
                "columns(a.*(b))",
                "columns(a.b.*(c))",
                "columns(a.* + 1)",
                'columns("iei".*(a.b, c.d))',
                "columns(a.* exclude(z) + 1)",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_within_keyword_rejected_as_identifier(self):
            # WITHIN is a lexer keyword used only in the `within group (...)` clause;
            # the grammar's `keyword` rule omits it, so it is not a valid identifier.
            # rust admitted it via `kw_valid_as_identifier` / `kw_acts_as_ident_in_primary`,
            # accepting `within`, `x.within`, `columns(within.*)` as Fields and, at
            # statement level, `f() within ()` as `f(); within()`. All must reject.
            for query in ("within", "within()", "within + 1", "x.within", "1 as within", "columns(within.*)"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            for query in ("select within from t", "select 1 as within from t", "select x from t as within"):
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)
            for query in ("f() within ()", "within ()", "within"):
                with self.assertRaises(BaseHogQLError):
                    parse_program(query, backend=backend)
            # The legitimate `within group (...)` clause still parses.
            parse_expr("f() within group (order by x)", backend=backend)
            parse_select("select f() within group (order by x) from t", backend=backend)

        def test_positional_and_tuple_index_decimal_literal_parity(self):
            # `#N` (positional ref) and `a.N` / `a?.N` (tuple access) all take a
            # grammar DECIMAL_LITERAL index. rust's lexer folds hex / octal / float
            # into one Number kind, so it diverged two ways: `#N` OVER-ACCEPTED
            # hex/octal/float (`#0x6`, `#017`, `#1e3` became PositionalRef(0) via
            # `parse().unwrap_or(0)`), while `.N` / `?.N` OVER-REJECTED leading-zero
            # decimals (`a.08`, `a.019`) that cpp accepts because 8 and 9 are not
            # octal digits, so the lexer reads them as DECIMAL not OCTAL. All three
            # now share one `is_decimal_literal()` gate.
            rejected = (
                "#0x6",
                "#0X6",
                "#00",
                "#06",
                "#017",
                "#007",
                "#1e3",
                "a.0x6",
                "a.00",
                "a.06",
                "a.017",
                "a.1e3",
                "a?.06",
                "a?.00",
            )
            for query in rejected:
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            # Decimal indices parse on both, including leading-zero forms whose digits
            # escape the octal range (`08`, `019`). Assert full AST parity (positions
            # included) rather than just accept/reject.
            accepted = (
                "#0",
                "#6",
                "#08",
                "#019",
                "#10",
                "a.0",
                "a.8",
                "a.08",
                "a.019",
                "a.10",
                "a?.0",
                "a?.08",
                "a?.019",
            )
            for query in accepted:
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_nested_interval_reserves_unit_for_outer(self):
            # `INTERVAL <value> <unit>`: cpp's ALL(*) reserves the trailing unit for
            # the OUTER interval, so a nested INTERVAL in value position never takes
            # the unit-consuming form — it is string-only (`interval '5 day'`) or a
            # Field / call. rust used to let the inner interval eat the unit, which
            # over-rejected `interval interval '5 day' month` / `interval interval -
            # x second` (expr) and over-accepted `interval interval 'jihi' month`
            # (program, split into `interval` + `interval 'jihi' month`). The
            # parenthesised forms were already self-contained. Both accept here, so
            # assert full AST parity (positions included).
            for query in (
                "interval interval second",
                "interval interval - x second",
                "interval interval '5 day' month",
                "interval interval (1) second",
                "interval (interval '5 day') month",
                "interval (interval '5 day' month) second",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            # A nested bad-string interval rejects on both: the inner
            # ColumnExprIntervalString can't split into `<count> <unit>`. This must
            # also reject at program level (rust no longer splits it into two
            # statements once the inner string interval errors fatally).
            for query in ("interval interval 'jihi' month", "interval interval x second"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            with self.assertRaises(BaseHogQLError):
                parse_program("interval interval 'jihi' month", backend=backend)

        def test_select_from_keyword_table_vs_invalid_from_column(self):
            # `FROM implicitAlias # ColumnExprInvalidFromImplicitAlias` is a
            # SELECT-COLUMN footgun only: a bare `from <ident>` in TABLE position is
            # valid (`from b, from c` is table `from` aliased `c`). rust used to (1)
            # over-reject explicit-FROM from-as-table cases via a misdiagnosed
            # join.rs check, and (2) over-accept the trailing-comma `select a, from
            # b, from (c)` because it broke the column list at the FIRST from. cpp's
            # `selectColumnExprListBeforeFrom` makes every `from X` before the LAST
            # one a column; only the final `from` opens the clause. Accepting cases
            # assert full AST parity (positions included).
            accept = (
                # from-as-table in the FROM / join clause (explicit FROM):
                "select a from b, from c",
                "select * from from x",
                "select 1 from a, from b, from(c)",
                "select 1 from a join from b on 1",
                "select 1 from from c",
                "select x from t1, from t2, from t3",
                "select 1 from b as from",
                # the LAST `from` opens the clause; an earlier `from(...)` is a call column:
                "select a, from (b), from (c)",
                # single from / cross-join / subquery / union unaffected:
                "select a, from b",
                "select a, from b, c",
                "select a, from (b), c",
                "select a from b, c",
                "select a, from (select 1 from t), c",
                "select a, from b union all select c from d",
            )
            for query in accept:
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )
            # Two+ top-level `from`s: every `from` before the last is a SELECT
            # column, and a bare `from <ident>` column is the rejected footgun.
            reject = (
                "select from x",
                "select a, from b, from c",
                "select a, from b, from (c)",
                "select a, from b, x, from (c)",
                "select a, from b, from c, from d",
            )
            for query in reject:
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)

        def test_from_trailing_comma_only_after_join_constraint(self):
            # A trailing comma in the FROM clause is valid ONLY as the ON / USING
            # `columnExprList`'s optional `COMMA?` (`a JOIN b ON 1,`); cpp's
            # JoinConstraint span includes it. After a cross / plain / positional
            # join the trailing comma is rejected. rust used to discard any
            # post-join trailing comma (over-accepting `a, b,` / `a join b,`) and
            # ended the constraint span before the comma (a position mismatch on the
            # constrained cases). Accepting cases assert full AST parity (positions).
            accept = (
                "select x from a join b on 1,",
                "select x from a left join b on 1,",
                "select x from a join b using c,",
                "select x from a join b using (c),",
                "select x from (a join b on 1,)",
                "select x from a join b using a, b,",
                # controls (no trailing comma):
                "select x from a, b",
                "select x from a join b on 1",
                "select x from a join b",
                "select x from a, b, c",
            )
            for query in accept:
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )
            # Trailing comma after a cross / plain / positional join (no constraint
            # to own it) rejects on both.
            reject = (
                "select x from a, b,",
                "select x from a cross join b,",
                "select x from a join b,",
                "select x from a positional join b,",
                "select x from a join b on 1, c,",
                "select x from a, from b,",
            )
            for query in reject:
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)

        def test_interval_without_unit_does_not_over_commit(self):
            # cpp commits to the INTERVAL form only for a STRING_LITERAL (the
            # ColumnExprIntervalString alt). `interval <number|ident|quoted-ident>`
            # with NO trailing unit is NOT an interval: cpp backtracks to `interval`
            # as a Field. So at expr level it rejects (trailing tokens) on both, but
            # at PROGRAM level it splits into two statements (`interval` + value).
            # rust used to commit fatally for number/ident/quoted-ident too, which
            # over-rejected the program split.
            for query in ("interval 1", "interval x", 'interval "a"'):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            # A STRING value still commits (a bad single-token string rejects at both
            # expr and program level — no two-statement split).
            with self.assertRaises(BaseHogQLError):
                parse_program("interval 'a'", backend=backend)
            # A trailing unit still makes it a real interval Call on both backends.
            for query in ("interval 1 day", 'interval "a" day', "interval x day"):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_statement_boundary_splits_incomplete_special_infix_and_postfix(self):
            # At a statement boundary, an INCOMPLETE special-infix (LIKE / BETWEEN /
            # IN / IS) or postfix (`[`) is cpp's "end this statement, start the next"
            # shape, not an error: `week like` -> two Field statements, `"_" between
            # "_"` -> three, `[ ] [ ]` -> two empty-array statements. rust's Pratt
            # loop used to apply the operator greedily and error. These all parse on
            # both backends with identical ASTs (positions included).
            for query in (
                "week like",
                '"_" between "_"',
                "[ ] [ ]",
                "[ ] [ ] [ ]",
                "week and",
                "a in",
                "a is",
            ):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )
            # At EXPRESSION level there is no next statement, so the same incomplete
            # forms stay hard errors on both backends (recovery is statement-only).
            for query in ("week like", "[ ] [ ]", "a between b", '"_" between "_"'):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)
            # COMPLETE forms are unaffected — still parse identically on both.
            for query in ("a like b", "a between b and c", "a[b]", "a in (1, 2)", "a is null", "a not like b"):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_not_and_modulo_accept_hogqlx_tag_operand(self):
            # `<` begins a HogQLX tag as well as the less-than operator. In bounded
            # lookahead rust used to always read `<` as less-than, so `not <a/>`
            # stranded the tag (NOT became a Field) and `1 % <a/>` abandoned the
            # modulo. cpp reads the tag operand. Both parse identically here.
            for query in (
                "not <a/>",
                "not <a></a>",
                "[not <a/>]",
                "1 and not <a/>",
                "f(not <a/>)",
                "1 % <a/>",
                "[1 % <a/>]",
                "(1 % <a/>)",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            # Genuine less-than / modulo (no tag following) are unchanged.
            for query in ("not < 2", "1 % 2", "1 % x"):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_boolean_literal_numeric_tuple_access_keeps_constant(self):
            # `true.1` / `false.0` are tuple access on the boolean Constant, not a
            # Field chain — cpp keeps Constant(true) as the tuple base. rust used to
            # route every `true.`/`false.` through ident-lead, making the base a
            # Field. `true.x` (chain), `true(1)` (call) and `null.1` are unaffected.
            for query in ("true.1", "false.0", "true.1.2", "true.x", "true(1)", "true", "null.1"):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_return_keyword_as_identifier_before_infix_postfix(self):
            # `return` is also a keyword-rule identifier. When it is followed by a
            # pure infix / postfix operator, that operator binds `return` as its
            # LHS, so the line is one exprStmt (`return :: t`, `return.x`, `return
            # -> y`, `return = 1`, `return / 2`), not a bare return that strands the
            # operator. A value-starter keeps the return statement (`return 1`,
            # `return + 1`); a keyword-infix keeps the bare-return split (`return
            # like x` is `return` + `like x`).
            for query in (
                "return -> y",
                "return :: date",
                "return . x",
                "return ?. x",
                "return = 1",
                "return / 2",
                "return || x",
                "return < 2",
                "return != 1",
                "return ?? x",
            ):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )
            for query in ("return 1", "return + 1", "return [1]", "return", "return like x", "return * 2"):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )
            # `.` is special: a leading-dot float (`return .5` -> value 0.5,
            # `return .5.5` -> tuple-access on 0.5) is a return VALUE, while a
            # `.`-chain-link (`return .x`) makes `return` an identifier (tuple /
            # field). Both must match cpp (regression guard for the #16 dispatch).
            for query in ("return .5", "return .5.5", "return . 5", "return .x"):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )

        def test_not_before_statement_keyword_falls_back_to_field(self):
            # At a statement boundary, `not` followed by a statement keyword that is
            # not a valid expression operand (`let`, `throw`) is `not` as a bare
            # Field statement followed by the keyword's statement — not a NOT whose
            # operand fails. rust used to commit NOT to the operator and reject.
            for query in ("not let x", "not throw x"):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )
            # An incomplete `not let` (no value) or a keyword that is neither a
            # valid operand nor a complete statement still rejects on both.
            for query in ("not let", "not while x", "not fn x"):
                with self.assertRaises(BaseHogQLError):
                    parse_program(query, backend=backend)

        def test_block_then_empty_param_lambda_is_two_statements(self):
            # `{…} ()` is a dict / placeholder called with empty args (one
            # exprStmt), but `{…} () -> body` is a Block followed by an empty-param
            # lambda statement (two statements). rust used to force the empty-call
            # interpretation and then reject when the block body was not a dict.
            for query in ("{ } () -> 1", "{ let q := 1; } () -> 1;", "{ if (1) {} } () -> 1"):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )
            # Unchanged: empty call (no arrow), non-empty params, dict, plain block.
            for query in ("{ } ()", "{ 1 } ()", "{ } (a) -> 1", "{ } () + 1", "{1: 2}", "{ let x := 1; }"):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )

        def test_hogqlx_tag_name_rejects_non_identifier_keywords(self):
            # A HogQLX tag/attr name is a grammar `identifier`, so a keyword head is
            # valid only when the grammar's `keyword` rule admits it. The Hog-statement
            # keywords (fn/fun/let/while/throw/try/catch/finally), set-op keywords
            # (intersect/except), literal keywords (null/inf/nan) and within/materialized
            # are omitted from that rule, so cpp rejects `<fn/>`; rust used to accept
            # them as tag/attr names (over-accept).
            for kw in (
                "fn",
                "fun",
                "let",
                "while",
                "throw",
                "try",
                "catch",
                "finally",
                "intersect",
                "except",
                "null",
                "inf",
                "nan",
                "within",
                "materialized",
            ):
                for query in (f"< {kw} />", f"< a {kw} />"):
                    with self.assertRaises(BaseHogQLError):
                        parse_expr(query, backend=backend)
            # Keywords that the grammar's `keyword` rule admits stay valid tag names.
            for kw in ("and", "select", "from", "by", "group", "order", "day", "sample"):
                self.assertEqual(
                    parse_expr(f"< {kw} />", backend="cpp-json"),
                    parse_expr(f"< {kw} />", backend=backend),
                    msg=kw,
                )

        def test_not_falls_back_to_field_when_operand_invalid(self):
            # In EXPRESSION context cpp's single-expression parse reads a leading NOT
            # as a Field when its operand can't parse, so a following infix binds to
            # it: `not < a` -> `(Field not) < a`, `not + a` -> `(Field not) + a`,
            # `not in a` -> `(Field not) in a`, `not as x` -> `Field(not) AS x`. A bare
            # `not as` keeps `Not(Field('as'))` (the operand parses). rust used to
            # commit NOT to the unary operator and reject. `not in (1,2)` stays the
            # unary `Not(Call(in, …))`.
            for query in (
                "not < a",
                "not + a",
                "not in a",
                "not as",
                "not as x",
                "not as date",
                "not like 'a'",
                "not in (1,2)",
                "not x",
                "a not in b",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            # At a STATEMENT boundary cpp takes the shortest leading statement, so
            # `not <op-keyword> <rhs>` is `Not(Field(<kw>))` (statement 1) and `<rhs>`
            # opens the next statement (two declarations), not the greedy single
            # expression. rust used to glue it into one statement.
            for query in (
                "not in a",
                "not like 'a'",
                "not and a",
                "not is null",
                "not * a",
                "not ignore nulls",
            ):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )

        def test_in_cohort_marker_only_before_a_complete_value(self):
            # `IN COHORT? columnExpr`: cpp takes the COHORT marker only when a complete
            # value follows it. When COHORT is followed by an operator it is the IN rhs
            # Field (or part of the rhs expression): `a in cohort < b` ->
            # `(a in cohort) < b`, `a in cohort like b` -> `(a in cohort) like b`,
            # `a in cohort * b` -> `a in (cohort * b)`. rust used to greedily eat COHORT
            # and choke on the empty / dangling value.
            for query in (
                "a in cohort < b",
                "a in cohort + b",
                "a in cohort * b",
                "a in cohort like b",
                "a in cohort is null",
                "a not in cohort < b",
                "a not in cohort * b",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            # COHORT stays a marker before a complete value (a bare `*`, a negative
            # number, a tag, a parenthesised/array value, or a plain primary), and a
            # value followed by an outer infix (`cohort 1 < b`) still works.
            for query in (
                "a in cohort 1",
                "a in cohort x",
                "a in cohort *",
                "a in cohort -1",
                "a in cohort <foo/>",
                "a in cohort (1)",
                "a in cohort [1]",
                "a in cohort 1 < b",
                "a not in cohort 1",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_select_distinct_reread_as_column_when_no_value_follows(self):
            # `SELECT DISTINCT? columnExprList`: DISTINCT is the modifier only when a
            # column follows. When the next token ends the column list (comma / EOF)
            # or opens a clause, cpp re-reads DISTINCT as the sole column Field:
            # `SELECT DISTINCT` -> `[Field(distinct)]`, `SELECT DISTINCT ORDER BY 1` ->
            # `[Field(distinct)]` + ORDER BY. rust used to keep DISTINCT a modifier and
            # then reject on the empty / clause-keyword column slot.
            for query in (
                "SELECT DISTINCT",
                "SELECT DISTINCT, a",
                "SELECT DISTINCT ORDER BY 1",
                "SELECT DISTINCT GROUP BY 1",
                "SELECT DISTINCT WHERE 1",
                "SELECT DISTINCT HAVING 1",
                "SELECT DISTINCT LIMIT 1",
                "SELECT DISTINCT group by 1",
            ):
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )
            # DISTINCT stays the modifier before a real column (incl. a bare keyword
            # column like `group` with no `BY`).
            for query in (
                "SELECT DISTINCT a",
                "SELECT DISTINCT a, b",
                "SELECT DISTINCT *",
                "SELECT DISTINCT day",
                "SELECT DISTINCT group",
            ):
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )
            # `SELECT DISTINCT FROM x` keeps DISTINCT a modifier and rejects on both
            # via the FROM-implicit-alias footgun (DISTINCT is NOT re-read here).
            with self.assertRaises(BaseHogQLError):
                parse_select("SELECT DISTINCT FROM x", backend=backend)

        def test_distinct_with_empty_parens_is_a_function_call(self):
            # `distinct()` with EMPTY parens is the zero-arg call `Call(distinct,
            # [])`, not the DISTINCT modifier: cpp can't read DISTINCT as the
            # modifier with only `()` (no column) after, so it backs off to a call.
            for src in ("SELECT distinct()", "SELECT distinct() FROM a"):
                self._assert_ast(src, "select")
            # Guard: non-empty parens keep DISTINCT the modifier on the column.
            for src in ("SELECT distinct(x)", "SELECT distinct(x), y"):
                self._assert_ast(src, "select")
            # Same rule one level down: `count(distinct())` is `count` over a
            # nested `distinct()` call, not the args DISTINCT-marker (empty `()` only).
            for src in ("count(distinct())", "f(distinct())", "count(distinct() + 1)"):
                self._assert_ast(src, "expr")
            # Guards: non-empty parens / non-leading position keep the args-marker.
            for src in ("count(distinct(x))", "count(distinct x)", "f(x, distinct())"):
                self._assert_ast(src, "expr")

        def test_hogqlx_attribute_and_text_child_positions_match(self):
            # cpp positions each HogQLXAttribute (name start -> value end, or name end
            # for a bare attribute), the string value Constant over the string token,
            # and each text-child Constant over its raw byte span. rust left these
            # inner nodes position-less. The shared suite strips positions, so this
            # asserts exact-position parity (the comparison keeps positions).
            for query in (
                "<a b='1' />",
                "<a b='1' c='2' />",
                "< a and />",
                "<a>x</a>",
                "<a>hello world</a>",
                "<a b='1'>text</a>",
                "<a b={1} />",
                "<outer><inner k='v'>t</inner></outer>",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_lambda_keyword_is_a_plain_alias_after_as(self):
            # The grammar's explicit `AS identifier` admits every keyword, so `AS
            # lambda` is a plain alias `Alias(expr, 'lambda')` in expression context.
            # rust blanket-refused `AS lambda` (it only ever heads a lambda value in
            # `INTERPOLATE (expr AS columnExpr)`), so it rejected the alias. Refuse
            # only when a lambda BODY (`lambda [params] :`) actually follows.
            for query in (
                "1 as lambda",
                "x as lambda",
                "(1) as lambda",
                "1 + 1 as lambda",
                "[1 as lambda]",
                "f(1 as lambda)",
                "1 as lambda()",
                "1 as lambda + 2",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            for query in ("select 1 as lambda", "select 1 as lambda, 2", "select 1 as lambda from t"):
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )
            # A real lambda body after `AS` is not a valid alias and rejects on both
            # in plain expression context (the alias absorbs `lambda`, the `:` trails).
            for query in ("1 as lambda: 2", "1 as lambda x: x", "1 as lambda x"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(query, backend=backend)

        def test_empty_fstring_constant_spans_whole_token(self):
            # An empty f-string `f''` has no interior text, so cpp spans its Constant
            # over the whole `f''` token, not the zero-width gap between the quotes.
            # rust positioned it at the interior; the comparison keeps positions.
            for query in ("f''", "f'a'", "f'ab'", "f'  '", "[f'']", "f'' || f''"):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_template_unknown_escape_with_multibyte_char(self):
            # An unknown f-string escape `\X` drops the backslash and the escaped char (cpp's `STRING_TEXT` lexer behaviour). When `X` is a multibyte codepoint (`\é`, `\😀`) the rust body splitter must step past the whole codepoint — a fixed 2-byte step landed mid-char and panicked the body slice, an uncatchable `PanicException` on the json path that also escaped `except Exception`. cpp accepts all of these, so matching it (value + positions) is a parity requirement.
            self.assertEqual(self._expr(r"f'\é'"), ast.Constant(value=""))
            self.assertEqual(self._expr(r"f'\😀z'"), ast.Constant(value="z"))
            self.assertEqual(self._expr(r"f'\éxyz'"), ast.Constant(value="xyz"))
            # Full position parity against cpp for the position-carrying backends.
            for src in (r"f'\é'", r"f'\éxyz'", r"f'\😀z'", r"f'ab\écd'", r"f'\é{1}\😀'"):
                expected = parse_expr(src, backend="cpp-json")
                actual = parse_expr(src, backend=backend)
                self.assertEqual(actual, expected, msg=src)

        def test_interpolate_expr_carries_positions(self):
            # The INTERPOLATE item node (InterpolateExpr) was built without a position
            # wrap, so it came back position-less; cpp spans it from the expr start to
            # the value end (or the expr end when there is no `AS value`).
            for query in (
                "select 1 order by a with fill interpolate (b)",
                "select 1 order by a with fill interpolate (b as 5)",
                "select 1 order by a with fill interpolate (b, c)",
                "select 1 order by a with fill interpolate (b as c, d)",
            ):
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )

        def test_between_span_includes_parenthesized_high_closing_paren(self):
            # A simple BETWEEN spans through the high operand's last consumed token,
            # so a parenthesized `high` (`1 between 2 and (3)`) must include the
            # trailing `)`. rust used `high.end` (the inner expr, parens stripped),
            # leaving the BetweenExpr end one byte short. The comparison keeps
            # positions.
            for query in (
                "1 between (2) and (3)",
                "1 between 2 and (3)",
                "1 between (2) and 3",
                "1 not between 2 and (3)",
                "a between (b) and (c)",
                "1 between (2+3) and (4)",
                "1 between (2) and (3) + 4",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_leading_comma_from_implicit_alias_dangling_clause(self):
            # Under a leading/trailing comma, cpp's greedy `selectColumnExprListBeforeFrom`
            # consumes `from <implicitAlias>` (+ any following cross-join tables) as
            # columns up to a trailing comma when a two-token clause introducer
            # (`USING SAMPLE` / `ARRAY JOIN`) follows it — then its visitor rejects the
            # `ColumnExprInvalidFromImplicitAlias` column. rust used to open the FROM
            # clause at `from f` and consume `using`/`array` as a cross-join table.
            # A depth-0 dangling-clause forward-scan now matches cpp: both reject.
            for query in (
                "select 1, from f, using sample 1",
                "select 1, from f, array join x",
                "select 1, from f, g, using sample 1",
                "select 1, from f, g, array join x",
            ):
                with self.assertRaises(BaseHogQLError, msg=query):
                    parse_select(query, backend=backend)
            # A bare keyword cross-join table (no SAMPLE/JOIN completing the clause),
            # and the no-leading-comma form, keep `using`/`array` as real tables — both
            # accept, so the suppression stays scoped to the dangling-comma case.
            for query in (
                "select 1, from f, using",
                "select 1, from f, array",
                "select 1, from f, using x",
                "select 1, from f, array x",
                "select 1 from f, using sample 1",
                "select 1 from f, array join x",
                "select 1, from f, g",
            ):
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )

        def test_date_literal_tolerated_in_discarded_set_decorators(self):
            # A `selectSetStmt`'s trailing `orderByClause?` is always grammar-parsed
            # but never emitted by cpp's `VISIT(SelectSetStmt)`, and its trailing
            # LIMIT / OFFSET are dropped when the body is a `{placeholder}` (which
            # can't carry them). cpp never visits those discarded subtrees, so an
            # unsupported `date`/`timestamp` literal anywhere inside (incl. nested
            # selects / calls) is tolerated. rust used to commit to the date literal
            # and fatally reject; the suppression now leaks into the whole discarded
            # subtree, matching cpp.
            for query in (
                "( {x} order by date 'z' )",
                "( {x} order by (select 1 order by date 'z') )",
                "( {x} order by f(date 'z') )",
                "( {x} order by date 'z' + 1 )",
                "( (select 1) order by (select date 'z') )",  # ORDER BY discarded even for a real subquery
                "( {x} order by date 'z' limit 1 )",
                "( {x} limit date 'z' )",  # placeholder LIMIT dropped -> tolerated
                "( {x} offset date 'z' )",
                "( {x} limit date 'z' with ties )",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            program = "range := ( { ( 'nlhonme ' ) } order by 'e' , date 'fa' collate 'a' ) "
            self.assertEqual(
                parse_program(program, backend="cpp-json"),
                parse_program(program, backend=backend),
            )
            # Still strict where cpp DOES visit: a real SelectQuery's kept order by /
            # limit / offset, and a bare / placeholder-block date literal. All must
            # reject on both backends (the placeholder LIMIT suppression must not
            # leak to a real `(select …)` body). A set op (UNION / EXCEPT) wraps the
            # result in a decorator-carrying SelectSetQuery, so its LIMIT is KEPT and
            # visited even when the operands are placeholders — the suppression must
            # not fire there either.
            for query, fn in (
                ("select 1 order by date 'x'", parse_select),
                ("select 1 order by (select date 'z')", parse_select),
                ("select 1 limit date 'x'", parse_select),
                ("(select 1) limit date 'x'", parse_select),
                ("(select 1) offset date 'x'", parse_select),
                ("{1} except {2} limit date 'x'", parse_select),
                ("({1}) union all ({2}) limit date 'x'", parse_select),
                ("({1}) except {2} limit interval 'p'", parse_select),
                ("date 'x'", parse_expr),
                ("{ date 'x' }", parse_program),
            ):
                with self.assertRaises(BaseHogQLError, msg=query):
                    fn(query, backend=backend)

        def test_interval_string_without_unit_tolerated_in_unvisited_clause(self):
            # `INTERVAL <string>` with no `<count> <unit>` content is cpp's
            # `ColumnExprIntervalString`, which `visitColumnExprIntervalString`
            # rejects — so it's tolerated in the same clauses cpp grammar-parses but
            # never visits (discarded ORDER BY, a placeholder body's LIMIT). rust
            # used to fatally require a unit keyword.
            for query in (
                "{x} order by interval 'pk'",
                "{x} order by interval 'pk' collate ''",
                "{x} order by 1 with fill to interval 'g'",
                "{x} limit interval 'p'",
            ):
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )
            # Still strict elsewhere: a KEPT clause visits it, a bare / block form
            # rejects, and a non-string interval value with no unit is a grammar
            # error even when discarded (so the suppression is string-gated).
            strict: list[tuple[str, object]] = [
                ("select 1 order by interval 'pk'", parse_select),
                ("select 1 limit interval 'pk'", parse_select),
                ("interval 'pk'", parse_expr),
                ("{ interval 'ln' }", parse_program),
                ("{x} order by interval 1", parse_select),
                ("{x} order by interval x", parse_select),
            ]
            for query, fn in strict:
                with self.assertRaises(BaseHogQLError, msg=query):
                    fn(query, backend=backend)

        def test_interval_value_pending_flag_does_not_leak(self):
            # `parse_interval_expr` flags the value's leading primary as a nested
            # interval (one-shot, consumed by `parse_primary`). When the value parse
            # errors BEFORE reaching `parse_primary` (a bare `interval` as an
            # arithmetic operand: `interval + …`), the flag must not leak past the
            # enclosing `try_alt` rollback and corrupt the FOLLOWING interval — which
            # caused `interval + interval '5 day' month` to wrong-reject and
            # `interval - interval '5 day' month` to build a mangled AST.
            for query in (
                "interval + interval '5 day' month",
                "interval - interval '5 day' month",
                "interval * interval '2 hour' day",
                "x + interval '5 day' month",
                "1 + interval '5 day' month",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_window_filter_body_suppresses_visitor_rejections(self):
            # A window function's FILTER body is grammar-parsed but never visited
            # (the AST discards it), so visitor-level rejections inside it must be
            # tolerated to match cpp: a no-column `select … from …` subquery (cpp's
            # `ColumnExprInvalidFromImplicitAlias`) and a unit-less `interval
            # '<str>'` (cpp's `ColumnExprIntervalString`). rust used to fatally
            # reject both before the body could be discarded.
            for query in (
                "a() filter(where (select from x)) over a",
                "\"\"() filter(where interval 'bm ') over ()",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            # Guards: the same forms reject when VISITED (at expr level), and a
            # genuine grammar error in the body still rejects even when discarded.
            strict = (
                "(select from x)",
                "interval 'bm '",
                "a() filter(where (select where 1)) over a",
            )
            for query in strict:
                with self.assertRaises((BaseHogQLError, SyntaxError), msg=query):
                    parse_expr(query, backend=backend)

        def test_nested_interval_value_skips_postfix_run_for_unit(self):
            # `INTERVAL <value> <unit>` whose value is itself a nested INTERVAL
            # carrying a postfix run (a `()` call, `[…]` index, `.id` access):
            # cpp resolves the trailing unit keyword by looking PAST the postfix
            # operators. rust used to stop at the postfix and miss the unit, so it
            # mis-parsed the nesting (`interval interval 0 hour () hour`).
            for query in (
                "interval interval 0 week week",
                "interval interval 0 hour () hour",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_nested_string_interval_dispatches_on_trailing_unit_count(self):
            # A nested string-valued INTERVAL: cpp keeps the inner string
            # self-contained (`'5 day'`) when ONE unit trails (it's the OUTER's),
            # but reads it as the value-expr of an expr+unit inner when TWO trail —
            # the value-expr reading sidesteps the string's count/unit validation,
            # so `''` / `'bm '` parse there (`interval interval '' day month` →
            # `INTERVAL (INTERVAL '' DAY) MONTH`). A window FILTER body, being
            # grammar-parsed but never visited, also tolerates a bad inner string.
            # rust used to always use the string-only reading and wrong-reject these.
            for query in (
                "interval interval '' day month",
                "interval interval '5 day' hour month",
                "a() filter(where interval interval 'bm ' day) over a",
                "a() filter(where interval interval '' day month) over a",
                # one trailing unit keeps the inner string-only — still parity
                "interval interval '5 day' month",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            # Guard: a bad inner string with a SINGLE trailing unit has no
            # value-expr escape hatch, so it rejects when VISITED.
            with self.assertRaises((BaseHogQLError, SyntaxError), msg="interval interval 'bm ' day"):
                parse_expr("interval interval 'bm ' day", backend=backend)

        def test_stacked_table_alias_span_ends_at_first_alias(self):
            # `TableExprAlias` is left-recursive (`x a b c`): cpp's nested ctxs end
            # the JoinExpr span at the INNERMOST (first) alias, while each outer
            # alias only overwrites `alias` / `column_aliases`. rust extended the
            # span to the last alias. Covers the `t format JSON` FORMAT-as-alias
            # chain and column-alias stacks. (Single / no alias are unchanged.)
            for query in (
                "select 1 from x t",
                "select 1 from x a b",
                "select 1 from x a b c",
                "select 1 from x t format JSON",
                "select 1 from x (c1, c2)",
                "select 1 from x a (c1) b (c2)",
            ):
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )

        def test_between_split_synthetic_node_positions(self):
            # When the greedy BETWEEN-body parse is split at the rightmost AND, the
            # rebuilt And/Or (and the wrappers it descends through) must carry cpp's
            # ctx-derived span, not the children's inner (paren-stripped) span. cpp
            # positions a boolean node from its FIRST operand's `(` and LAST operand's
            # `)`, and a stay-in-place wrapper (Lambda / Not / arith.right / the
            # if-call else-branch) ends where its now-shorter child ends. A no_pos
            # NamedArgument operand still contributes its `value`'s end.
            for query in (
                "x between (1) and (2) or y",  # synthetic Or start = `(` of `(2)`
                "1 between 2 and (3) and 4",  # synthetic And end = `)` of `(3)`
                "x between (1) and lambda z: (2) and (3)",  # Lambda body end shrinks
                "a between not lambda x: (b) and (c) and d",  # Not + Lambda descent
                "x between 1 and (2) * (3) and 4",  # arith.right end shrinks
                "a between b ? c : (d) and (e) and f",  # if-call else-branch end
                "1 between 2 between 3 and (4) and 5",  # nested BETWEEN low peel
                "x between y between z and (w) and v",
                "p between (q) and r := (s) and (t)",  # no_pos NamedArgument last operand
                "m between (n) and o := (p) and q := (r) and (s)",
                "x between (1) and ((2) or (3)) and (4)",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_between_parenthesized_group_high(self):
            # `a and (b and c)` flattens to `And([a,b,c])` (cpp does too for a standalone
            # expr), but in a BETWEEN body cpp keeps `(b and c)` as one high operand: the
            # rightmost AND at paren-depth 0 is the one BEFORE the parens, so
            # `1 between a and (b and c)` is `low=a, high=And(b,c)`. rust used to descend
            # into the flattened inner AND and mis-split to `low=And(a,b), high=c`. The
            # split now skips ANDs inside parens (paren-depth-0 rule).
            for query in (
                "1 between a and (b and c)",
                "1 between a and ((b) and (c))",
                "1 between a and (b and c and d)",
                "1 between x and y and (b and c)",
                "1 between a and (b or c)",
                "1 between (a and b) and c",
                "1 between a and (b and c) or d",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_return_empty_parens_is_a_call(self):
            # `return ()` — empty parens are not a valid return value, so cpp re-reads
            # `return` as a Field and `()` as an empty call: `Call(return, [])`. rust
            # used to commit to the return statement and reject the empty parens. A
            # `return (expr)` (incl. empty `[]` / `{}` which ARE valid values) keeps
            # the returnStmt.
            for query in ("return ()", "return ( )", "return () + 1", "x := return ()", "return () ()"):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )
            for query in ("return (1)", "return (1, 2)", "return []", "return {}", "return"):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )

        def test_bare_star_decorator_splits_at_statement_boundary(self):
            # A bare `*` admits only a valid `EXCLUDE (<identifiers>)` (no REPLACE, no
            # string/empty list). At a statement boundary an invalid decorator is cpp's
            # `*` (or `* EXCLUDE(...)`) statement followed by `exclude(...)` / `replace(...)`
            # as the NEXT statement's call: `* exclude ('j')` -> `*` ; `exclude('j')`,
            # `* replace (1 as b)` -> `*` ; `replace(1 as b)`, `* exclude (a) replace (b as c)`
            # -> `ColumnsExpr(exclude=[a])` ; `replace(b as c)`. rust used to reject.
            for query in (
                "* exclude ('j')",
                "* exclude ()",
                "x := * exclude ('j')",
                "osl := * exclude ()",
                "* replace (1 as b)",
                "* exclude (a) replace (1 as b)",
                "x := * replace (1 as b)",
            ):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )
            # A valid `* EXCLUDE (<idents>)` stays one columns-expr; outside a statement
            # boundary (a SELECT column) an invalid / REPLACE decorator rejects on both,
            # and the paren-wrapped `(* REPLACE …)` form stays valid.
            for query in (
                "select * exclude (a) from t",
                "select (* replace (1 as b)) from t",
            ):
                self.assertEqual(
                    parse_select(query, backend="cpp-json"),
                    parse_select(query, backend=backend),
                    msg=query,
                )
            for query in ("select * exclude ('j') from t", "select * replace (1 as b) from t"):
                with self.assertRaises(BaseHogQLError):
                    parse_select(query, backend=backend)

        def test_invalid_filter_clause_splits_at_statement_boundary(self):
            # The aggregate FILTER clause requires `(WHERE <expr>)`. An invalid FILTER
            # (`filter ()`, no WHERE) is, at a statement boundary, cpp's completed
            # `<call>()` statement followed by a `filter(...)` call as the NEXT
            # statement: `l() filter ()` -> `l()` ; `filter()` (also for parametric
            # `quantile(0.5)(x) filter ()`). rust used to commit to the clause and
            # reject. A valid `filter (where …)` stays one expression (the clause is
            # consumed and dropped).
            for query in (
                "l() filter ()",
                "count() filter ()",
                "x := l() filter ()",
                "l() filter filter ()",
                "quantile(0.5)(x) filter ()",
            ):
                self.assertEqual(
                    parse_program(query, backend="cpp-json"),
                    parse_program(query, backend=backend),
                    msg=query,
                )
            for query in ("count() filter (where 1)", "sum(x) filter (where y > 1) over ()", "count() over ()"):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            # Outside a statement boundary (a SELECT column) the invalid FILTER rejects.
            with self.assertRaises(BaseHogQLError):
                parse_expr("count() filter ()", backend=backend)

        def test_filter_where_body_grammar_parsed_visitor_discarded(self):
            # cpp's window FILTER (with OVER) grammar-parses the WHERE body but
            # never visits it, so DATE/TIMESTAMP/INTERVAL string literals and
            # ColumnTypeExprEnum cast types accept; aggregate FILTER (no OVER)
            # visits and rejects them. Pin both arms of the cpp/rust boundary.
            for query in (
                "f() FILTER (WHERE date '') OVER w",
                "f() FILTER (WHERE timestamp '') OVER w",
                "f() FILTER (WHERE interval '') OVER w",
                "f() FILTER (WHERE cast(1 as q('a' = 1))) OVER w",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            for query in (
                "f() FILTER (WHERE date '')",
                "f() FILTER (WHERE timestamp '')",
                "f() FILTER (WHERE interval '')",
                "f() FILTER (WHERE cast(1 as q('a' = 1)))",
            ):
                with self.assertRaises(BaseHogQLError, msg=query):
                    parse_expr(query, backend=backend)

        def test_cast_type_enum_vs_param_fallback(self):
            # A cast type `q(...)` is `ColumnTypeExprEnum` only when every entry is a
            # `string '=' numberLiteral` (the visitor then rejects it as unsupported).
            # If any value isn't a numberLiteral (`''`, an ident, `1 + 2`) or the
            # separator is `==`, ANTLR falls back to `ColumnTypeExprParam` (a
            # columnExpr param), which cpp accepts. rust used to commit to the enum
            # path on a `string =` head and reject these.
            for query in (
                "cast(1 as q('a' = ''))",
                "cast(1 as q('a' = 'b'))",
                "cast(1 as q('a' = x))",
                "cast(1 as q('a' = 1 + 2))",
                "cast(1 as q('a' == 1))",
                "cast(1 as q('a' = 1, 'b' = ''))",
                "try_cast(1 as q('a' = ''))",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )
            # A real enumValue list (string '=' numberLiteral, incl. floats / inf /
            # signed / trailing comma) stays ColumnTypeExprEnum and rejects on both.
            for value in ("1", "-1", "1.5", "1.5e3", "2447.9157e+17", "inf", "nan", "0x1f", ".5"):
                with self.assertRaises(BaseHogQLError):
                    parse_expr(f"cast(1 as q('a' = {value}))", backend=backend)
            # A NESTED enum (an enum type sitting in another type's parens, e.g.
            # `q(w('k' = 1))`) is a `ColumnTypeExprEnum` cpp also rejects. rust used
            # to mask the nested enum's (fatal) rejection with the raw-text Param
            # fallback and over-accept; the type-param parser now propagates fatal
            # errors instead.
            for value in ("1", "inf", "nan", "0x1f"):
                for query in (f"cast(1 as q(w('k' = {value})))", f"cast(1 as q(w('a' = 1, 'b' = {value})))"):
                    with self.assertRaises(BaseHogQLError, msg=query):
                        parse_expr(query, backend=backend)
            # A nested NON-enum (string / ident value) falls back to Param and is
            # accepted on both — the fatal propagation must not over-reject these.
            for query in (
                "cast(1 as q(w('k' = '')))",
                "cast(1 as q(w('k' = x)))",
                # Non-enum parametric / nested / complex types are unaffected.
                "cast(1 as Decimal(10, 2))",
                "cast(1 as FixedString(5))",
                "cast(1 as Array(Int))",
                "cast(1 as Tuple(UInt8, String))",
                "cast(1 as Array(Tuple(UInt8, String)))",
            ):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

        def test_cast_type_enum_template_string_key_rejected(self):
            # `enumValue: string '=' numberLiteral`, and `string` is
            # STRING_LITERAL | templateString — so an `f'…'` key makes
            # `cast(0 as a(f''=0))` a `ColumnTypeExprEnum` that cpp rejects as
            # unsupported. rust used to check only STRING for the key and
            # over-accept the template-keyed enum as a raw Param type name.
            for query in (
                "cast(0 as a(f''=0))",
                "cast(0 as a(f'x'=1))",
                "cast(0 as a(f'{1}'=2))",
                "cast(0 as a('k'=1, f''=2))",
                "try_cast(0 as a(f''=0))",
            ):
                with self.assertRaises(BaseHogQLError, msg=f"{backend}: {query}"):
                    parse_expr(query, backend=backend)
            # Guard: a template not followed by `= numberLiteral` is a Param type
            # (not an enum), still accepted on both.
            for query in ("cast(0 as a(b))", "cast(0 as a(f''))"):
                self.assertEqual(
                    parse_expr(query, backend="cpp-json"),
                    parse_expr(query, backend=backend),
                    msg=query,
                )

    return TestParser
