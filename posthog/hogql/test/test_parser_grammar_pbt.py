"""Grammar-driven property-based tests for the HogQL parser.

Strategies are auto-generated from ``HogQLParser.g4`` /
``HogQLLexer.common.g4`` by
``posthog/hogql/scripts/build_grammar_strategies.py`` and imported
from ``_generated_grammar_strategies``. Variable-content tokens are
hand-written once in ``_grammar_token_strategies``.

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
from posthog.hogql.test._grammar_token_strategies import _RESERVED_KEYWORDS
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
    """Randomise keyword case (preserves the rest of the string).
    Skipped inside single-quoted strings and double-quoted identifiers
    — quoted identifiers are case-sensitive, so flipping a fragment
    that happens to share text with a keyword (e.g. ``in`` inside
    ``"abc in def"``) would change the identifier's value."""

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
    in_squote = False
    in_dquote = False
    for token in query.split(" "):
        in_string = in_squote or in_dquote
        stripped = token.strip(",()")
        if not in_string and stripped.upper() in _KEYWORDS_FOR_CASE_VARIATION:
            out.append(token.replace(stripped, _flip(stripped)))
        else:
            out.append(token)
        if token.count("'") % 2 == 1:
            in_squote = not in_squote
        if token.count('"') % 2 == 1:
            in_dquote = not in_dquote
    return " ".join(out)


@st.composite
def _whitespace_jiggle(draw: Any, query: str) -> str:
    """Replace single spaces with whitespace variants — spaces, tabs,
    newlines, multi-space runs. Skipped inside single-quoted string
    literals and double-quoted identifiers, both of which can legally
    contain a space character (``quoted_identifier_token`` draws from
    an alphabet that includes spaces, so identifiers like
    ``"abc def"`` exist; replacing the internal space would change
    the identifier's value rather than its surrounding whitespace)."""
    out: list[str] = []
    in_string = False
    quote: str | None = None
    for ch in query:
        if not in_string and ch in ("'", '"'):
            in_string = True
            quote = ch
            out.append(ch)
            continue
        if in_string and ch == quote:
            in_string = False
            quote = None
            out.append(ch)
            continue
        if ch == " " and not in_string:
            ws = draw(st.sampled_from([" ", "  ", "\t", "\n", " \n ", "\t\n"]))
            out.append(ws)
        else:
            out.append(ch)
    return "".join(out)


@st.composite
def _comment_jiggle(draw: Any, query: str) -> str:
    """Insert block / line comments before clause-keyword tokens.
    Skipped inside single-quoted strings and double-quoted identifiers
    — both alphabets include space, so a literal like ``"abc in def"``
    splits to ``["abc, in, def"]`` and the inner ``in`` would otherwise
    match the ``IN`` keyword and receive a comment, producing a
    lexically broken identifier."""
    out: list[str] = []
    in_squote = False
    in_dquote = False
    for tok in query.split(" "):
        in_string = in_squote or in_dquote
        if (
            not in_string
            and tok.upper() in _KEYWORDS_FOR_CASE_VARIATION
            and draw(st.integers(min_value=0, max_value=4)) == 0
        ):
            # ``--...\n`` is a separate lexical path from ``/* ... */``
            # — line comments must extend to end-of-line, so they
            # exercise ``\n``-terminated lookaheads that the block-comment
            # form doesn't reach. No space between ``--`` and the body
            # so the whole token is hostile to ``_whitespace_jiggle``
            # substitution (which would otherwise turn the space into a
            # ``\n`` and terminate the comment prematurely).
            comment = draw(
                st.sampled_from(
                    [
                        "/* note */",
                        "/**/",
                        "/* multi\nline */",
                        "--note\n",
                    ]
                )
            )
            out.append(comment)
        if tok.count("'") % 2 == 1:
            in_squote = not in_squote
        if tok.count('"') % 2 == 1:
            in_dquote = not in_dquote
        out.append(tok)
    return " ".join(out)


def _apply_jiggle(query: str) -> st.SearchStrategy[str]:
    """Compose the three jiggles. Each is independently optional.

    Ordering matters: ``_case_jiggle`` and ``_comment_jiggle`` both
    locate clause keywords via ``query.split(" ")``, which only splits
    on literal space. ``_whitespace_jiggle`` rewrites single spaces to
    tabs / newlines / runs, after which a later ``split(" ")`` lands
    the whole query in one "token" and finds no keywords. So run the
    keyword-aware jiggles first and whitespace last."""

    @st.composite
    def _inner(draw: Any) -> str:
        result = query
        if draw(st.booleans()):
            result = draw(_case_jiggle(result))
        if draw(st.booleans()):
            result = draw(_comment_jiggle(result))
        if draw(st.booleans()):
            result = draw(_whitespace_jiggle(result))
        return result

    return _inner()


# ---------------------------------------------------------------------------
# Mutation layer
# ---------------------------------------------------------------------------
#
# The grammar generator only emits *valid* surface (it walks valid
# productions). To exercise the rejection path — "does the candidate
# refuse what the oracle refuses?" — we perturb a valid query into a
# near-miss invalid one. Each operator targets a distinct syntactic
# failure mode. A mutation that happens to land on still-valid syntax
# is harmless: it flows through the normal acceptance-parity check.
#
# Tokens are crude space-split units (the generator emits space-separated
# tokens), which keeps the perturbations cheap and the invalid forms
# realistic (a stray `)` mid-query, a doubled keyword, a truncated tail).

# Reserved keywords / operators that are hostile when injected into an
# arbitrary position — they break the surrounding production without
# being silently absorbable as identifiers.
_INJECTION_TOKENS = (
    "select",
    "from",
    "where",
    "group",
    "by",
    "join",
    "union",
    "(",
    ")",
    "[",
    "]",
    ",",
    "*",
    "+",
    "::",
    "->",
    "between",
    "and",
)


@st.composite
def _mutate_once(draw: Any, query: str) -> str:
    """Apply a single perturbation. Returns the query unchanged when it's
    too short to perturb meaningfully."""
    tokens = [t for t in query.split(" ") if t != ""]
    if len(tokens) < 2:
        return query

    op = draw(
        st.sampled_from(
            [
                "delete",  # drop a token — unbalances counts, strands operators
                "duplicate",  # repeat a token — e.g. `SELECT SELECT`
                "swap",  # reorder adjacent tokens
                "inject",  # splice in a hostile keyword/operator
                "drop_paren",  # remove one `(` or `)` to unbalance nesting
                "truncate",  # cut the tail — incomplete production
            ]
        )
    )

    if op == "delete":
        i = draw(st.integers(min_value=0, max_value=len(tokens) - 1))
        del tokens[i]
    elif op == "duplicate":
        i = draw(st.integers(min_value=0, max_value=len(tokens) - 1))
        tokens.insert(i, tokens[i])
    elif op == "swap":
        i = draw(st.integers(min_value=0, max_value=len(tokens) - 2))
        tokens[i], tokens[i + 1] = tokens[i + 1], tokens[i]
    elif op == "inject":
        i = draw(st.integers(min_value=0, max_value=len(tokens)))
        tokens.insert(i, draw(st.sampled_from(_INJECTION_TOKENS)))
    elif op == "drop_paren":
        paren_positions = [i for i, t in enumerate(tokens) if t in ("(", ")", "[", "]")]
        if not paren_positions:
            return query
        del tokens[draw(st.sampled_from(paren_positions))]
    elif op == "truncate":
        cut = draw(st.integers(min_value=1, max_value=len(tokens) - 1))
        tokens = tokens[:cut]

    return " ".join(tokens)


def _apply_mutation(query: str) -> st.SearchStrategy[str]:
    """Perturb a valid query into a near-miss invalid one (1-3 stacked
    mutations). Used by the diagnostic's ``--mutate`` mode to flood the
    rejection path: most outputs are invalid, so the two-sided contract
    (oracle rejects -> candidate must reject) gets exercised heavily."""

    @st.composite
    def _inner(draw: Any) -> str:
        result = query
        for _ in range(draw(st.integers(min_value=1, max_value=3))):
            result = draw(_mutate_once(result))
        return result

    return _inner()


# ---------------------------------------------------------------------------
# Grammar-aware mutation layer
# ---------------------------------------------------------------------------
#
# Token mutation (above) mostly yields *lexically* broken junk that both
# backends reject at the lexer / early-parse stage — cheap, but it rarely
# reaches the interesting over-acceptance boundary. Grammar-aware mutation
# corrupts at the *production* level using the grammar's own vocabulary
# (the reserved-keyword set, bracket pairs, literal forms): empty a
# bracketed argument list, turn a `{x}` placeholder into a `{}` / `{k: v}`
# dict, swap or duplicate a keyword, retype a literal, mismatch a bracket.
# The results are structurally plausible but illegal — exactly the shapes
# where one parser is liable to be more lenient than the other (both
# reject-parity bugs found this session, `from {}` and `* columns()`, are
# of this kind, where blind token edits would have to get lucky).

_BRACKET_OPENERS: dict[str, str] = {"(": ")", "{": "}", "[": "]"}
_BRACKET_CLOSERS: frozenset[str] = frozenset((")", "}", "]"))
_RESERVED_KEYWORD_TUPLE: tuple[str, ...] = tuple(sorted(_RESERVED_KEYWORDS))

# Tokens that sit right at the lexer / parser edge: ambiguous operators and
# malformed-literal shapes. Mirrors the hostile-token seeding in ClickHouse's
# own parser fuzzer grammar template.
_ADVERSARIAL_TOKENS: tuple[str, ...] = (
    "<>",
    "<=>",
    "::",
    "->",
    "||",
    "!",
    ":",
    "..",
    "1e",
    "1e-",
    "0x",
    "1.2.3",
    ".5.5",
    "''",
    "`",
    "@",
    "#",
)


def _bracket_pairs(tokens: list[str]) -> list[tuple[int, int]]:
    """`(open_index, close_index)` for each matching bracket pair. Brackets
    never occur inside HogQL string / identifier literals (their alphabets
    exclude them), so a flat scan needs no quote tracking. Inner pairs are
    listed before the outer pairs that enclose them."""
    stack: list[int] = []
    pairs: list[tuple[int, int]] = []
    for i, tok in enumerate(tokens):
        if tok in _BRACKET_OPENERS:
            stack.append(i)
        elif tok in _BRACKET_CLOSERS and stack:
            pairs.append((stack.pop(), i))
    return pairs


def _string_mask(tokens: list[str]) -> list[bool]:
    """Per-token "inside a quoted string / identifier" flag, by quote parity
    — so keyword / identifier edits skip literal contents (a string literal
    can contain a space and split across several tokens)."""
    mask: list[bool] = []
    in_squote = in_dquote = False
    for tok in tokens:
        mask.append(in_squote or in_dquote)
        if tok.count("'") % 2 == 1:
            in_squote = not in_squote
        if tok.count('"') % 2 == 1:
            in_dquote = not in_dquote
    return mask


@st.composite
def _grammar_mutate_once(draw: Any, query: str) -> str:
    """Apply one grammar-aware perturbation, returning the query unchanged
    when no operator applies."""
    tokens = [t for t in query.split(" ") if t != ""]
    if len(tokens) < 2:
        return query
    mask = _string_mask(tokens)
    pairs = _bracket_pairs(tokens)
    nonempty_pairs = [(o, c) for (o, c) in pairs if c - o > 1]
    brace_pairs = [(o, c) for (o, c) in pairs if tokens[o] == "{"]
    kw_idx = [i for i, t in enumerate(tokens) if not mask[i] and t.lower() in _RESERVED_KEYWORDS]
    ident_idx = [
        i
        for i, t in enumerate(tokens)
        if not mask[i] and t.isascii() and t.isidentifier() and t.lower() not in _RESERVED_KEYWORDS
    ]
    lit_idx = [i for i, t in enumerate(tokens) if t.lstrip("-").isdigit() or (len(t) >= 2 and t[0] == "'" == t[-1])]

    ops: list[str] = ["adversarial_inject"]  # always applicable
    if nonempty_pairs:
        ops.append("empty_brackets")
    if pairs:
        ops.append("bracket_retype")
    if brace_pairs:
        ops.append("brace_dictify")
    if kw_idx:
        ops += ["keyword_swap", "keyword_duplicate"]
    if ident_idx:
        ops.append("ident_to_keyword")
    if lit_idx:
        ops.append("literal_corrupt")
    op = draw(st.sampled_from(ops))

    if op == "empty_brackets":
        o, c = draw(st.sampled_from(nonempty_pairs))
        return " ".join(tokens[: o + 1] + tokens[c:])
    if op == "bracket_retype":
        o, c = draw(st.sampled_from(pairs))
        tokens[c] = draw(st.sampled_from([x for x in (")", "}", "]") if x != tokens[c]]))
        return " ".join(tokens)
    if op == "brace_dictify":
        o, c = draw(st.sampled_from(brace_pairs))
        inner = tokens[o + 1 : c] or ["1"]
        tokens[o : c + 1] = ["{", *inner, ":", *inner, "}"]
        return " ".join(tokens)
    if op == "keyword_swap":
        tokens[draw(st.sampled_from(kw_idx))] = draw(st.sampled_from(_RESERVED_KEYWORD_TUPLE))
        return " ".join(tokens)
    if op == "keyword_duplicate":
        i = draw(st.sampled_from(kw_idx))
        tokens.insert(i, tokens[i])
        return " ".join(tokens)
    if op == "ident_to_keyword":
        tokens[draw(st.sampled_from(ident_idx))] = draw(st.sampled_from(_RESERVED_KEYWORD_TUPLE))
        return " ".join(tokens)
    if op == "literal_corrupt":
        tokens[draw(st.sampled_from(lit_idx))] = draw(st.sampled_from(_ADVERSARIAL_TOKENS))
        return " ".join(tokens)
    # adversarial_inject
    tokens.insert(draw(st.integers(min_value=0, max_value=len(tokens))), draw(st.sampled_from(_ADVERSARIAL_TOKENS)))
    return " ".join(tokens)


def _apply_grammar_mutation(query: str) -> st.SearchStrategy[str]:
    """Perturb a valid query into a structurally-plausible invalid one with
    1-2 stacked grammar-aware mutations. Used by the diagnostic's
    ``--grammar-mutate`` mode to probe over-acceptance with near-miss shapes
    a parser is more likely to wrongly accept than lexical junk is."""

    @st.composite
    def _inner(draw: Any) -> str:
        result = query
        for _ in range(draw(st.integers(min_value=1, max_value=2))):
            result = draw(_grammar_mutate_once(result))
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
    """Return ``(accepted, ast_or_none)``. Only ``BaseHogQLError`` counts
    as rejection — that covers both grammar-level errors
    (``SyntaxError``) and visitor-level "Unsupported rule" failures
    (``NotImplementedError``), which are the legitimate "this backend
    declined to handle the input" outcomes.

    Any other exception type (``RecursionError``, ``TypeError``,
    ``AssertionError``, ``MemoryError``, …) is a real bug in the
    backend under test and is allowed to propagate so pytest records
    the failure. The whole point of the differential PBT is to surface
    asymmetric crashes; swallowing them here would defeat that.
    """
    parser_fn = parse_expr if rule == "expr" else parse_select
    try:
        node = parser_fn(query, backend=backend)  # type: ignore[arg-type]
        return True, clear_locations(node)
    except BaseHogQLError:
        return False, None


def _assert_backends_agree(query: str, rule: str) -> None:
    """Bidirectional contract: both backends must accept the same
    grammar surface, and on accepted inputs the ASTs must match
    (post-`clear_locations`).

    There is intentionally no known-bug discard list — every
    divergence the grind surfaces is a real bug in one of the two
    visitors. Drop the failing example into a regression test, fix
    the bug, and let the grind continue.
    """
    a_ok, a_ast = _try_parse(query, rule, _BACKEND_A)
    b_ok, b_ast = _try_parse(query, rule, _BACKEND_B)

    if not a_ok and not b_ok:
        # Both rejected — uninteresting; the grammar generator can
        # over-produce strings that neither visitor accepts. ``assume(False)``
        # raises ``UnsatisfiedAssumption`` to skip the example.
        assume(False)

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
    # ``too_slow`` and ``filter_too_much`` are characteristics of the
    # grind itself (deep ASTs, semantic-visitor rejections drop a
    # sizable fraction). ``data_too_large`` is deliberately *not*
    # suppressed — if it fires, the strategy is producing inputs
    # larger than Hypothesis's default buffer, which usually means an
    # unbounded path slipped past the ``_MAX_REPEAT``,
    # ``_MAX_LR_CHAIN``, or depth-decrement guards. That's a real
    # signal worth fixing rather than masking.
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
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
