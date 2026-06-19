"""Auto-generated grammar strategies for the HogQL parser PBT.

DO NOT EDIT. Regenerate via::

    python -m posthog.hogql.scripts.build_grammar_strategies

The generator reads ``posthog/hogql/grammar/HogQLParser.g4`` and
``posthog/hogql/grammar/HogQLLexer.common.g4`` and emits this file.

Each rule is a depth-parameterised strategy factory:
``foo_strategy(depth=_DEFAULT_DEPTH)`` returns a ``SearchStrategy[str]``.
Recursive sub-rule draws decrement depth; at depth 0 the strategy
prefers leaf alternatives so generation bottoms out. Strategies are
memoised per-depth via ``functools.cache`` so Hypothesis sees stable
identity across draws (matters for shrinking).
"""

from __future__ import annotations

import functools
from typing import Any

from hypothesis import strategies as st

from posthog.hogql.test._grammar_token_strategies import (
    binary_literal_token,
    decimal_literal_token,
    floating_literal_token,
    full_string_escape_trigger_token,
    full_string_text_token,
    hexadecimal_literal_token,
    hogqlx_text_token,
    identifier_token,
    octal_literal_token,
    octal_prefix_literal_token,
    quote_single_template_full_token,
    quote_single_template_token,
    quoted_identifier_token,
    string_escape_trigger_token,
    string_literal_token,
    string_text_token,
)

_DEFAULT_DEPTH = 5
_MAX_REPEAT = 4  # cap for `*` / `+` quantifiers (per occurrence)
_MAX_LR_CHAIN = 4  # cap for chained Pratt-style suffixes (per LR rule)

# Probability an optional ``?``-quantified element is included. 50/50
# produces unrealistically clause-rich SELECTs (a typical SELECT has 25
# optional clauses; even 30% inclusion gives ~8 clauses per query, more
# than enough). Tune-able to stress the parser harder.
# 1-in-N inclusion rate for ``?``-quantified elements. With SELECT's
# ~20 optional clauses, 1/8 = 12.5% gives an average of ~2.5 clauses
# per query — small enough that visitor-NotImplementedError productions
# in any one clause don't blow up acceptance for the whole query, but
# big enough that every optional gets exercised across a 1k-example run.
_OPT_INCLUSION_DEN = 8

# 1-in-N inclusion rate for "soft-excluded" productions — alternatives
# that exist in the grammar but tend to be visitor-rejected by cpp.
# Firing them at a low rate keeps parity coverage without tanking
# acceptance. With ~10 columnExpr nodes per SELECT, a rate of 1/30
# yields ~70% chance the SELECT contains no soft alt.
# Interpolated from the generator's module-level constant; both
# alt-level and element-level soft-firing emit ``_include_soft(draw)``
# below, so the rate lives in exactly one place at runtime.
_SOFT_FREQ_DENOM = 30


def _dec(depth: int) -> int:
    """Decrement depth but clamp at 0."""
    return depth - 1 if depth > 0 else 0


def _include_optional(draw: Any) -> bool:
    """Whether to include a ``?``-quantified element. Biased low so
    optional-heavy rules like ``selectStmt`` don't produce 25-clause
    monsters."""
    return draw(st.integers(min_value=0, max_value=_OPT_INCLUSION_DEN - 1)) == 0


def _include_soft(draw: Any) -> bool:
    """Whether to include a soft-excluded production (visitor-rejected
    by cpp; rare-fire to keep parity coverage without tanking
    acceptance). The rate is per-occurrence; trees with many soft slots
    compound, so this needs to be low enough that a typical query stays
    free of soft alts. With ~10 columnExpr nodes per SELECT, a rate of
    1/30 yields ~70% chance the SELECT contains no soft alt."""
    return draw(st.integers(min_value=0, max_value=_SOFT_FREQ_DENOM - 1)) == 0


@functools.cache
def program_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(draw(declaration_strategy(_dec(depth))))
        parts.append("")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def declaration_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append(draw(varDecl_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(statement_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def expression_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def varDecl_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("let")
        parts.append(draw(identifier_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(":=")
            parts.append(draw(expression_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def identifierList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(nestedIdentifier_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(nestedIdentifier_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(",")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def statement_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=10))
        if alt_idx == 0:
            parts = []
            parts.append(draw(returnStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(throwStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append(draw(tryCatchStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append(draw(ifStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 4:
            parts = []
            parts.append(draw(whileStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 5:
            parts = []
            parts.append(draw(forInStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 6:
            parts = []
            parts.append(draw(forStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 7:
            parts = []
            parts.append(draw(funcStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 8:
            parts = []
            parts.append(draw(block_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 9:
            parts = []
            parts.append(draw(exprStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 10:
            parts = []
            parts.append(draw(emptyStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def returnStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("return")
        if _include_optional(draw):
            parts.append(draw(expression_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(";")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def throwStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("throw")
        parts.append(draw(expression_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(";")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def catchBlock_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("catch")
        if _include_optional(draw):
            parts.append("(")
            parts.append(draw(identifier_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append(":")
                parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(")")
        parts.append(draw(block_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def tryCatchStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("try")
        parts.append(draw(block_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(draw(catchBlock_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append("finally")
            parts.append(draw(block_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def ifStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("if")
        parts.append("(")
        parts.append(draw(expression_strategy(_dec(depth))))
        parts.append(")")
        parts.append(draw(statement_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append("else")
            parts.append(draw(statement_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def whileStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("while")
        parts.append("(")
        parts.append(draw(expression_strategy(_dec(depth))))
        parts.append(")")
        parts.append(draw(statement_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(";")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def forStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("for")
        parts.append("(")
        if _include_optional(draw):
            group_idx = draw(st.integers(min_value=0, max_value=2))
            if group_idx == 0:
                parts.append(draw(varDecl_strategy(_dec(depth))))
            if group_idx == 1:
                parts.append(draw(varAssignment_strategy(_dec(depth))))
            if group_idx == 2:
                parts.append(draw(expression_strategy(_dec(depth))))
        parts.append(";")
        if _include_optional(draw):
            parts.append(draw(expression_strategy(_dec(depth))))
        parts.append(";")
        if _include_optional(draw):
            group_idx = draw(st.integers(min_value=0, max_value=2))
            if group_idx == 0:
                parts.append(draw(varDecl_strategy(_dec(depth))))
            if group_idx == 1:
                parts.append(draw(varAssignment_strategy(_dec(depth))))
            if group_idx == 2:
                parts.append(draw(expression_strategy(_dec(depth))))
        parts.append(")")
        parts.append(draw(statement_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(";")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def forInStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("for")
        parts.append("(")
        parts.append("let")
        parts.append(draw(identifier_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(",")
            parts.append(draw(identifier_strategy(_dec(depth))))
        parts.append("in")
        parts.append(draw(expression_strategy(_dec(depth))))
        parts.append(")")
        parts.append(draw(statement_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(";")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def funcStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        group_idx = draw(st.integers(min_value=0, max_value=1))
        if group_idx == 0:
            parts.append("fn")
        if group_idx == 1:
            parts.append("fun")
        parts.append(draw(identifier_strategy(_dec(depth))))
        parts.append("(")
        if _include_optional(draw):
            parts.append(draw(identifierList_strategy(_dec(depth))))
        parts.append(")")
        parts.append(draw(block_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def varAssignment_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(expression_strategy(_dec(depth))))
        parts.append(":=")
        parts.append(draw(expression_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def exprStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(expression_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(":=")
            parts.append(draw(expression_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(";")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def emptyStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(";")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def block_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("{")
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(draw(declaration_strategy(_dec(depth))))
        parts.append("}")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def kvPair_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(expression_strategy(_dec(depth))))
        parts.append(":")
        parts.append(draw(expression_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def kvPairList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(kvPair_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(kvPair_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(",")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def select_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        group_idx = draw(st.integers(min_value=0, max_value=2))
        if group_idx == 0:
            parts.append(draw(selectSetStmt_strategy(_dec(depth))))
        if group_idx == 1:
            parts.append(draw(selectStmt_strategy(_dec(depth))))
        if group_idx == 2:
            parts.append(draw(hogqlxTagElement_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(";")
        parts.append("")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def selectStmtWithParens_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=3))
        if alt_idx == 0:
            parts = []
            parts.append(draw(selectStmt_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(withClause_strategy(_dec(depth))))
            parts.append("(")
            parts.append(draw(selectSetStmt_strategy(_dec(depth))))
            parts.append(")")
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("(")
            parts.append(draw(selectSetStmt_strategy(_dec(depth))))
            parts.append(")")
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append(draw(placeholder_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def subsequentSelectSetClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        group_idx = draw(st.integers(min_value=0, max_value=7))
        if group_idx == 0:
            parts.append("except")
            parts.append("all")
            if _include_optional(draw):
                parts.append("by")
                parts.append("name")
        if group_idx == 1:
            parts.append("except")
            if _include_optional(draw):
                parts.append("by")
                parts.append("name")
        if group_idx == 2:
            parts.append("union")
            parts.append("all")
            if _include_optional(draw):
                parts.append("by")
                parts.append("name")
        if group_idx == 3:
            parts.append("union")
            parts.append("distinct")
            if _include_optional(draw):
                parts.append("by")
                parts.append("name")
        if group_idx == 4:
            parts.append("union")
            if _include_optional(draw):
                parts.append("by")
                parts.append("name")
        if group_idx == 5:
            parts.append("intersect")
            parts.append("all")
            if _include_optional(draw):
                parts.append("by")
                parts.append("name")
        if group_idx == 6:
            parts.append("intersect")
            parts.append("distinct")
            if _include_optional(draw):
                parts.append("by")
                parts.append("name")
        if group_idx == 7:
            parts.append("intersect")
            if _include_optional(draw):
                parts.append("by")
                parts.append("name")
        parts.append(draw(selectStmtWithParens_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def selectSetStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(selectStmtWithParens_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(draw(subsequentSelectSetClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(orderByClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(limitAndOffsetClauseOptional_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def limitAndOffsetClauseOptional_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=2))
        if alt_idx == 0:
            parts = []
            parts.append("limit")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("%")
            if _include_optional(draw):
                parts.append(",")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("with")
                parts.append("ties")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("limit")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("%")
            if _include_optional(draw):
                parts.append("with")
                parts.append("ties")
            parts.append("offset")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("offset")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def selectStmt_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if _include_optional(draw):
            parts.append(draw(withClause_strategy(_dec(depth))))
        parts.append("select")
        if _include_optional(draw):
            parts.append("distinct")
        if _include_optional(draw):
            parts.append(draw(topClause_strategy(_dec(depth))))
        parts.append(draw(selectColumnExprListBeforeFrom_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(fromClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(arrayJoinClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(prewhereClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(whereClause_strategy(_dec(depth))))
        if _include_optional(draw):
            if _include_optional(draw):
                parts.append("using")
            parts.append(draw(sampleClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(groupByClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append("with")
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append("cube")
            if group_idx == 1:
                parts.append("rollup")
        if _include_optional(draw):
            parts.append("with")
            parts.append("totals")
        if _include_optional(draw):
            parts.append(draw(havingClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(qualifyClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append("using")
            parts.append(draw(sampleClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(windowClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(orderByClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(limitByClause_strategy(_dec(depth))))
        if _include_optional(draw):
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append(draw(limitAndOffsetClause_strategy(_dec(depth))))
            if group_idx == 1:
                parts.append(draw(offsetOnlyClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(settingsClause_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def withClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("with")
        if _include_optional(draw):
            parts.append("recursive")
        parts.append(draw(withExprList_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def topClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("top")
        parts.append(draw(decimal_literal_token))
        if _include_optional(draw):
            parts.append("with")
            parts.append("ties")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def fromClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("from")
        parts.append(draw(joinExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def arrayJoinClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if _include_optional(draw):
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append("left")
            if group_idx == 1:
                parts.append("inner")
        parts.append("array")
        parts.append("join")
        parts.append(draw(columnExprList_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def windowClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("window")
        parts.append(draw(identifier_strategy(_dec(depth))))
        parts.append("as")
        parts.append("(")
        parts.append(draw(windowExpr_strategy(_dec(depth))))
        parts.append(")")
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("as")
            parts.append("(")
            parts.append(draw(windowExpr_strategy(_dec(depth))))
            parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def prewhereClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("prewhere")
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def whereClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("where")
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def groupByClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("group")
        parts.append("by")
        group_idx = draw(st.integers(min_value=0, max_value=3))
        if group_idx == 0:
            parts.append("all")
        if group_idx == 1:
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append("cube")
            if group_idx == 1:
                parts.append("rollup")
            parts.append("(")
            parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
        if group_idx == 2:
            parts.append("grouping")
            parts.append("sets")
            parts.append("(")
            parts.append(draw(groupingSetList_strategy(_dec(depth))))
            parts.append(")")
        if group_idx == 3:
            parts.append(draw(columnExprList_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def groupingSetList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(groupingSet_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(groupingSet_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def groupingSet_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("(")
        if _include_optional(draw):
            parts.append(draw(columnExprList_strategy(_dec(depth))))
        parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def havingClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("having")
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def qualifyClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("qualify")
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def orderByClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("order")
        parts.append("by")
        parts.append(draw(orderExprList_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(interpolateClause_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def interpolateClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("interpolate")
        if _include_optional(draw):
            parts.append("(")
            parts.append(draw(interpolateExpr_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(",")
                parts.append(draw(interpolateExpr_strategy(_dec(depth))))
            parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def projectionOrderByClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("order")
        parts.append("by")
        parts.append(draw(columnExprList_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def limitByClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("limit")
        parts.append(draw(limitExpr_strategy(_dec(depth))))
        parts.append("by")
        parts.append(draw(columnExprList_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def limitAndOffsetClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append("limit")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("%")
            if _include_optional(draw):
                parts.append(",")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("with")
                parts.append("ties")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("limit")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("%")
            if _include_optional(draw):
                parts.append("with")
                parts.append("ties")
            parts.append("offset")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def offsetOnlyClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("offset")
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def settingsClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("settings")
        parts.append(draw(settingExprList_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def valuesClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("values")
        parts.append(draw(valuesRow_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(valuesRow_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def valuesRow_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("(")
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
        parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def joinExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    _has_suffixes = True

    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        seed_idx = draw(st.integers(min_value=0, max_value=1))
        seed = ""
        if seed_idx == 0:
            parts = []
            parts.append(draw(tableExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("final")
            if _include_optional(draw):
                parts.append(draw(sampleClause_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 1:
            parts = []
            parts.append("(")
            parts.append(draw(joinExpr_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if depth <= 0 or not _has_suffixes:
            return seed
        n_suffixes = draw(st.integers(min_value=0, max_value=_MAX_LR_CHAIN))
        for _ in range(n_suffixes):
            suffix_idx = draw(st.integers(min_value=0, max_value=4))
            if suffix_idx == 0:
                parts = []
                if _include_optional(draw):
                    parts.append("natural")
                if _include_optional(draw):
                    parts.append(draw(joinOp_strategy(_dec(depth))))
                parts.append("join")
                parts.append(draw(joinExpr_strategy(_dec(depth))))
                if _include_optional(draw):
                    parts.append(draw(joinConstraintClause_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 1:
                parts = []
                parts.append("positional")
                parts.append("join")
                parts.append(draw(joinExpr_strategy(_dec(depth))))
                if _include_optional(draw):
                    parts.append(draw(joinConstraintClause_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 2:
                parts = []
                parts.append(draw(joinOpCross_strategy(_dec(depth))))
                parts.append(draw(joinExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 3:
                parts = []
                parts.append("pivot")
                parts.append("(")
                parts.append(draw(columnExprList_strategy(_dec(depth))))
                parts.append(draw(pivotColumnList_strategy(_dec(depth))))
                if _include_optional(draw):
                    parts.append("group")
                    parts.append("by")
                    parts.append(draw(columnExprList_strategy(_dec(depth))))
                parts.append(")")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 4:
                parts = []
                parts.append("unpivot")
                if _include_optional(draw):
                    parts.append("include")
                    parts.append("nulls")
                parts.append("(")
                parts.append(draw(unpivotColumnList_strategy(_dec(depth))))
                parts.append(")")
                seed = seed + " " + " ".join(p for p in parts if p)
        return seed

    return gen()


@functools.cache
def joinOp_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=2))
        if alt_idx == 0:
            parts = []
            group_idx = draw(st.integers(min_value=0, max_value=5))
            if group_idx == 0:
                if _include_optional(draw):
                    group_idx = draw(st.integers(min_value=0, max_value=2))
                    if group_idx == 0:
                        parts.append("all")
                    if group_idx == 1:
                        parts.append("any")
                    if group_idx == 2:
                        parts.append("asof")
                parts.append("inner")
            if group_idx == 1:
                parts.append("inner")
                if _include_optional(draw):
                    group_idx = draw(st.integers(min_value=0, max_value=2))
                    if group_idx == 0:
                        parts.append("all")
                    if group_idx == 1:
                        parts.append("any")
                    if group_idx == 2:
                        parts.append("asof")
            if group_idx == 2:
                group_idx = draw(st.integers(min_value=0, max_value=2))
                if group_idx == 0:
                    parts.append("all")
                if group_idx == 1:
                    parts.append("any")
                if group_idx == 2:
                    parts.append("asof")
            if group_idx == 3:
                parts.append("anti")
            if group_idx == 4:
                parts.append("semi")
            if group_idx == 5:
                parts.append("asof")
                group_idx = draw(st.integers(min_value=0, max_value=1))
                if group_idx == 0:
                    parts.append("anti")
                if group_idx == 1:
                    parts.append("semi")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            group_idx = draw(st.integers(min_value=0, max_value=2))
            if group_idx == 0:
                if _include_optional(draw):
                    group_idx = draw(st.integers(min_value=0, max_value=4))
                    if group_idx == 0:
                        parts.append("semi")
                    if group_idx == 1:
                        parts.append("all")
                    if group_idx == 2:
                        parts.append("anti")
                    if group_idx == 3:
                        parts.append("any")
                    if group_idx == 4:
                        parts.append("asof")
                group_idx = draw(st.integers(min_value=0, max_value=1))
                if group_idx == 0:
                    parts.append("left")
                if group_idx == 1:
                    parts.append("right")
                if _include_optional(draw):
                    parts.append("outer")
            if group_idx == 1:
                group_idx = draw(st.integers(min_value=0, max_value=1))
                if group_idx == 0:
                    parts.append("left")
                if group_idx == 1:
                    parts.append("right")
                if _include_optional(draw):
                    parts.append("outer")
                if _include_optional(draw):
                    group_idx = draw(st.integers(min_value=0, max_value=4))
                    if group_idx == 0:
                        parts.append("semi")
                    if group_idx == 1:
                        parts.append("all")
                    if group_idx == 2:
                        parts.append("anti")
                    if group_idx == 3:
                        parts.append("any")
                    if group_idx == 4:
                        parts.append("asof")
            if group_idx == 2:
                parts.append("asof")
                group_idx = draw(st.integers(min_value=0, max_value=1))
                if group_idx == 0:
                    parts.append("anti")
                if group_idx == 1:
                    parts.append("semi")
                group_idx = draw(st.integers(min_value=0, max_value=1))
                if group_idx == 0:
                    parts.append("left")
                if group_idx == 1:
                    parts.append("right")
                if _include_optional(draw):
                    parts.append("outer")
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                if _include_optional(draw):
                    group_idx = draw(st.integers(min_value=0, max_value=2))
                    if group_idx == 0:
                        parts.append("all")
                    if group_idx == 1:
                        parts.append("any")
                    if group_idx == 2:
                        parts.append("asof")
                parts.append("full")
                if _include_optional(draw):
                    parts.append("outer")
            if group_idx == 1:
                parts.append("full")
                if _include_optional(draw):
                    parts.append("outer")
                if _include_optional(draw):
                    group_idx = draw(st.integers(min_value=0, max_value=2))
                    if group_idx == 0:
                        parts.append("all")
                    if group_idx == 1:
                        parts.append("any")
                    if group_idx == 2:
                        parts.append("asof")
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def joinOpCross_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append("cross")
            parts.append("join")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(",")
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def joinConstraintClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=2))
        if alt_idx == 0:
            parts = []
            parts.append("on")
            parts.append(draw(columnExprList_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("using")
            parts.append("(")
            parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("using")
            parts.append(draw(columnExprList_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def sampleClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("sample")
        parts.append(draw(ratioExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append("%")
        if _include_optional(draw):
            parts.append("offset")
            parts.append(draw(ratioExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append("(")
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def limitExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append(",")
            if group_idx == 1:
                parts.append("offset")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def orderExprList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(orderExpr_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(orderExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def orderExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            group_idx = draw(st.integers(min_value=0, max_value=2))
            if group_idx == 0:
                parts.append(draw(st.sampled_from(["asc", "ascending"])))
            if group_idx == 1:
                parts.append("descending")
            if group_idx == 2:
                parts.append("desc")
        if _include_optional(draw):
            parts.append("nulls")
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append("first")
            if group_idx == 1:
                parts.append("last")
        if _include_optional(draw):
            parts.append("collate")
            parts.append(draw(string_literal_token))
        if _include_optional(draw):
            parts.append(draw(withFillClause_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def withFillClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("with")
        parts.append("fill")
        if _include_optional(draw):
            parts.append("from")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append("to")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append("step")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def interpolateExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append("as")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def ratioExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append(draw(placeholder_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(numberLiteral_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("/")
                parts.append(draw(numberLiteral_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def settingExprList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(settingExpr_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(settingExpr_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def settingExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(identifier_strategy(_dec(depth))))
        parts.append("=")
        parts.append(draw(literal_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def windowExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if _include_optional(draw):
            parts.append(draw(winPartitionByClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(winOrderByClause_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(draw(winFrameClause_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def winPartitionByClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("partition")
        parts.append("by")
        parts.append(draw(columnExprList_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def winOrderByClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("order")
        parts.append("by")
        parts.append(draw(orderExprList_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def withinGroupClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("within")
        parts.append("group")
        parts.append("(")
        parts.append(draw(orderByClause_strategy(_dec(depth))))
        parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def winFrameClause_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        group_idx = draw(st.integers(min_value=0, max_value=1))
        if group_idx == 0:
            parts.append("rows")
        if group_idx == 1:
            parts.append("range")
        parts.append(draw(winFrameExtend_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def winFrameExtend_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append(draw(winFrameBound_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("between")
            parts.append(draw(winFrameBound_strategy(_dec(depth))))
            parts.append("and")
            parts.append(draw(winFrameBound_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def winFrameBound_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        group_idx = draw(st.integers(min_value=0, max_value=4))
        if group_idx == 0:
            parts.append("current")
            parts.append("row")
        if group_idx == 1:
            parts.append("unbounded")
            parts.append("preceding")
        if group_idx == 2:
            parts.append("unbounded")
            parts.append("following")
        if group_idx == 3:
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("preceding")
        if group_idx == 4:
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("following")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def expr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        parts.append("")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def columnTypeExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    _has_suffixes = True

    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        seed_idx = draw(st.integers(min_value=0, max_value=5))
        seed = ""
        if seed_idx == 0:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("(")
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(draw(columnTypeExpr_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(",")
                parts.append(draw(identifier_strategy(_dec(depth))))
                parts.append(draw(columnTypeExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append(",")
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 1:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("(")
            parts.append(draw(enumValue_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(",")
                parts.append(draw(enumValue_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append(",")
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 2:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("(")
            parts.append(draw(columnTypeExpr_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(",")
                parts.append(draw(columnTypeExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append(",")
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 3:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("(")
            if _include_optional(draw):
                parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 4:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=1, max_value=_MAX_REPEAT))):
                parts.append(draw(identifier_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 5:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if depth <= 0 or not _has_suffixes:
            return seed
        n_suffixes = draw(st.integers(min_value=0, max_value=_MAX_LR_CHAIN))
        for _ in range(n_suffixes):
            suffix_idx = draw(st.integers(min_value=0, max_value=0))
            if suffix_idx == 0:
                parts = []
                parts.append("[")
                if _include_optional(draw):
                    parts.append(draw(decimal_literal_token))
                parts.append("]")
                seed = seed + " " + " ".join(p for p in parts if p)
        return seed

    return gen()


@functools.cache
def columnTypeCastExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append(draw(columnTypeCastIdentifier_strategy(_dec(depth))))
            parts.append("with")
            if _include_optional(draw):
                parts.append("local")
            parts.append("time")
            parts.append("zone")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(columnTypeCastIdentifier_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def columnTypeCastIdentifier_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if depth <= 0:
            alt_idx = draw(st.sampled_from([0, 1]))
        else:
            alt_idx = draw(st.sampled_from([0, 1, 2, 3]))
        if alt_idx == 0:
            parts = []
            parts.append(draw(identifier_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(quoted_identifier_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append(draw(interval_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append(draw(keywordForTypeCast_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def keywordForTypeCast_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=3))
        if alt_idx == 0:
            parts = []
            parts.append("date")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("time")
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("timestamp")
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append("interval")
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def columnExprList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(",")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def selectColumnExprListBeforeFrom_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append(draw(selectColumnExpr_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(",")
                parts.append(draw(selectColumnExpr_strategy(_dec(depth))))
            parts.append(",")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(selectColumnExprList_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def selectColumnExprList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(selectColumnExpr_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(selectColumnExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(",")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def selectColumnExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=3))
        if alt_idx == 0:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(":")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("from")
            parts.append(draw(implicitAlias_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append(draw(implicitAlias_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def columnExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    _has_suffixes = True

    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if depth <= 0:
            seed_idx = draw(st.sampled_from([3, 5, 7, 9, 14, 19, 39]))
        else:
            seed_idx = draw(
                st.sampled_from(
                    [
                        0,
                        1,
                        2,
                        3,
                        4,
                        5,
                        6,
                        7,
                        8,
                        9,
                        10,
                        11,
                        12,
                        13,
                        14,
                        15,
                        16,
                        17,
                        18,
                        19,
                        20,
                        21,
                        22,
                        23,
                        24,
                        25,
                        26,
                        27,
                        28,
                        29,
                        30,
                        31,
                        32,
                        33,
                        34,
                        35,
                        36,
                        37,
                        38,
                        39,
                        40,
                    ]
                )
            )
        seed = ""
        if seed_idx == 0:
            parts = []
            parts.append("case")
            if _include_optional(draw):
                parts.append(draw(columnExpr_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=1, max_value=_MAX_REPEAT))):
                parts.append("when")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append("then")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("else")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("end")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 1:
            parts = []
            parts.append("cast")
            parts.append("(")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("as")
            parts.append(draw(columnTypeExpr_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 2:
            parts = []
            parts.append("try_cast")
            parts.append("(")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("as")
            parts.append(draw(columnTypeExpr_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 3:
            parts = []
            parts.append("date")
            parts.append(draw(string_literal_token))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 4:
            parts = []
            parts.append("interval")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append(draw(interval_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 5:
            parts = []
            parts.append("interval")
            parts.append(draw(string_literal_token))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 6:
            parts = []
            parts.append("substring")
            parts.append("(")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("from")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("for")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 7:
            parts = []
            parts.append("timestamp")
            parts.append(draw(string_literal_token))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 8:
            parts = []
            parts.append("trim")
            parts.append("(")
            group_idx = draw(st.integers(min_value=0, max_value=2))
            if group_idx == 0:
                parts.append("both")
            if group_idx == 1:
                parts.append("leading")
            if group_idx == 2:
                parts.append("trailing")
            parts.append(draw(string_strategy(_dec(depth))))
            parts.append("from")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 9:
            parts = []
            parts.append("columns")
            parts.append("(")
            parts.append(draw(string_literal_token))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 10:
            parts = []
            parts.append("columns")
            parts.append("(")
            parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 11:
            parts = []
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append("columns")
                parts.append("(")
                parts.append("*")
                parts.append("exclude")
                parts.append("(")
                parts.append(draw(identifierList_strategy(_dec(depth))))
                parts.append(")")
                parts.append("replace")
                parts.append("(")
                parts.append(draw(columnsReplaceList_strategy(_dec(depth))))
                parts.append(")")
                parts.append(")")
            if group_idx == 1:
                parts.append("(")
                parts.append("*")
                parts.append("exclude")
                parts.append("(")
                parts.append(draw(identifierList_strategy(_dec(depth))))
                parts.append(")")
                parts.append("replace")
                parts.append("(")
                parts.append(draw(columnsReplaceList_strategy(_dec(depth))))
                parts.append(")")
                parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 12:
            parts = []
            parts.append("columns")
            parts.append("(")
            parts.append("*")
            parts.append("exclude")
            parts.append("(")
            parts.append(draw(identifierList_strategy(_dec(depth))))
            parts.append(")")
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 13:
            parts = []
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append("columns")
                parts.append("(")
                parts.append("*")
                parts.append("replace")
                parts.append("(")
                parts.append(draw(columnsReplaceList_strategy(_dec(depth))))
                parts.append(")")
                parts.append(")")
            if group_idx == 1:
                parts.append("(")
                parts.append("*")
                parts.append("replace")
                parts.append("(")
                parts.append(draw(columnsReplaceList_strategy(_dec(depth))))
                parts.append(")")
                parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 14:
            parts = []
            parts.append("columns")
            parts.append("(")
            parts.append("*")
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 15:
            parts = []
            parts.append("columns")
            parts.append("(")
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(".")
            parts.append("*")
            parts.append("exclude")
            parts.append("(")
            parts.append(draw(identifierList_strategy(_dec(depth))))
            parts.append(")")
            parts.append("replace")
            parts.append("(")
            parts.append(draw(columnsReplaceList_strategy(_dec(depth))))
            parts.append(")")
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 16:
            parts = []
            parts.append("columns")
            parts.append("(")
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(".")
            parts.append("*")
            parts.append("exclude")
            parts.append("(")
            parts.append(draw(identifierList_strategy(_dec(depth))))
            parts.append(")")
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 17:
            parts = []
            parts.append("columns")
            parts.append("(")
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(".")
            parts.append("*")
            parts.append("replace")
            parts.append("(")
            parts.append(draw(columnsReplaceList_strategy(_dec(depth))))
            parts.append(")")
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 18:
            parts = []
            parts.append("columns")
            parts.append("(")
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(".")
            parts.append("*")
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 19:
            parts = []
            parts.append("*")
            parts.append("columns")
            parts.append("(")
            parts.append(draw(string_literal_token))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 20:
            parts = []
            parts.append("*")
            parts.append("columns")
            parts.append("(")
            parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 21:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("(")
            if _include_optional(draw):
                parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
            parts.append(draw(withinGroupClause_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 22:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("(")
            if _include_optional(draw):
                parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
            if _include_optional(draw):
                parts.append("(")
                if _include_optional(draw):
                    parts.append("distinct")
                if _include_optional(draw):
                    parts.append(draw(columnExprList_strategy(_dec(depth))))
                parts.append(")")
            if _include_optional(draw):
                parts.append("filter")
                parts.append("(")
                parts.append("where")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append(")")
            parts.append("over")
            parts.append("(")
            parts.append(draw(windowExpr_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 23:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("(")
            if _include_optional(draw):
                parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
            if _include_optional(draw):
                parts.append("(")
                if _include_optional(draw):
                    parts.append("distinct")
                if _include_optional(draw):
                    parts.append(draw(columnExprList_strategy(_dec(depth))))
                parts.append(")")
            if _include_optional(draw):
                parts.append("filter")
                parts.append("(")
                parts.append("where")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append(")")
            parts.append("over")
            parts.append(draw(identifier_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 24:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("(")
                if _include_optional(draw):
                    parts.append(draw(columnExprList_strategy(_dec(depth))))
                parts.append(")")
            parts.append("(")
            if _include_optional(draw):
                parts.append("distinct")
            if _include_optional(draw):
                parts.append(draw(columnExprList_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("order")
                parts.append("by")
                parts.append(draw(orderExprList_strategy(_dec(depth))))
            parts.append(")")
            if _include_optional(draw):
                parts.append("filter")
                parts.append("(")
                parts.append("where")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 25:
            parts = []
            parts.append(draw(hogqlxTagElement_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 26:
            parts = []
            parts.append(draw(templateString_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 27:
            parts = []
            parts.append(draw(literal_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 28:
            parts = []
            parts.append("-")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 29:
            parts = []
            parts.append("not")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 30:
            parts = []
            if _include_optional(draw):
                parts.append(draw(tableIdentifier_strategy(_dec(depth))))
                parts.append(".")
            parts.append("*")
            if _include_optional(draw):
                parts.append("exclude")
                parts.append("(")
                parts.append(draw(identifierList_strategy(_dec(depth))))
                parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 31:
            parts = []
            parts.append("lambda")
            parts.append(draw(identifier_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(",")
                parts.append(draw(identifier_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append(",")
            parts.append(":")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 32:
            parts = []
            parts.append("(")
            parts.append(draw(selectSetStmt_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 33:
            parts = []
            parts.append("(")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 34:
            parts = []
            parts.append("(")
            parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 35:
            parts = []
            if _include_optional(draw):
                parts.append("array")
            parts.append("[")
            if _include_optional(draw):
                parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append("]")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 36:
            parts = []
            parts.append("{")
            if _include_optional(draw):
                parts.append(draw(kvPairList_strategy(_dec(depth))))
            parts.append("}")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 37:
            parts = []
            parts.append(draw(columnLambdaExpr_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 38:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(":=")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 39:
            parts = []
            parts.append("#")
            parts.append(draw(decimal_literal_token))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 40:
            parts = []
            parts.append(draw(columnIdentifier_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if depth <= 0 or not _has_suffixes:
            return seed
        n_suffixes = draw(st.integers(min_value=0, max_value=_MAX_LR_CHAIN))
        for _ in range(n_suffixes):
            suffix_idx = draw(st.integers(min_value=0, max_value=21))
            if suffix_idx == 0:
                parts = []
                parts.append("(")
                parts.append(draw(selectSetStmt_strategy(_dec(depth))))
                parts.append(")")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 1:
                parts = []
                parts.append("(")
                if _include_optional(draw):
                    parts.append(draw(columnExprList_strategy(_dec(depth))))
                parts.append(")")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 2:
                parts = []
                parts.append("[")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append("]")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 3:
                parts = []
                parts.append("[")
                if _include_optional(draw):
                    parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append(":")
                if _include_optional(draw):
                    parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append("]")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 4:
                parts = []
                parts.append(".")
                parts.append(draw(decimal_literal_token))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 5:
                parts = []
                parts.append(".")
                parts.append(draw(identifier_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 6:
                parts = []
                parts.append("?.")
                parts.append("[")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append("]")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 7:
                parts = []
                parts.append("?.")
                parts.append(draw(decimal_literal_token))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 8:
                parts = []
                parts.append("?.")
                parts.append(draw(identifier_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 9:
                parts = []
                parts.append("::")
                parts.append(draw(columnTypeCastExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 10:
                parts = []
                group_idx = draw(st.integers(min_value=0, max_value=2))
                if group_idx == 0:
                    parts.append("*")
                if group_idx == 1:
                    parts.append("/")
                if group_idx == 2:
                    parts.append("%")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 11:
                parts = []
                group_idx = draw(st.integers(min_value=0, max_value=2))
                if group_idx == 0:
                    parts.append("+")
                if group_idx == 1:
                    parts.append("-")
                if group_idx == 2:
                    parts.append("||")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 12:
                parts = []
                group_idx = draw(st.integers(min_value=0, max_value=14))
                if group_idx == 0:
                    parts.append("==")
                if group_idx == 1:
                    parts.append("=")
                if group_idx == 2:
                    parts.append(draw(st.sampled_from(["!=", "<>"])))
                if group_idx == 3:
                    parts.append("<=")
                if group_idx == 4:
                    parts.append("<")
                if group_idx == 5:
                    parts.append(">=")
                if group_idx == 6:
                    parts.append(">")
                if group_idx == 7:
                    if _include_optional(draw):
                        parts.append("not")
                    parts.append("in")
                    if _include_optional(draw):
                        parts.append("cohort")
                if group_idx == 8:
                    if _include_optional(draw):
                        parts.append("not")
                    group_idx = draw(st.integers(min_value=0, max_value=1))
                    if group_idx == 0:
                        parts.append("like")
                    if group_idx == 1:
                        parts.append("ilike")
                if group_idx == 9:
                    parts.append("~")
                if group_idx == 10:
                    parts.append("=~")
                if group_idx == 11:
                    parts.append("!~")
                if group_idx == 12:
                    parts.append("~*")
                if group_idx == 13:
                    parts.append("=~*")
                if group_idx == 14:
                    parts.append("!~*")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 13:
                parts = []
                parts.append("ignore")
                parts.append("nulls")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 14:
                parts = []
                parts.append("is")
                if _include_optional(draw):
                    parts.append("not")
                parts.append("null")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 15:
                parts = []
                parts.append("is")
                if _include_optional(draw):
                    parts.append("not")
                parts.append("distinct")
                parts.append("from")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 16:
                parts = []
                parts.append("??")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 17:
                parts = []
                parts.append("and")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 18:
                parts = []
                parts.append("or")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 19:
                parts = []
                if _include_optional(draw):
                    parts.append("not")
                parts.append("between")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append("and")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 20:
                parts = []
                parts.append("?")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                parts.append(":")
                parts.append(draw(columnExpr_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 21:
                parts = []
                parts.append("as")
                group_idx = draw(st.integers(min_value=0, max_value=1))
                if group_idx == 0:
                    parts.append(draw(identifier_strategy(_dec(depth))))
                if group_idx == 1:
                    parts.append(draw(string_literal_token))
                seed = seed + " " + " ".join(p for p in parts if p)
        return seed

    return gen()


@functools.cache
def columnLambdaExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            group_idx = draw(st.integers(min_value=0, max_value=2))
            if group_idx == 0:
                parts.append("(")
                parts.append(draw(identifier_strategy(_dec(depth))))
                for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                    parts.append(",")
                    parts.append(draw(identifier_strategy(_dec(depth))))
                if _include_optional(draw):
                    parts.append(",")
                parts.append(")")
            if group_idx == 1:
                parts.append(draw(identifier_strategy(_dec(depth))))
                for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                    parts.append(",")
                    parts.append(draw(identifier_strategy(_dec(depth))))
                if _include_optional(draw):
                    parts.append(",")
            if group_idx == 2:
                parts.append("(")
                parts.append(")")
            parts.append("->")
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append(draw(columnExpr_strategy(_dec(depth))))
            if group_idx == 1:
                parts.append(draw(block_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("lambda")
            parts.append(draw(identifier_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(",")
                parts.append(draw(identifier_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append(",")
            parts.append(":")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def columnsReplaceList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnsReplaceItem_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(columnsReplaceItem_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def columnsReplaceItem_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        parts.append("as")
        parts.append(draw(identifier_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def hogqlxChildElement_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=2))
        if alt_idx == 0:
            parts = []
            parts.append(draw(hogqlxTagElement_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(hogqlxText_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("{")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("}")
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def hogqlxText_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(hogqlx_text_token))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def hogqlxTagElement_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append("<")
            parts.append(draw(identifier_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(draw(hogqlxTagAttribute_strategy(_dec(depth))))
            parts.append("/>")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("<")
            parts.append(draw(identifier_strategy(_dec(depth))))
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(draw(hogqlxTagAttribute_strategy(_dec(depth))))
            parts.append(">")
            for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
                parts.append(draw(hogqlxChildElement_strategy(_dec(depth))))
            parts.append("</")
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append(">")
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def hogqlxTagAttribute_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=2))
        if alt_idx == 0:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("=")
            parts.append(draw(string_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            parts.append("=")
            parts.append("{")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("}")
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def withExprList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(withExpr_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(withExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(",")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def withExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append(draw(identifier_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append(draw(withExprColumnNameList_strategy(_dec(depth))))
            if _include_optional(draw):
                parts.append("using")
                parts.append("key")
                parts.append(draw(withExprColumnNameList_strategy(_dec(depth))))
            parts.append("as")
            if _include_optional(draw):
                if _include_optional(draw):
                    parts.append("not")
                parts.append("materialized")
            parts.append("(")
            parts.append(draw(selectSetStmt_strategy(_dec(depth))))
            parts.append(")")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("as")
            parts.append(draw(identifier_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def withExprColumnNameList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("(")
        parts.append(draw(identifier_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(identifier_strategy(_dec(depth))))
        parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def columnIdentifier_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append(draw(placeholder_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            if _include_optional(draw):
                parts.append(draw(tableIdentifier_strategy(_dec(depth))))
                parts.append(".")
            parts.append(draw(nestedIdentifier_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def nestedIdentifier_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(identifier_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(".")
            parts.append(draw(identifier_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def tableExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    _has_suffixes = True

    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        seed_idx = draw(st.integers(min_value=0, max_value=5))
        seed = ""
        if seed_idx == 0:
            parts = []
            parts.append(draw(tableIdentifier_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 1:
            parts = []
            parts.append(draw(tableFunctionExpr_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 2:
            parts = []
            parts.append("(")
            parts.append(draw(selectSetStmt_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 3:
            parts = []
            parts.append("(")
            parts.append(draw(valuesClause_strategy(_dec(depth))))
            parts.append(")")
            seed = " ".join(p for p in parts if p)
        if seed_idx == 4:
            parts = []
            parts.append(draw(hogqlxTagElement_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if seed_idx == 5:
            parts = []
            parts.append(draw(placeholder_strategy(_dec(depth))))
            seed = " ".join(p for p in parts if p)
        if depth <= 0 or not _has_suffixes:
            return seed
        n_suffixes = draw(st.integers(min_value=0, max_value=_MAX_LR_CHAIN))
        for _ in range(n_suffixes):
            suffix_idx = draw(st.integers(min_value=0, max_value=2))
            if suffix_idx == 0:
                parts = []
                parts.append("pivot")
                parts.append("(")
                parts.append(draw(columnExprList_strategy(_dec(depth))))
                parts.append(draw(pivotColumnList_strategy(_dec(depth))))
                if _include_optional(draw):
                    parts.append("group")
                    parts.append("by")
                    parts.append(draw(columnExprList_strategy(_dec(depth))))
                parts.append(")")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 1:
                parts = []
                parts.append("unpivot")
                if _include_optional(draw):
                    parts.append("include")
                    parts.append("nulls")
                parts.append("(")
                parts.append(draw(unpivotColumnList_strategy(_dec(depth))))
                parts.append(")")
                seed = seed + " " + " ".join(p for p in parts if p)
            if suffix_idx == 2:
                parts = []
                group_idx = draw(st.integers(min_value=0, max_value=1))
                if group_idx == 0:
                    parts.append(draw(alias_strategy(_dec(depth))))
                if group_idx == 1:
                    parts.append("as")
                    parts.append(draw(identifier_strategy(_dec(depth))))
                if _include_optional(draw):
                    parts.append(draw(columnAliases_strategy(_dec(depth))))
                seed = seed + " " + " ".join(p for p in parts if p)
        return seed

    return gen()


@functools.cache
def pivotColumnList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("for")
        for _ in range(draw(st.integers(min_value=1, max_value=_MAX_REPEAT))):
            parts.append(draw(pivotColumn_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def pivotColumn_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExprTupleOrSingle_strategy(_dec(depth))))
        parts.append("in")
        parts.append("(")
        parts.append(draw(columnExprList_strategy(_dec(depth))))
        parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def unpivotColumnList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(unpivotColumn_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(unpivotColumn_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(",")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def unpivotColumn_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExprTupleOrSingle_strategy(_dec(depth))))
        parts.append("for")
        parts.append(draw(columnExprTupleOrSingle_strategy(_dec(depth))))
        parts.append("in")
        parts.append("(")
        parts.append(draw(columnExprList_strategy(_dec(depth))))
        parts.append(")")
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(draw(columnExprTupleOrSingle_strategy(_dec(depth))))
            parts.append("in")
            parts.append("(")
            parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def columnExprTupleOrSingle_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=1))
        if alt_idx == 0:
            parts = []
            parts.append("(")
            parts.append(draw(columnExprList_strategy(_dec(depth))))
            parts.append(")")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def columnAliases_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("(")
        parts.append(draw(identifier_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(identifier_strategy(_dec(depth))))
        parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def tableFunctionExpr_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(identifier_strategy(_dec(depth))))
        parts.append("(")
        if _include_optional(draw):
            parts.append(draw(tableArgList_strategy(_dec(depth))))
        parts.append(")")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def tableIdentifier_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if _include_optional(draw):
            parts.append(draw(databaseIdentifier_strategy(_dec(depth))))
            parts.append(".")
        parts.append(draw(nestedIdentifier_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def tableArgList_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(",")
            parts.append(draw(columnExpr_strategy(_dec(depth))))
        if _include_optional(draw):
            parts.append(",")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def databaseIdentifier_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(identifier_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def floatingLiteral_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=2))
        if alt_idx == 0:
            parts = []
            parts.append(draw(floating_literal_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(".")
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append(draw(decimal_literal_token))
            if group_idx == 1:
                parts.append(draw(octal_literal_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append(draw(decimal_literal_token))
            parts.append(".")
            if _include_optional(draw):
                group_idx = draw(st.integers(min_value=0, max_value=1))
                if group_idx == 0:
                    parts.append(draw(decimal_literal_token))
                if group_idx == 1:
                    parts.append(draw(octal_literal_token))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def numberLiteral_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if _include_optional(draw):
            group_idx = draw(st.integers(min_value=0, max_value=1))
            if group_idx == 0:
                parts.append("+")
            if group_idx == 1:
                parts.append("-")
        group_idx = draw(st.integers(min_value=0, max_value=7))
        if group_idx == 0:
            parts.append(draw(floatingLiteral_strategy(_dec(depth))))
        if group_idx == 1:
            parts.append(draw(binary_literal_token))
        if group_idx == 2:
            parts.append(draw(octal_literal_token))
        if group_idx == 3:
            parts.append(draw(octal_prefix_literal_token))
        if group_idx == 4:
            parts.append(draw(decimal_literal_token))
        if group_idx == 5:
            parts.append(draw(hexadecimal_literal_token))
        if group_idx == 6:
            parts.append(draw(st.sampled_from(["inf", "infinity"])))
        if group_idx == 7:
            parts.append("nan")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def literal_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if depth <= 0:
            alt_idx = draw(st.sampled_from([1, 2]))
        else:
            alt_idx = draw(st.sampled_from([0, 1, 2]))
        if alt_idx == 0:
            parts = []
            parts.append(draw(numberLiteral_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(string_literal_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("null")
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def interval_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=7))
        if alt_idx == 0:
            parts = []
            parts.append("second")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("minute")
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("hour")
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append("day")
            return " ".join(p for p in parts if p)
        if alt_idx == 4:
            parts = []
            parts.append("week")
            return " ".join(p for p in parts if p)
        if alt_idx == 5:
            parts = []
            parts.append("month")
            return " ".join(p for p in parts if p)
        if alt_idx == 6:
            parts = []
            parts.append("quarter")
            return " ".join(p for p in parts if p)
        if alt_idx == 7:
            parts = []
            parts.append(draw(st.sampled_from(["year", "yyyy"])))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def keyword_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=108))
        if alt_idx == 0:
            parts = []
            parts.append("all")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("and")
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("anti")
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append("any")
            return " ".join(p for p in parts if p)
        if alt_idx == 4:
            parts = []
            parts.append("array")
            return " ".join(p for p in parts if p)
        if alt_idx == 5:
            parts = []
            parts.append("as")
            return " ".join(p for p in parts if p)
        if alt_idx == 6:
            parts = []
            parts.append(draw(st.sampled_from(["asc", "ascending"])))
            return " ".join(p for p in parts if p)
        if alt_idx == 7:
            parts = []
            parts.append("asof")
            return " ".join(p for p in parts if p)
        if alt_idx == 8:
            parts = []
            parts.append("between")
            return " ".join(p for p in parts if p)
        if alt_idx == 9:
            parts = []
            parts.append("both")
            return " ".join(p for p in parts if p)
        if alt_idx == 10:
            parts = []
            parts.append("by")
            return " ".join(p for p in parts if p)
        if alt_idx == 11:
            parts = []
            parts.append("case")
            return " ".join(p for p in parts if p)
        if alt_idx == 12:
            parts = []
            parts.append("cast")
            return " ".join(p for p in parts if p)
        if alt_idx == 13:
            parts = []
            parts.append("cohort")
            return " ".join(p for p in parts if p)
        if alt_idx == 14:
            parts = []
            parts.append("collate")
            return " ".join(p for p in parts if p)
        if alt_idx == 15:
            parts = []
            parts.append("columns")
            return " ".join(p for p in parts if p)
        if alt_idx == 16:
            parts = []
            parts.append("cross")
            return " ".join(p for p in parts if p)
        if alt_idx == 17:
            parts = []
            parts.append("cube")
            return " ".join(p for p in parts if p)
        if alt_idx == 18:
            parts = []
            parts.append("current")
            return " ".join(p for p in parts if p)
        if alt_idx == 19:
            parts = []
            parts.append("date")
            return " ".join(p for p in parts if p)
        if alt_idx == 20:
            parts = []
            parts.append("desc")
            return " ".join(p for p in parts if p)
        if alt_idx == 21:
            parts = []
            parts.append("descending")
            return " ".join(p for p in parts if p)
        if alt_idx == 22:
            parts = []
            parts.append("distinct")
            return " ".join(p for p in parts if p)
        if alt_idx == 23:
            parts = []
            parts.append("else")
            return " ".join(p for p in parts if p)
        if alt_idx == 24:
            parts = []
            parts.append("end")
            return " ".join(p for p in parts if p)
        if alt_idx == 25:
            parts = []
            parts.append("exclude")
            return " ".join(p for p in parts if p)
        if alt_idx == 26:
            parts = []
            parts.append("extract")
            return " ".join(p for p in parts if p)
        if alt_idx == 27:
            parts = []
            parts.append("fill")
            return " ".join(p for p in parts if p)
        if alt_idx == 28:
            parts = []
            parts.append("filter")
            return " ".join(p for p in parts if p)
        if alt_idx == 29:
            parts = []
            parts.append("final")
            return " ".join(p for p in parts if p)
        if alt_idx == 30:
            parts = []
            parts.append("first")
            return " ".join(p for p in parts if p)
        if alt_idx == 31:
            parts = []
            parts.append("for")
            return " ".join(p for p in parts if p)
        if alt_idx == 32:
            parts = []
            parts.append("following")
            return " ".join(p for p in parts if p)
        if alt_idx == 33:
            parts = []
            parts.append("from")
            return " ".join(p for p in parts if p)
        if alt_idx == 34:
            parts = []
            parts.append("full")
            return " ".join(p for p in parts if p)
        if alt_idx == 35:
            parts = []
            parts.append("group")
            return " ".join(p for p in parts if p)
        if alt_idx == 36:
            parts = []
            parts.append("having")
            return " ".join(p for p in parts if p)
        if alt_idx == 37:
            parts = []
            parts.append("id")
            return " ".join(p for p in parts if p)
        if alt_idx == 38:
            parts = []
            parts.append("interpolate")
            return " ".join(p for p in parts if p)
        if alt_idx == 39:
            parts = []
            parts.append("is")
            return " ".join(p for p in parts if p)
        if alt_idx == 40:
            parts = []
            parts.append("grouping")
            return " ".join(p for p in parts if p)
        if alt_idx == 41:
            parts = []
            parts.append("if")
            return " ".join(p for p in parts if p)
        if alt_idx == 42:
            parts = []
            parts.append("ignore")
            return " ".join(p for p in parts if p)
        if alt_idx == 43:
            parts = []
            parts.append("ilike")
            return " ".join(p for p in parts if p)
        if alt_idx == 44:
            parts = []
            parts.append("include")
            return " ".join(p for p in parts if p)
        if alt_idx == 45:
            parts = []
            parts.append("in")
            return " ".join(p for p in parts if p)
        if alt_idx == 46:
            parts = []
            parts.append("inner")
            return " ".join(p for p in parts if p)
        if alt_idx == 47:
            parts = []
            parts.append("interval")
            return " ".join(p for p in parts if p)
        if alt_idx == 48:
            parts = []
            parts.append("join")
            return " ".join(p for p in parts if p)
        if alt_idx == 49:
            parts = []
            parts.append("key")
            return " ".join(p for p in parts if p)
        if alt_idx == 50:
            parts = []
            parts.append("lambda")
            return " ".join(p for p in parts if p)
        if alt_idx == 51:
            parts = []
            parts.append("last")
            return " ".join(p for p in parts if p)
        if alt_idx == 52:
            parts = []
            parts.append("leading")
            return " ".join(p for p in parts if p)
        if alt_idx == 53:
            parts = []
            parts.append("left")
            return " ".join(p for p in parts if p)
        if alt_idx == 54:
            parts = []
            parts.append("like")
            return " ".join(p for p in parts if p)
        if alt_idx == 55:
            parts = []
            parts.append("limit")
            return " ".join(p for p in parts if p)
        if alt_idx == 56:
            parts = []
            parts.append("local")
            return " ".join(p for p in parts if p)
        if alt_idx == 57:
            parts = []
            parts.append("name")
            return " ".join(p for p in parts if p)
        if alt_idx == 58:
            parts = []
            parts.append("natural")
            return " ".join(p for p in parts if p)
        if alt_idx == 59:
            parts = []
            parts.append("not")
            return " ".join(p for p in parts if p)
        if alt_idx == 60:
            parts = []
            parts.append("nulls")
            return " ".join(p for p in parts if p)
        if alt_idx == 61:
            parts = []
            parts.append("offset")
            return " ".join(p for p in parts if p)
        if alt_idx == 62:
            parts = []
            parts.append("on")
            return " ".join(p for p in parts if p)
        if alt_idx == 63:
            parts = []
            parts.append("or")
            return " ".join(p for p in parts if p)
        if alt_idx == 64:
            parts = []
            parts.append("order")
            return " ".join(p for p in parts if p)
        if alt_idx == 65:
            parts = []
            parts.append("outer")
            return " ".join(p for p in parts if p)
        if alt_idx == 66:
            parts = []
            parts.append("over")
            return " ".join(p for p in parts if p)
        if alt_idx == 67:
            parts = []
            parts.append("partition")
            return " ".join(p for p in parts if p)
        if alt_idx == 68:
            parts = []
            parts.append("pivot")
            return " ".join(p for p in parts if p)
        if alt_idx == 69:
            parts = []
            parts.append("positional")
            return " ".join(p for p in parts if p)
        if alt_idx == 70:
            parts = []
            parts.append("preceding")
            return " ".join(p for p in parts if p)
        if alt_idx == 71:
            parts = []
            parts.append("prewhere")
            return " ".join(p for p in parts if p)
        if alt_idx == 72:
            parts = []
            parts.append("qualify")
            return " ".join(p for p in parts if p)
        if alt_idx == 73:
            parts = []
            parts.append("range")
            return " ".join(p for p in parts if p)
        if alt_idx == 74:
            parts = []
            parts.append("recursive")
            return " ".join(p for p in parts if p)
        if alt_idx == 75:
            parts = []
            parts.append("replace")
            return " ".join(p for p in parts if p)
        if alt_idx == 76:
            parts = []
            parts.append("return")
            return " ".join(p for p in parts if p)
        if alt_idx == 77:
            parts = []
            parts.append("right")
            return " ".join(p for p in parts if p)
        if alt_idx == 78:
            parts = []
            parts.append("rollup")
            return " ".join(p for p in parts if p)
        if alt_idx == 79:
            parts = []
            parts.append("row")
            return " ".join(p for p in parts if p)
        if alt_idx == 80:
            parts = []
            parts.append("rows")
            return " ".join(p for p in parts if p)
        if alt_idx == 81:
            parts = []
            parts.append("sample")
            return " ".join(p for p in parts if p)
        if alt_idx == 82:
            parts = []
            parts.append("select")
            return " ".join(p for p in parts if p)
        if alt_idx == 83:
            parts = []
            parts.append("semi")
            return " ".join(p for p in parts if p)
        if alt_idx == 84:
            parts = []
            parts.append("sets")
            return " ".join(p for p in parts if p)
        if alt_idx == 85:
            parts = []
            parts.append("settings")
            return " ".join(p for p in parts if p)
        if alt_idx == 86:
            parts = []
            parts.append("step")
            return " ".join(p for p in parts if p)
        if alt_idx == 87:
            parts = []
            parts.append("substring")
            return " ".join(p for p in parts if p)
        if alt_idx == 88:
            parts = []
            parts.append("then")
            return " ".join(p for p in parts if p)
        if alt_idx == 89:
            parts = []
            parts.append("ties")
            return " ".join(p for p in parts if p)
        if alt_idx == 90:
            parts = []
            parts.append("time")
            return " ".join(p for p in parts if p)
        if alt_idx == 91:
            parts = []
            parts.append("timestamp")
            return " ".join(p for p in parts if p)
        if alt_idx == 92:
            parts = []
            parts.append("totals")
            return " ".join(p for p in parts if p)
        if alt_idx == 93:
            parts = []
            parts.append("trailing")
            return " ".join(p for p in parts if p)
        if alt_idx == 94:
            parts = []
            parts.append("trim")
            return " ".join(p for p in parts if p)
        if alt_idx == 95:
            parts = []
            parts.append("truncate")
            return " ".join(p for p in parts if p)
        if alt_idx == 96:
            parts = []
            parts.append("try_cast")
            return " ".join(p for p in parts if p)
        if alt_idx == 97:
            parts = []
            parts.append("to")
            return " ".join(p for p in parts if p)
        if alt_idx == 98:
            parts = []
            parts.append("top")
            return " ".join(p for p in parts if p)
        if alt_idx == 99:
            parts = []
            parts.append("unbounded")
            return " ".join(p for p in parts if p)
        if alt_idx == 100:
            parts = []
            parts.append("union")
            return " ".join(p for p in parts if p)
        if alt_idx == 101:
            parts = []
            parts.append("unpivot")
            return " ".join(p for p in parts if p)
        if alt_idx == 102:
            parts = []
            parts.append("using")
            return " ".join(p for p in parts if p)
        if alt_idx == 103:
            parts = []
            parts.append("values")
            return " ".join(p for p in parts if p)
        if alt_idx == 104:
            parts = []
            parts.append("when")
            return " ".join(p for p in parts if p)
        if alt_idx == 105:
            parts = []
            parts.append("where")
            return " ".join(p for p in parts if p)
        if alt_idx == 106:
            parts = []
            parts.append("window")
            return " ".join(p for p in parts if p)
        if alt_idx == 107:
            parts = []
            parts.append("with")
            return " ".join(p for p in parts if p)
        if alt_idx == 108:
            parts = []
            parts.append("zone")
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def keywordForAlias_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=3))
        if alt_idx == 0:
            parts = []
            parts.append("date")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("first")
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("id")
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append("key")
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def keywordForImplicitAlias_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        alt_idx = draw(st.integers(min_value=0, max_value=8))
        if alt_idx == 0:
            parts = []
            parts.append(draw(st.sampled_from(["asc", "ascending"])))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append("cohort")
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append("date")
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append("descending")
            return " ".join(p for p in parts if p)
        if alt_idx == 4:
            parts = []
            parts.append("final")
            return " ".join(p for p in parts if p)
        if alt_idx == 5:
            parts = []
            parts.append("id")
            return " ".join(p for p in parts if p)
        if alt_idx == 6:
            parts = []
            parts.append("return")
            return " ".join(p for p in parts if p)
        if alt_idx == 7:
            parts = []
            parts.append("top")
            return " ".join(p for p in parts if p)
        if alt_idx == 8:
            parts = []
            parts.append("totals")
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def alias_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if depth <= 0:
            alt_idx = draw(st.sampled_from([0, 1]))
        else:
            alt_idx = draw(st.sampled_from([0, 1, 2]))
        if alt_idx == 0:
            parts = []
            parts.append(draw(identifier_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(quoted_identifier_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append(draw(keywordForAlias_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def implicitAlias_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if depth <= 0:
            alt_idx = draw(st.sampled_from([0, 1]))
        else:
            alt_idx = draw(st.sampled_from([0, 1, 2]))
        if alt_idx == 0:
            parts = []
            parts.append(draw(identifier_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(quoted_identifier_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append(draw(keywordForImplicitAlias_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def identifier_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if depth <= 0:
            alt_idx = draw(st.sampled_from([0, 1]))
        else:
            alt_idx = draw(st.sampled_from([0, 1, 2, 3]))
        if alt_idx == 0:
            parts = []
            parts.append(draw(identifier_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(quoted_identifier_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 2:
            parts = []
            parts.append(draw(interval_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        if alt_idx == 3:
            parts = []
            parts.append(draw(keyword_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def enumValue_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(string_strategy(_dec(depth))))
        parts.append("=")
        parts.append(draw(numberLiteral_strategy(_dec(depth))))
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def placeholder_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append("{")
        parts.append(draw(columnExpr_strategy(_dec(depth))))
        parts.append("}")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def string_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if depth <= 0:
            alt_idx = draw(st.sampled_from([0]))
        else:
            alt_idx = draw(st.sampled_from([0, 1]))
        if alt_idx == 0:
            parts = []
            parts.append(draw(string_literal_token))
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(templateString_strategy(_dec(depth))))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def templateString_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(quote_single_template_token))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(draw(stringContents_strategy(_dec(depth))))
        parts.append("'")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def stringContents_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if depth <= 0:
            alt_idx = draw(st.sampled_from([1]))
        else:
            alt_idx = draw(st.sampled_from([0, 1]))
        if alt_idx == 0:
            parts = []
            parts.append(draw(string_escape_trigger_token))
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("}")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(string_text_token))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()


@functools.cache
def fullTemplateString_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        parts.append(draw(quote_single_template_full_token))
        for _ in range(draw(st.integers(min_value=0, max_value=_MAX_REPEAT))):
            parts.append(draw(stringContentsFull_strategy(_dec(depth))))
        parts.append("")
        return " ".join(p for p in parts if p)

    return gen()


@functools.cache
def stringContentsFull_strategy(depth: int = _DEFAULT_DEPTH) -> st.SearchStrategy[str]:
    @st.composite
    def gen(draw: Any) -> str:
        parts: list[str] = []
        if depth <= 0:
            alt_idx = draw(st.sampled_from([1]))
        else:
            alt_idx = draw(st.sampled_from([0, 1]))
        if alt_idx == 0:
            parts = []
            parts.append(draw(full_string_escape_trigger_token))
            parts.append(draw(columnExpr_strategy(_dec(depth))))
            parts.append("}")
            return " ".join(p for p in parts if p)
        if alt_idx == 1:
            parts = []
            parts.append(draw(full_string_text_token))
            return " ".join(p for p in parts if p)
        raise AssertionError("unreachable")

    return gen()
