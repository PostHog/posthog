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

# Binary literal per the lexer: ``BINARY_LITERAL : '0' B BIN_DIGIT+`` where B is
# case-insensitive ``b`` and BIN_DIGIT is ``[01]``.
binary_literal_token: st.SearchStrategy[str] = st.from_regex(r"0[bB][01]{1,8}", fullmatch=True)

# Octal-prefix literal: ``'0' [oO] DEC_DIGIT+``. The lexer allows 0-9 here, not
# just 0-7 — the parser / visitor rejects truly non-octal payloads downstream.
# Matching the lexer rule faithfully exercises that mismatch handling.
octal_prefix_literal_token: st.SearchStrategy[str] = st.from_regex(r"0[oO][0-9]{1,6}", fullmatch=True)


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


# ─── Variable-content tokens for HogQLX / template strings ────────────────────
# These belong to lexer modes the codegen can't resolve to literal text on its
# own. Strategies are short and conservative so the surrounding parse stays
# plausible; the surface we care about exercising is the *grammar rule*, not
# whatever arbitrary text could legally fit in the token slot.


# `f'…'` template-string start. Pushes the lexer into IN_TEMPLATE_STRING mode.
quote_single_template_token: st.SearchStrategy[str] = st.just("f'")

# `F'…'` full-template start. Pushes IN_FULL_TEMPLATE_STRING.
quote_single_template_full_token: st.SearchStrategy[str] = st.just("F'")

# `{` inside a template-string body — escapes back into expression mode for
# the embedded ``{expr}`` chunk. The closing `}` is a separate punctuation
# token the codegen already knows.
string_escape_trigger_token: st.SearchStrategy[str] = st.just("{")
full_string_escape_trigger_token: st.SearchStrategy[str] = st.just("{")

# Body text inside a `f'…'` template (the part between `f'`/`}` and `{`/`'`).
# The lexer rule excludes ``\``, ``'``, and ``{``; everything else, including
# whitespace, is fair game. Stay short for legibility.
string_text_token: st.SearchStrategy[str] = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz 0123456789", min_size=1, max_size=8
)

# Body text inside a `F'…'` full template. The lexer rule for FULL_STRING_TEXT
# only excludes ``{`` (no quote escaping), so the alphabet can include `'`.
full_string_text_token: st.SearchStrategy[str] = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz '0123456789", min_size=1, max_size=8
)

# Body text inside a HogQLX tag (`<tag>here</tag>`). HOGQLX_TEXT_TEXT excludes
# `<` and `{` (the tag and interpolation triggers).
hogqlx_text_token: st.SearchStrategy[str] = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz 0123456789", min_size=1, max_size=8
)

# Common escape sequences inside string content. Mirrors the lexer's
# ESCAPE_CHAR_COMMON alternatives (``\b``, ``\f``, ``\r``, ``\n``, ``\t``,
# ``\0``, ``\a``, ``\v``, ``\\``, ``\xHH``). Each is a complete token, so
# we sample whole sequences rather than building char-by-char.
escape_char_common_token: st.SearchStrategy[str] = st.sampled_from(
    ["\\b", "\\f", "\\r", "\\n", "\\t", "\\0", "\\a", "\\v", "\\\\", "\\x00", "\\xff", "\\xAF"]
)
