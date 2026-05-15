"""Hand-written Hypothesis strategies for variable-content HogQL tokens.

The grammar codegen (``_grammar_codegen.py``) can resolve keyword and
punctuation tokens to literal text by reading the lexer .g4. Variable-
content tokens (identifiers, numbers, strings) need real strategies; this
file is their single source of truth. The codegen references these by
name (see ``_ESCAPE_HATCH_NAMES`` in ``_grammar_codegen.py``).

Each strategy emits a *raw token string* — quoted where the lexer expects
quoting (string literals, quoted identifiers), unquoted where it doesn't
(decimal/octal/hex/float).
"""

from __future__ import annotations

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


# Octal and hexadecimal literals fall through to a known cpp bug:
# ``visitColumnExprLiteral`` in ``common/hogql_parser/parser_json.cpp``
# calls ``std::stoll(text)`` with the default base of 10, which silently
# parses `0x1` as `0` (consuming only the leading zero before the non-
# digit `x`). The bug is documented + locked in by
# `test_pbt_hex_and_octal_literals_parse_correctly` in `_test_parser.py`
# (skipped on cpp-json via `_CPP_KNOWN_VISITOR_BUG`). The grammar PBT
# generates decimal-shaped fallbacks for these so the broader grind
# doesn't trip on a known divergence each run.
octal_literal_token: st.SearchStrategy[str] = st.integers(min_value=0, max_value=999_999).map(str)

hexadecimal_literal_token: st.SearchStrategy[str] = st.integers(min_value=0, max_value=999_999).map(str)


# Floating literal — ``DECIMAL_LITERAL DOT DEC_DIGIT* E (PLUS|DASH)? DEC_DIGIT+``
# is one valid form. We keep things simple with ``<int>.<int>e<int>``.
@st.composite
def _floating_literal(draw) -> str:  # type: ignore[no-untyped-def]
    whole = draw(st.integers(min_value=0, max_value=9999))
    frac = draw(st.integers(min_value=0, max_value=9999))
    if draw(st.booleans()):
        exp_sign = draw(st.sampled_from(["", "+", "-"]))
        exp = draw(st.integers(min_value=0, max_value=99))
        return f"{whole}.{frac}e{exp_sign}{exp}"
    return f"{whole}.{frac}"


floating_literal_token: st.SearchStrategy[str] = _floating_literal()
