"""Property-based tests for the HogQL parser ↔ printer roundtrip.

We generate random AST expression trees, print them to HogQL strings, then
parse them back and verify the result matches the original. Because the
printer normalises some constructs (e.g. ``1 + 2`` → ``plus(1, 2)``), we
compare at the *printed-string* level: ``print(parse(print(ast))) == print(ast)``.

As a bonus this also tests **parser backend equivalence**: every generated
string is parsed with both the Python and C++ backends and the results are
compared.
"""

import math
from typing import Any

import pytest

from hypothesis import (
    HealthCheck,
    assume,
    given,
    settings,
    strategies as st,
)

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_expr

# ---------------------------------------------------------------------------
# AST generation strategies
# ---------------------------------------------------------------------------

# Identifiers that are safe for round-tripping: valid HogQL identifiers that
# won't collide with reserved keywords or contain problematic characters.
_SAFE_IDENTIFIER = st.from_regex(r"[a-z_][a-z0-9_]{0,15}", fullmatch=True).filter(
    lambda s: s not in ("true", "false", "null", "team_id", "not", "and", "or", "in", "is", "like", "ilike", "between")
)

# String constants: NUL excluded (lossy parse via \0 → ""), surrogates
# excluded (not valid UTF-8, rejected by the C++ parser backend).
_SAFE_STRING = st.text(
    alphabet=st.characters(
        blacklist_characters="\0",
        blacklist_categories=["Cs"],
    ),
    min_size=0,
    max_size=50,
)

_SAFE_INTEGER = st.integers(min_value=-(10**15), max_value=10**15)

_SAFE_FLOAT = st.floats(allow_nan=False, allow_infinity=False, min_value=-(10**15), max_value=10**15).filter(
    lambda f: f == 0.0 or (abs(f) > 1e-10 and abs(f) < 1e15)
)

# A subset of functions that are known to the HogQL printer/parser and accept
# a small fixed number of arguments. We avoid functions that trigger special
# behaviour in the printer (timezone injection, type checks, etc).
_SIMPLE_FUNCTIONS: list[tuple[str, int]] = [
    ("toString", 1),
    ("toInt", 1),
    ("length", 1),
    ("lower", 1),
    ("upper", 1),
    ("reverse", 1),
    ("abs", 1),
    ("coalesce", 2),
    ("concat", 2),
    ("substring", 3),
    ("if", 3),
    ("greatest", 2),
    ("least", 2),
    ("replaceOne", 3),
    ("trim", 1),
    ("trimLeft", 1),
    ("trimRight", 1),
    ("position", 2),
    ("empty", 1),
    ("notEmpty", 1),
    ("isNull", 1),
    ("isNotNull", 1),
    ("toFloat", 1),
    ("multiIf", 3),
    ("floor", 1),
    ("ceil", 1),
    ("round", 1),
    ("left", 2),
    ("right", 2),
]

# Functions that take a lambda as the first argument and a list/array as the
# second. Used to test lambda round-tripping.
_LAMBDA_FUNCTIONS: list[str] = [
    "arrayMap",
    "arrayFilter",
    "arrayExists",
]

# Comparison ops that the HogQL printer can round-trip.
# Cohort ops and global ops require special context; regex ops
# get rewritten to match()/concat() calls that don't round-trip
# cleanly back to CompareOperation nodes.
_ROUNDTRIP_COMPARE_OPS = [
    ast.CompareOperationOp.Eq,
    ast.CompareOperationOp.NotEq,
    ast.CompareOperationOp.Gt,
    ast.CompareOperationOp.GtEq,
    ast.CompareOperationOp.Lt,
    ast.CompareOperationOp.LtEq,
    ast.CompareOperationOp.Like,
    ast.CompareOperationOp.ILike,
    ast.CompareOperationOp.NotLike,
    ast.CompareOperationOp.NotILike,
    ast.CompareOperationOp.In,
    ast.CompareOperationOp.NotIn,
]


def _constant_strategy() -> st.SearchStrategy[ast.Constant]:
    return st.one_of(
        _SAFE_STRING.map(lambda s: ast.Constant(value=s)),
        _SAFE_INTEGER.map(lambda n: ast.Constant(value=n)),
        _SAFE_FLOAT.map(lambda f: ast.Constant(value=f)),
        st.just(ast.Constant(value=True)),
        st.just(ast.Constant(value=False)),
        st.just(ast.Constant(value=None)),
    )


def _field_strategy() -> st.SearchStrategy[ast.Field]:
    return st.lists(_SAFE_IDENTIFIER, min_size=1, max_size=3).map(lambda chain: ast.Field(chain=list[str | int](chain)))


def _make_call(name_nargs: tuple[str, int], args: list[ast.Expr]) -> ast.Call:
    return ast.Call(name=name_nargs[0], args=args)


def _make_lambda_call(fn_name: str, lambda_arg: str, body: ast.Expr, array: ast.Expr) -> ast.Call:
    return ast.Call(
        name=fn_name,
        args=[ast.Lambda(args=[lambda_arg], expr=body), array],
    )


# Recursive expression strategy — depth is bounded by Hypothesis's
# ``max_leaves`` on ``st.recursive``.
def _expr_strategy() -> st.SearchStrategy[ast.Expr]:
    base: st.SearchStrategy[ast.Expr] = st.one_of(_constant_strategy(), _field_strategy())

    def extend(children: st.SearchStrategy[ast.Expr]) -> st.SearchStrategy[ast.Expr]:
        arith = st.builds(
            ast.ArithmeticOperation,
            left=children,
            right=children,
            op=st.sampled_from(list(ast.ArithmeticOperationOp)),
        )

        compare = st.builds(
            ast.CompareOperation,
            left=children,
            right=children,
            op=st.sampled_from(_ROUNDTRIP_COMPARE_OPS),
        )

        and_expr = st.lists(children, min_size=2, max_size=4).map(lambda exprs: ast.And(exprs=exprs))
        or_expr = st.lists(children, min_size=2, max_size=4).map(lambda exprs: ast.Or(exprs=exprs))
        not_expr = children.map(lambda e: ast.Not(expr=e))

        array = st.lists(children, min_size=0, max_size=4).map(lambda exprs: ast.Array(exprs=exprs))
        tuple_expr = st.lists(children, min_size=1, max_size=4).map(lambda exprs: ast.Tuple(exprs=exprs))

        def _call_strategy(name_nargs: tuple[str, int]) -> st.SearchStrategy[ast.Call]:
            return st.lists(children, min_size=name_nargs[1], max_size=name_nargs[1]).map(
                lambda args: _make_call(name_nargs, args)
            )

        call = st.sampled_from(_SIMPLE_FUNCTIONS).flatmap(_call_strategy)

        alias = st.builds(
            ast.Alias,
            alias=_SAFE_IDENTIFIER,
            expr=children,
        )

        between = st.builds(
            ast.BetweenExpr,
            expr=children,
            low=children,
            high=children,
            negated=st.booleans(),
        )

        # Array access: expr[expr]
        array_access = st.builds(
            ast.ArrayAccess,
            array=children,
            property=children,
        )

        # IS [NOT] DISTINCT FROM
        is_distinct_from = st.builds(
            ast.IsDistinctFrom,
            left=children,
            right=children,
            negated=st.booleans(),
        )

        # Lambda inside array higher-order functions: arrayMap(x -> body, arr)
        lambda_call = st.builds(
            _make_lambda_call,
            fn_name=st.sampled_from(_LAMBDA_FUNCTIONS),
            lambda_arg=_SAFE_IDENTIFIER,
            body=children,
            array=children,
        )

        return st.one_of(
            arith,
            compare,
            and_expr,
            or_expr,
            not_expr,
            array,
            tuple_expr,
            call,
            alias,
            between,
            array_access,
            is_distinct_from,
            lambda_call,
        )

    return st.recursive(base, extend, max_leaves=20)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_hogql(node: ast.Expr) -> str:
    """Print an AST node to a HogQL string using a minimal context."""
    return node.to_hogql()


def _parse_both_backends(hogql_string: str) -> tuple[ast.Expr | None, ast.Expr | None]:
    """Parse with both backends, returning (python_ast, cpp_ast).

    Returns None for a backend if parsing fails.
    """
    py_ast: ast.Expr | None = None
    cpp_ast: ast.Expr | None = None
    try:
        py_ast = parse_expr(hogql_string, backend="python")
    except BaseHogQLError:
        pass
    try:
        cpp_ast = parse_expr(hogql_string, backend="cpp-json")
    except BaseHogQLError:
        pass
    return py_ast, cpp_ast


def _roundtrip_check(expr: ast.Expr) -> None:
    """Shared logic: print → parse → print and verify idempotency."""
    try:
        printed1 = _print_hogql(expr)
    except BaseHogQLError:
        assume(False)
        return  # type: ignore[unreachable]

    try:
        parsed = parse_expr(printed1)
    except BaseHogQLError:
        assume(False)
        return  # type: ignore[unreachable]

    printed2 = _print_hogql(parsed)
    assert printed1 == printed2, f"Round-trip mismatch:\n  pass 1: {printed1!r}\n  pass 2: {printed2!r}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExprRoundTrip:
    """Print → parse → print yields the same HogQL string."""

    @given(expr=_expr_strategy())
    @settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_print_parse_print_idempotent(self, expr: ast.Expr) -> None:
        _roundtrip_check(expr)


class TestParserBackendEquivalence:
    """Both parser backends produce equivalent ASTs for generated HogQL strings."""

    @given(expr=_expr_strategy())
    @settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_python_and_cpp_backends_agree(self, expr: ast.Expr) -> None:
        try:
            hogql_string = _print_hogql(expr)
        except BaseHogQLError:
            assume(False)
            return  # type: ignore[unreachable]

        py_ast, cpp_ast = _parse_both_backends(hogql_string)

        if py_ast is None and cpp_ast is None:
            assume(False)
            return  # type: ignore[unreachable]

        # If one succeeds and the other fails, that's a bug
        assert (py_ast is None) == (cpp_ast is None), (
            f"Backend disagreement on parsability of: {hogql_string!r}\n"
            f"  Python: {'failed' if py_ast is None else 'ok'}\n"
            f"  C++:    {'failed' if cpp_ast is None else 'ok'}"
        )

        assert py_ast is not None and cpp_ast is not None

        # Compare by printing both back to HogQL — this normalises away
        # any minor structural differences (like start/end positions).
        py_printed = _print_hogql(py_ast)
        cpp_printed = _print_hogql(cpp_ast)

        assert py_printed == cpp_printed, (
            f"Backend outputs differ for: {hogql_string!r}\n"
            f"  Python backend: {py_printed!r}\n"
            f"  C++ backend:    {cpp_printed!r}"
        )


class TestConstantRoundTrip:
    """Focused round-trip tests for constant values (strings, numbers, booleans, null)."""

    @given(s=_SAFE_STRING)
    @settings(max_examples=500)
    def test_string_constant_roundtrip(self, s: str) -> None:
        node = ast.Constant(value=s)
        printed = _print_hogql(node)
        parsed = parse_expr(printed)
        assert _print_hogql(parsed) == printed

    @given(n=_SAFE_INTEGER)
    def test_integer_constant_roundtrip(self, n: int) -> None:
        node = ast.Constant(value=n)
        printed = _print_hogql(node)
        parsed = parse_expr(printed)
        assert _print_hogql(parsed) == printed

    @given(f=_SAFE_FLOAT)
    def test_float_constant_roundtrip(self, f: float) -> None:
        node = ast.Constant(value=f)
        printed = _print_hogql(node)
        parsed = parse_expr(printed)
        reprinted = _print_hogql(parsed)
        # Floats may lose precision through string representation,
        # so we compare the parsed float values rather than exact strings
        if printed == reprinted:
            return
        # Both should parse to the same numeric value
        parsed_original = float(printed)
        parsed_roundtrip = float(reprinted)
        if f == 0.0:
            assert parsed_roundtrip == 0.0
        else:
            assert math.isclose(parsed_original, parsed_roundtrip, rel_tol=1e-10)

    @pytest.mark.parametrize("value", [True, False, None])
    def test_literal_roundtrip(self, value: Any) -> None:
        node = ast.Constant(value=value)
        printed = _print_hogql(node)
        parsed = parse_expr(printed)
        assert _print_hogql(parsed) == printed


class TestFieldRoundTrip:
    """Focused round-trip tests for field references."""

    @given(chain=st.lists(_SAFE_IDENTIFIER, min_size=1, max_size=3))
    def test_field_roundtrip(self, chain: list[str]) -> None:
        node = ast.Field(chain=list[str | int](chain))
        printed = _print_hogql(node)
        parsed = parse_expr(printed)
        assert _print_hogql(parsed) == printed


class TestArrayAccessRoundTrip:
    """Focused round-trip tests for array access expressions."""

    @given(
        array_chain=st.lists(_SAFE_IDENTIFIER, min_size=1, max_size=2),
        index=st.integers(min_value=1, max_value=100),
    )
    def test_field_array_access_roundtrip(self, array_chain: list[str], index: int) -> None:
        node = ast.ArrayAccess(
            array=ast.Field(chain=list[str | int](array_chain)),
            property=ast.Constant(value=index),
        )
        _roundtrip_check(node)


class TestIsDistinctFromRoundTrip:
    """Focused round-trip tests for IS [NOT] DISTINCT FROM."""

    @given(
        left=st.lists(_SAFE_IDENTIFIER, min_size=1, max_size=2),
        right=st.lists(_SAFE_IDENTIFIER, min_size=1, max_size=2),
        negated=st.booleans(),
    )
    def test_is_distinct_from_roundtrip(self, left: list[str], right: list[str], negated: bool) -> None:
        node = ast.IsDistinctFrom(
            left=ast.Field(chain=list[str | int](left)),
            right=ast.Field(chain=list[str | int](right)),
            negated=negated,
        )
        _roundtrip_check(node)


class TestInfixAliasParenthesization:
    """Regression tests: aliases as operands of infix keyword operators must be
    parenthesized by the printer so that AS doesn't steal precedence."""

    @pytest.mark.parametrize(
        "node",
        [
            pytest.param(
                ast.IsDistinctFrom(
                    left=ast.Constant(value=""),
                    right=ast.Alias(alias="x", expr=ast.Constant(value=True)),
                ),
                id="is_distinct_from_with_alias_rhs",
            ),
            pytest.param(
                ast.IsDistinctFrom(
                    left=ast.Alias(alias="x", expr=ast.Field(chain=["a"])),
                    right=ast.Constant(value=1),
                    negated=True,
                ),
                id="is_not_distinct_from_with_alias_lhs",
            ),
            pytest.param(
                ast.BetweenExpr(
                    expr=ast.Alias(alias="x", expr=ast.Field(chain=["a"])),
                    low=ast.Constant(value=1),
                    high=ast.Constant(value=10),
                ),
                id="between_with_alias_expr",
            ),
            pytest.param(
                ast.BetweenExpr(
                    expr=ast.Constant(value=5),
                    low=ast.Alias(alias="lo", expr=ast.Constant(value=1)),
                    high=ast.Alias(alias="hi", expr=ast.Constant(value=10)),
                ),
                id="between_with_alias_bounds",
            ),
        ],
    )
    def test_alias_in_infix_operator_roundtrips(self, node: ast.Expr) -> None:
        _roundtrip_check(node)


class TestLambdaRoundTrip:
    """Focused round-trip tests for lambda expressions within array functions."""

    @given(
        fn_name=st.sampled_from(_LAMBDA_FUNCTIONS),
        arg_name=_SAFE_IDENTIFIER,
        body_field=_SAFE_IDENTIFIER,
    )
    def test_lambda_in_array_function_roundtrip(self, fn_name: str, arg_name: str, body_field: str) -> None:
        node = ast.Call(
            name=fn_name,
            args=[
                ast.Lambda(args=[arg_name], expr=ast.Field(chain=[arg_name])),
                ast.Array(exprs=[ast.Constant(value=1), ast.Constant(value=2)]),
            ],
        )
        _roundtrip_check(node)
