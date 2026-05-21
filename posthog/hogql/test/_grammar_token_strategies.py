"""Hand-written Hypothesis strategies for variable-content HogQL tokens.

The grammar codegen (``posthog/hogql/scripts/build_grammar_strategies.py``)
can resolve keyword and punctuation tokens to literal text by reading
the lexer .g4. Variable-content tokens (identifiers, numbers, strings)
need real strategies; this file is their single source of truth. The
codegen references these by name (see ``_ESCAPE_HATCH_NAMES`` in
``build_grammar_strategies.py``).

Each strategy emits a *raw token string* — quoted where the lexer expects
quoting (string literals, quoted identifiers), unquoted where it doesn't
(decimal/octal/hex/float).
"""

from __future__ import annotations

from typing import Any

from hypothesis import strategies as st

# All HogQL reserved keywords (hand-mirrored from HogQLParser.g4's
# ``keyword`` rule plus the case-insensitive booleans/null). An unquoted
# identifier must not collide with one of these.
_RESERVED_KEYWORDS: frozenset[str] = frozenset(
    s.lower()
    for s in (
        "ALL",
        "AND",
        "ANTI",
        "ANY",
        "ARRAY",
        "AS",
        "ASCENDING",
        "ASOF",
        "BETWEEN",
        "BOTH",
        "BY",
        "CASE",
        "CAST",
        "COHORT",
        "COLLATE",
        "COLUMNS",
        "CROSS",
        "CUBE",
        "CURRENT",
        "DATE",
        "DESC",
        "DESCENDING",
        "DISTINCT",
        "ELSE",
        "END",
        "EXCLUDE",
        "EXTRACT",
        "FILL",
        "FILTER",
        "FINAL",
        "FIRST",
        "FOR",
        "FOLLOWING",
        "FROM",
        "FULL",
        "GROUP",
        "HAVING",
        "ID",
        "INTERPOLATE",
        "IS",
        "GROUPING",
        "IF",
        "IGNORE",
        "ILIKE",
        "INCLUDE",
        "IN",
        "INNER",
        "INTERVAL",
        "JOIN",
        "KEY",
        "LAMBDA",
        "LAST",
        "LEADING",
        "LEFT",
        "LIKE",
        "LIMIT",
        "LOCAL",
        "NAME",
        "NATURAL",
        "NOT",
        "NULLS",
        "OFFSET",
        "ON",
        "OR",
        "ORDER",
        "OUTER",
        "OVER",
        "PARTITION",
        "PIVOT",
        "POSITIONAL",
        "PRECEDING",
        "PREWHERE",
        "QUALIFY",
        "RANGE",
        "RECURSIVE",
        "REPLACE",
        "RETURN",
        "RIGHT",
        "ROLLUP",
        "ROW",
        "ROWS",
        "SAMPLE",
        "SELECT",
        "SEMI",
        "SETS",
        "SETTINGS",
        "STEP",
        "SUBSTRING",
        "THEN",
        "TIES",
        "TIME",
        "TIMESTAMP",
        "TOTALS",
        "TRAILING",
        "TRIM",
        "TRUNCATE",
        "TRY_CAST",
        "TO",
        "TOP",
        "UNBOUNDED",
        "UNION",
        "UNPIVOT",
        "USING",
        "VALUES",
        "WHEN",
        "WHERE",
        "WINDOW",
        "WITH",
        "ZONE",
        "NULL",
        "INF",
        "NAN",
        "SECOND",
        "MINUTE",
        "HOUR",
        "DAY",
        "WEEK",
        "MONTH",
        "QUARTER",
        "YEAR",
        "TRUE",
        "FALSE",
        "TEAM_ID",
        "FN",
        "FUN",
        "LET",
        "THROW",
        "TRY",
        "CATCH",
        "FINALLY",
        "WHILE",
        "MATERIALIZED",
    )
)


# Plain unquoted identifier per the lexer:
#   IDENTIFIER : (LETTER | UNDERSCORE | DOLLAR) (LETTER | UNDERSCORE | DEC_DIGIT | DOLLAR)*
# We restrict to lowercase ASCII + digits + underscore to keep the
# generated strings recognisable; that's still a valid HogQL identifier.
identifier_token: st.SearchStrategy[str] = st.from_regex(r"[a-z][a-z0-9_]{0,7}", fullmatch=True).filter(
    lambda s: s.lower() not in _RESERVED_KEYWORDS
)


# Quoted identifier: double-quoted form. The lexer also accepts
# backquoted, but mixing in a smoke test only complicates things.
# The alphabet deliberately includes space — quoted identifiers can
# legally contain whitespace (``"abc def"`` is one identifier), and
# the jiggler-layer guards (``_whitespace_jiggle``, ``_comment_jiggle``)
# track ``"`` quoting so they don't break identifiers like that. The
# unquoted ``identifier_token`` above has no such allowance and must
# also dodge ``_RESERVED_KEYWORDS``; quoted identifiers ignore both.
quoted_identifier_token: st.SearchStrategy[str] = st.text(alphabet="abcdefghijklmnopq _", min_size=1, max_size=8).map(
    lambda s: f'"{s}"'
)


# Single-quoted string literal with no escapes — keep simple for the
# initial smoke. The codegen will pull this in for STRING_LITERAL
# references everywhere they occur (column expressions, DATE 'literal',
# settings clauses, etc.).
string_literal_token: st.SearchStrategy[str] = st.text(alphabet="abcdefghijklmnop ", min_size=0, max_size=8).map(
    lambda s: "'" + s + "'"
)


# Decimal integer literal — must be non-negative; sign is handled by the
# parser as unary minus.
decimal_literal_token: st.SearchStrategy[str] = st.integers(min_value=0, max_value=999_999).map(str)


# Octal and hexadecimal literals per the lexer:
#   OCTAL_LITERAL       : '0' OCT_DIGIT+    -- OCT_DIGIT = [0-7]
#   HEXADECIMAL_LITERAL : '0' [xX] HEX_DIGIT+
# Emit real ``0...`` / ``0x...`` text rather than decimal-shaped
# fallbacks so the PBT actually exercises these productions. There is
# a known cpp visitor bug — ``visitColumnExprLiteral`` in
# ``common/hogql_parser/parser_json.cpp`` calls ``std::stoll(text)``
# with the default base of 10 and so silently parses ``0x1F`` as ``0``
# — which makes the comparison fail at this token on the buggy wheel.
# That divergence is the whole point: it's the bidirectional contract
# in ``_assert_backends_agree`` doing its job, the same outcome we
# wanted when ``_CPP_KNOWN_BUG_PATTERNS`` was dropped. The cpp fix
# landed upstream in ``common/hogql_parser`` 1.3.42; once
# ``pyproject.toml`` pins that wheel (or newer), these draws will
# stop tripping the divergence.
octal_literal_token: st.SearchStrategy[str] = st.from_regex(r"0[0-7]{1,6}", fullmatch=True)

hexadecimal_literal_token: st.SearchStrategy[str] = st.from_regex(r"0[xX][0-9a-fA-F]{1,6}", fullmatch=True)


# Floating literal — ``DECIMAL_LITERAL DOT DEC_DIGIT* E (PLUS|DASH)? DEC_DIGIT+``
# is one valid form. We keep things simple with ``<int>.<int>e<int>``.
@st.composite
def _floating_literal(draw: Any) -> str:
    whole = draw(st.integers(min_value=0, max_value=9999))
    frac = draw(st.integers(min_value=0, max_value=9999))
    if draw(st.booleans()):
        exp_sign = draw(st.sampled_from(["", "+", "-"]))
        exp = draw(st.integers(min_value=0, max_value=99))
        return f"{whole}.{frac}e{exp_sign}{exp}"
    return f"{whole}.{frac}"


floating_literal_token: st.SearchStrategy[str] = _floating_literal()
