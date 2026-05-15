"""Grammar-driven property-based tests for the HogQL parser.

Strategies are auto-generated from ``HogQLParser.g4`` /
``HogQLLexer.common.g4`` by ``bin/build-hogql-grammar-strategies.py``
and imported from ``_generated_grammar_strategies``. Variable-content
tokens are hand-written once in ``_grammar_token_strategies``.

The stylistic-jiggle layer (case-flipping, whitespace, comment
insertion) wraps grammar-generated text to cover lexical axes that are
awkward to encode as grammar productions — exactly where the two
backends are most likely to disagree.

Contract — **bidirectional parity** between the two backends:

    1. If both accept, ``clear_locations(a) == clear_locations(b)``.
    2. If both reject, the example is discarded.
    3. If one accepts and the other rejects → test fails: the two
       backends must agree on the accepted grammar surface.

The comparison is between the Python parser (the original reference
implementation, an ANTLR4-generated parser + a parse-tree visitor in
``HogQLParseTreeConverter``) and the C++ parser (a hand-ported visitor
over the same ANTLR4-generated parser, exposed to Python via the
``hogql_parser`` wheel). Both consume the same ``.g4`` grammar; AST
divergences here are visitor-implementation bugs in one of them.

Opt-in via ``RUN_PBT=1`` — the grind is slow and intended for offline
audit runs rather than every CI build.
"""

from __future__ import annotations

import os
import re
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
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.test._generated_grammar_strategies import expr_strategy, select_strategy
from posthog.hogql.visitor import clear_locations

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_PBT"),
    reason="grammar PBT is slow and primarily for offline runs; set RUN_PBT=1 to opt in",
)


# ---------------------------------------------------------------------------
# Stylistic-jiggle layer
# ---------------------------------------------------------------------------
#
# Applied as a post-pass on grammar-generated text. Covers lexical axes
# (case, whitespace, comment placement) that are awkward to express
# inside grammar productions.

_KEYWORDS_FOR_CASE_VARIATION = (
    "SELECT",
    "DISTINCT",
    "FROM",
    "WHERE",
    "GROUP",
    "BY",
    "HAVING",
    "ORDER",
    "LIMIT",
    "OFFSET",
    "ASC",
    "DESC",
    "AND",
    "OR",
    "NOT",
    "LIKE",
    "ILIKE",
    "AS",
    "WITH",
    "JOIN",
    "ON",
    "USING",
    "UNION",
    "INTERSECT",
    "EXCEPT",
    "ALL",
    "ANY",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "IN",
    "IS",
    "BETWEEN",
    "INTERVAL",
    "OVER",
    "PARTITION",
    "WINDOW",
    "FILTER",
)


@st.composite
def _case_jiggle(draw: Any, query: str) -> str:
    """Randomise keyword case (preserves the rest of the string)."""

    def _flip(word: str) -> str:
        choice = draw(st.sampled_from(["upper", "lower", "title", "as-is"]))
        if choice == "upper":
            return word.upper()
        if choice == "lower":
            return word.lower()
        if choice == "title":
            return word.capitalize()
        return word

    out: list[str] = []
    for token in query.split(" "):
        stripped = token.strip(",()")
        if stripped.upper() in _KEYWORDS_FOR_CASE_VARIATION:
            out.append(token.replace(stripped, _flip(stripped)))
        else:
            out.append(token)
    return " ".join(out)


@st.composite
def _whitespace_jiggle(draw: Any, query: str) -> str:
    """Replace single spaces with whitespace variants — spaces, tabs,
    newlines, multi-space runs. Skipped inside string literals."""
    out: list[str] = []
    in_string = False
    for ch in query:
        if ch == "'":
            in_string = not in_string
            out.append(ch)
            continue
        if ch == " " and not in_string:
            ws = draw(st.sampled_from([" ", "  ", "\t", "\n", " \n ", " "]))
            out.append(ws)
        else:
            out.append(ch)
    return "".join(out)


@st.composite
def _comment_jiggle(draw: Any, query: str) -> str:
    """Insert block / line comments before clause-keyword tokens.
    Skipped inside string literals."""
    out: list[str] = []
    in_string = False
    for tok in query.split(" "):
        if (
            not in_string
            and tok.upper() in _KEYWORDS_FOR_CASE_VARIATION
            and draw(st.integers(min_value=0, max_value=4)) == 0
        ):
            comment = draw(
                st.sampled_from(
                    [
                        "/* note */",
                        "/**/",
                        "/* multi\nline */",
                    ]
                )
            )
            out.append(comment)
        if tok.count("'") % 2 == 1:
            in_string = not in_string
        out.append(tok)
    return " ".join(out)


def _apply_jiggle(query: str) -> st.SearchStrategy[str]:
    """Compose the three jiggles. Each is independently optional."""

    @st.composite
    def _inner(draw: Any) -> str:
        result = query
        if draw(st.booleans()):
            result = draw(_case_jiggle(result))
        if draw(st.booleans()):
            result = draw(_whitespace_jiggle(result))
        if draw(st.booleans()):
            result = draw(_comment_jiggle(result))
        return result

    return _inner()


# ---------------------------------------------------------------------------
# Differential parsing harness
# ---------------------------------------------------------------------------

# The two backends under comparison. Both implement the same `.g4`
# grammar — the Python one via an ANTLR4-generated parser + a
# HogQLParseTreeConverter visitor, the C++ one via a hand-ported
# visitor exposed through the `hogql_parser` wheel.
_BACKEND_A = "python"
_BACKEND_B = "cpp-json"


def _try_parse(query: str, rule: str, backend: str) -> tuple[bool, ast.AST | None]:
    """Return ``(accepted, ast_or_none)``. Errors of any kind count as
    rejection — visitor-level "Unsupported rule" failures behave the
    same as parse failures from the test's point of view."""
    parser_fn = parse_expr if rule == "expr" else parse_select
    try:
        node = parser_fn(query, backend=backend)  # type: ignore[arg-type]
        return True, clear_locations(node)
    except BaseHogQLError:
        return False, None
    except Exception:
        return False, None


# Substrings that exercise a documented cpp-json visitor bug — the
# Python AST is correct, cpp's is not. The PBT discards examples that
# would trip these so the grind isn't stuck on already-known cpp bugs.
# When a fix lands cpp-side, drop the corresponding entry.
_CPP_KNOWN_BUG_PATTERNS = (
    re.compile(r"\+\s*inf\b", re.IGNORECASE),  # `+inf` mis-mapped to NaN
    # `infinity` lexes as Kw::Inf but the visitor's special-number
    # branch only matches the exact text `inf`/`-inf`, so `infinity`,
    # `+infinity`, and `-infinity` all fall through to NaN.
    re.compile(r"\binfinity\b", re.IGNORECASE),
    re.compile(r"\b0x[0-9a-f]+\b", re.IGNORECASE),  # hex literal mis-parsed to 0
    re.compile(r"\b0o[0-7]+\b", re.IGNORECASE),  # octal literal mis-parsed
)


def _assert_backends_agree(query: str, rule: str) -> None:
    """Bidirectional contract: both backends must accept the same
    grammar surface, and on accepted inputs the ASTs must match
    (post-`clear_locations`).

    Documented cpp-bug-trigger patterns are discarded so the PBT can
    keep grinding past already-known visitor divergences.
    """
    if any(p.search(query) for p in _CPP_KNOWN_BUG_PATTERNS):
        assume(False)
        return

    a_ok, a_ast = _try_parse(query, rule, _BACKEND_A)
    b_ok, b_ast = _try_parse(query, rule, _BACKEND_B)

    if not a_ok and not b_ok:
        # Both rejected — uninteresting; the grammar generator can
        # over-produce strings that neither visitor accepts.
        assume(False)
        return

    if a_ok != b_ok:
        accepted, rejected = (_BACKEND_A, _BACKEND_B) if a_ok else (_BACKEND_B, _BACKEND_A)
        raise AssertionError(f"{accepted!r} accepted but {rejected!r} rejected ({rule!r}): {query!r}")

    if a_ast != b_ast:
        raise AssertionError(
            f"AST mismatch for {rule!r}: {query!r}\n  {_BACKEND_A}:  {a_ast!r}\n  {_BACKEND_B}: {b_ast!r}"
        )


# Shared Hypothesis settings. Strategies overgenerate (semantic-visitor
# rejection drops a sizable fraction); ``filter_too_much`` is silenced.
_PBT_SETTINGS = settings(
    max_examples=int(os.environ.get("GRAMMAR_PBT_EXAMPLES", "1000")),
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
        HealthCheck.data_too_large,
    ],
)

# Wall-clock timeout per test (via pytest-timeout, which is already a
# project dependency). Hypothesis shrinking on a deep AST tree can run
# for many minutes; cap each test so a stuck shrink loop doesn't block
# the loop. Override with ``GRAMMAR_PBT_TIMEOUT=600`` for longer runs.
_PBT_TIMEOUT_SECONDS = int(os.environ.get("GRAMMAR_PBT_TIMEOUT", "300"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(_PBT_TIMEOUT_SECONDS)
class TestExpressionGrammarPBT:
    """``parse_expr`` differential parity over the full ``columnExpr``
    grammar surface — auto-generated from .g4."""

    @given(query=expr_strategy())
    @_PBT_SETTINGS
    def test_expression_backends_agree(self, query: str) -> None:
        _assert_backends_agree(query, rule="expr")

    @given(query=expr_strategy().flatmap(_apply_jiggle))
    @_PBT_SETTINGS
    def test_expression_backends_agree_with_jiggle(self, query: str) -> None:
        _assert_backends_agree(query, rule="expr")


@pytest.mark.timeout(_PBT_TIMEOUT_SECONDS)
class TestSelectGrammarPBT:
    """``parse_select`` differential parity over the full ``select``
    grammar surface — auto-generated from .g4."""

    @given(query=select_strategy())
    @_PBT_SETTINGS
    def test_select_backends_agree(self, query: str) -> None:
        _assert_backends_agree(query, rule="select")

    @given(query=select_strategy().flatmap(_apply_jiggle))
    @_PBT_SETTINGS
    def test_select_backends_agree_with_jiggle(self, query: str) -> None:
        _assert_backends_agree(query, rule="select")
