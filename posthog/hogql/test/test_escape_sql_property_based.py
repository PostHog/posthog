import math

import pytest

from hypothesis import (
    assume,
    given,
    settings,
    strategies as st,
)

from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import (
    escape_clickhouse_identifier,
    escape_clickhouse_string,
    escape_hogql_identifier,
    escape_hogql_string,
    escape_postgres_identifier,
)
from posthog.hogql.parse_string import parse_string_literal_text

# Characters that, when preceded by a backslash, form escape sequences
# recognized by replace_common_escape_characters. Because that function
# uses sequential str.replace (rather than left-to-right single-pass
# parsing), a literal backslash followed by one of these chars in the
# original string doesn't survive a round-trip through escape → parse.
_ESCAPE_SEQUENCE_LETTERS = frozenset("bfrnt0av")


def _has_backslash_before_escape_letter(s: str) -> bool:
    """True if s contains '\\' immediately followed by an escape letter."""
    for i in range(len(s) - 1):
        if s[i] == "\\" and s[i + 1] in _ESCAPE_SEQUENCE_LETTERS:
            return True
    return False


# ---------------------------------------------------------------------------
# Reusable strategies
# ---------------------------------------------------------------------------

# Strings that are expected to round-trip through escape → parse:
#   - no NUL (parse_string_literal_text maps \\0 → empty, so NUL is lossy)
#   - no backslash + escape-letter combos (see docstring above)
_roundtrip_safe_text = st.text(
    alphabet=st.characters(blacklist_characters="\0"),
).filter(lambda s: not _has_backslash_before_escape_letter(s))

_simple_hogql_identifier = st.from_regex(r"[A-Za-z_$][A-Za-z0-9_$]*", fullmatch=True)

_no_percent_nonempty = st.text(min_size=1).filter(lambda s: "%" not in s)

# Strings guaranteed to contain at least one '%' — built by
# concatenating a random prefix, a '%', and a random suffix so
# Hypothesis doesn't waste time filtering.
_text_with_percent = st.builds(
    lambda prefix, suffix: prefix + "%" + suffix,
    prefix=st.text(),
    suffix=st.text(),
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStringEscapingStructure:
    """Structural properties of string escape output."""

    @given(s=st.text())
    def test_hogql_string_always_single_quoted(self, s: str) -> None:
        result = escape_hogql_string(s)
        assert result.startswith("'") and result.endswith("'")

    @given(s=st.text())
    def test_clickhouse_string_always_single_quoted(self, s: str) -> None:
        result = escape_clickhouse_string(s)
        assert result.startswith("'") and result.endswith("'")

    @given(s=st.text())
    def test_hogql_string_inner_quotes_always_escaped(self, s: str) -> None:
        inner = escape_hogql_string(s)[1:-1]
        i = 0
        while i < len(inner):
            if inner[i] == "'":
                assert i > 0 and inner[i - 1] == "\\", (
                    f"Unescaped single-quote at position {i} in escaped form: {inner!r}"
                )
            i += 1

    @given(s=st.text())
    def test_clickhouse_string_inner_quotes_always_escaped(self, s: str) -> None:
        inner = escape_clickhouse_string(s)[1:-1]
        i = 0
        while i < len(inner):
            if inner[i] == "'":
                assert i > 0 and inner[i - 1] == "\\", (
                    f"Unescaped single-quote at position {i} in escaped form: {inner!r}"
                )
            i += 1


class TestStringEscapingRoundTrip:
    """Round-trip: escape_*_string(s) → parse_string_literal_text → s."""

    @given(s=_roundtrip_safe_text)
    @settings(max_examples=500)
    def test_hogql_string_roundtrip(self, s: str) -> None:
        escaped = escape_hogql_string(s)
        assert parse_string_literal_text(escaped) == s

    @given(s=_roundtrip_safe_text)
    @settings(max_examples=500)
    def test_clickhouse_string_roundtrip(self, s: str) -> None:
        escaped = escape_clickhouse_string(s)
        assert parse_string_literal_text(escaped) == s


class TestStringEscapingKnownAsymmetries:
    """Document known cases where the round-trip is intentionally lossy."""

    def test_nul_chars_are_dropped_by_parser(self) -> None:
        escaped = escape_hogql_string("hello\0world")
        result = parse_string_literal_text(escaped)
        # parse_string_literal_text maps \\0 → "" (NUL is discarded)
        assert result == "helloworld"

    def test_backslash_before_escape_letter_is_lossy(self) -> None:
        # Literal backslash + 'n' (two chars, NOT a newline)
        s = "\\n"
        escaped = escape_hogql_string(s)
        result = parse_string_literal_text(escaped)
        # replace_common_escape_characters sees the \\n at the boundary
        # between the escaped backslash and the literal 'n', and
        # interprets it as a newline escape sequence.
        assert result != s
        assert result == "\\\n"  # backslash + newline, not backslash + 'n'


class TestHogQLIdentifier:
    """Property-based tests for escape_hogql_identifier."""

    @given(s=_simple_hogql_identifier)
    def test_simple_identifiers_returned_bare(self, s: str) -> None:
        assert escape_hogql_identifier(s) == s

    @given(n=st.integers(min_value=0, max_value=10_000))
    def test_integer_identifiers(self, n: int) -> None:
        assert escape_hogql_identifier(n) == str(n)

    @given(s=_no_percent_nonempty)
    @settings(max_examples=500)
    def test_roundtrip_through_parse_string_literal(self, s: str) -> None:
        assume("\0" not in s)
        assume(not _has_backslash_before_escape_letter(s))

        escaped = escape_hogql_identifier(s)
        if escaped.startswith("`"):
            assert parse_string_literal_text(escaped) == s
        else:
            # Bare identifier — returned as-is
            assert escaped == s

    @given(s=_text_with_percent)
    def test_percent_always_rejected(self, s: str) -> None:
        with pytest.raises(QueryError, match='is not permitted as it contains the "%" character'):
            escape_hogql_identifier(s)


class TestClickHouseIdentifier:
    """Property-based tests for escape_clickhouse_identifier."""

    @given(s=st.from_regex(r"[A-Za-z_][A-Za-z0-9_]*", fullmatch=True))
    def test_simple_identifiers_returned_bare(self, s: str) -> None:
        assert escape_clickhouse_identifier(s) == s

    @given(s=_no_percent_nonempty)
    @settings(max_examples=500)
    def test_roundtrip_through_parse_string_literal(self, s: str) -> None:
        assume("\0" not in s)
        assume(not _has_backslash_before_escape_letter(s))

        escaped = escape_clickhouse_identifier(s)
        if escaped.startswith("`"):
            assert parse_string_literal_text(escaped) == s
        else:
            assert escaped == s

    @given(s=_text_with_percent)
    def test_percent_always_rejected(self, s: str) -> None:
        with pytest.raises(QueryError, match='is not permitted as it contains the "%" character'):
            escape_clickhouse_identifier(s)


class TestPostgresIdentifier:
    """Property-based tests for escape_postgres_identifier.

    Postgres uses double-quote escaping (not backslash escaping), so we
    verify the round-trip with a simple unquote rather than
    parse_string_literal_text (which applies ClickHouse-style backslash
    unescaping that Postgres identifiers don't use).
    """

    @given(s=st.text(min_size=1, max_size=63))
    @settings(max_examples=500)
    def test_roundtrip(self, s: str) -> None:
        escaped = escape_postgres_identifier(s)
        if escaped.startswith('"'):
            # Double-quoted: strip quotes and unescape "" → "
            inner = escaped[1:-1]
            assert inner.replace('""', '"') == s
        else:
            assert escaped == s

    @given(s=st.from_regex(r"[a-z_][a-z0-9_$]*", fullmatch=True).filter(lambda s: len(s) <= 63))
    def test_simple_identifiers_returned_bare(self, s: str) -> None:
        from posthog.hogql.escape_sql import POSTGRES_RESERVED_KEYWORDS

        assume(s.upper() not in POSTGRES_RESERVED_KEYWORDS)
        assert escape_postgres_identifier(s) == s

    @given(s=st.text(min_size=64, max_size=200))
    def test_rejects_identifiers_over_63_chars(self, s: str) -> None:
        with pytest.raises(QueryError, match="is too long"):
            escape_postgres_identifier(s)

    @given(s=st.text(min_size=1, max_size=63))
    def test_output_never_empty(self, s: str) -> None:
        result = escape_postgres_identifier(s)
        assert len(result) > 0


class TestFloatEscaping:
    """Property-based tests for float value escaping."""

    @given(f=st.floats(allow_nan=False, allow_infinity=False))
    def test_finite_floats_parse_back(self, f: float) -> None:
        result = escape_hogql_string(f)
        parsed = float(result)
        if f == 0.0:
            assert parsed == 0.0
        else:
            assert math.isclose(parsed, f, rel_tol=1e-15)

    def test_nan(self) -> None:
        assert escape_hogql_string(float("nan")) == "NaN"

    def test_positive_inf(self) -> None:
        assert escape_hogql_string(float("inf")) == "Inf"

    def test_negative_inf(self) -> None:
        assert escape_hogql_string(float("-inf")) == "-Inf"

    @given(n=st.integers(min_value=-(10**18), max_value=10**18))
    def test_integer_values_roundtrip(self, n: int) -> None:
        result = escape_hogql_string(n)
        assert int(result) == n
