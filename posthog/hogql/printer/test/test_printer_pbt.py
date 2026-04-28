import os
import math
from collections.abc import Callable
from typing import Any

import pytest

from hypothesis import (
    assume,
    given,
    settings,
    strategies as st,
)

from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import (
    POSTGRES_RESERVED_KEYWORDS,
    escape_clickhouse_identifier,
    escape_clickhouse_string,
    escape_hogql_identifier,
    escape_hogql_string,
    escape_postgres_identifier,
)
from posthog.hogql.parse_string import parse_string_literal_text

# These tests are too slow for CI. Run manually with:
#   RUN_PBT=1 pytest posthog/hogql/printer/test/test_printer_pbt.py
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_PBT"),
    reason="PBT tests are slow; set RUN_PBT=1 to run",
)

# ---------------------------------------------------------------------------
# Reusable strategies
# ---------------------------------------------------------------------------

# Strings that are expected to round-trip through escape → parse.
# NUL is excluded because parse_string_literal_text maps \0 → "" (lossy).
_roundtrip_safe_text = st.text(
    alphabet=st.characters(blacklist_characters="\0"),
)

# Like _roundtrip_safe_text but also excludes '%' (rejected by
# escape_hogql_identifier / escape_clickhouse_identifier).
_roundtrip_safe_identifier_text = st.text(
    min_size=1,
    alphabet=st.characters(blacklist_characters="\0%"),
)

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

_STRING_ESCAPE_FUNCTIONS: list[tuple[str, Callable[[Any], str]]] = [
    ("hogql", escape_hogql_string),
    ("clickhouse", escape_clickhouse_string),
]


class TestStringEscapingStructure:
    """Structural properties of string escape output."""

    @pytest.mark.parametrize("label,escape_fn", _STRING_ESCAPE_FUNCTIONS)
    @given(data=st.data())
    def test_string_always_single_quoted(self, label: str, escape_fn: Callable, data: st.DataObject) -> None:
        s = data.draw(st.text())
        result = escape_fn(s)
        assert result.startswith("'") and result.endswith("'")

    @pytest.mark.parametrize("label,escape_fn", _STRING_ESCAPE_FUNCTIONS)
    @given(data=st.data())
    def test_string_inner_quotes_always_escaped(self, label: str, escape_fn: Callable, data: st.DataObject) -> None:
        s = data.draw(st.text())
        inner = escape_fn(s)[1:-1]
        for i, ch in enumerate(inner):
            if ch == "'":
                # Count consecutive backslashes immediately before this quote.
                # An odd count means the quote itself is escaped (\');
                # an even count means the backslashes pair off (\\) and the
                # quote is bare — which would be a bug.
                n_backslashes = 0
                j = i - 1
                while j >= 0 and inner[j] == "\\":
                    n_backslashes += 1
                    j -= 1
                assert n_backslashes % 2 == 1, (
                    f"Single-quote at position {i} preceded by {n_backslashes} "
                    f"backslash(es) (even = unescaped) in: {inner!r}"
                )


class TestStringEscapingRoundTrip:
    """Round-trip: escape_*_string(s) → parse_string_literal_text → s."""

    @pytest.mark.parametrize("label,escape_fn", _STRING_ESCAPE_FUNCTIONS)
    @given(data=st.data())
    @settings(max_examples=1000)
    def test_string_roundtrip(self, label: str, escape_fn: Callable, data: st.DataObject) -> None:
        s = data.draw(_roundtrip_safe_text)
        escaped = escape_fn(s)
        assert parse_string_literal_text(escaped) == s


class TestStringEscapingKnownAsymmetries:
    """Document known cases where the round-trip is intentionally lossy."""

    def test_nul_chars_are_dropped_by_parser(self) -> None:
        escaped = escape_hogql_string("hello\0world")
        result = parse_string_literal_text(escaped)
        # parse_string_literal_text maps \0 → "" (NUL is discarded)
        assert result == "helloworld"


class TestHogQLIdentifier:
    """Property-based tests for escape_hogql_identifier."""

    @given(s=st.from_regex(r"[A-Za-z_$][A-Za-z0-9_$]*", fullmatch=True))
    def test_simple_identifiers_returned_bare(self, s: str) -> None:
        assert escape_hogql_identifier(s) == s

    @given(n=st.integers())
    def test_integer_identifiers(self, n: int) -> None:
        assert escape_hogql_identifier(n) == str(n)

    @given(s=_text_with_percent)
    def test_percent_always_rejected(self, s: str) -> None:
        with pytest.raises(QueryError, match='is not permitted as it contains the "%" character'):
            escape_hogql_identifier(s)


_BACKTICK_IDENTIFIER_FUNCTIONS: list[tuple[str, Callable[[str], str]]] = [
    ("hogql", escape_hogql_identifier),
    ("clickhouse", escape_clickhouse_identifier),
]


class TestBacktickIdentifierRoundTrip:
    """Round-trip tests shared by HogQL and ClickHouse backtick-escaped identifiers."""

    @pytest.mark.parametrize("label,escape_fn", _BACKTICK_IDENTIFIER_FUNCTIONS)
    @given(data=st.data())
    @settings(max_examples=1000)
    def test_roundtrip_through_parse_string_literal(self, label: str, escape_fn: Callable, data: st.DataObject) -> None:
        s = data.draw(_roundtrip_safe_identifier_text)
        escaped = escape_fn(s)
        if escaped.startswith("`"):
            assert parse_string_literal_text(escaped) == s
        else:
            assert escaped == s

    @pytest.mark.parametrize("label,escape_fn", _BACKTICK_IDENTIFIER_FUNCTIONS)
    @given(data=st.data())
    def test_percent_always_rejected(self, label: str, escape_fn: Callable, data: st.DataObject) -> None:
        s = data.draw(_text_with_percent)
        with pytest.raises(QueryError, match='is not permitted as it contains the "%" character'):
            escape_fn(s)


class TestClickHouseIdentifier:
    """Property-based tests specific to escape_clickhouse_identifier."""

    @given(s=st.from_regex(r"[A-Za-z_][A-Za-z0-9_]*", fullmatch=True))
    def test_simple_identifiers_returned_bare(self, s: str) -> None:
        assert escape_clickhouse_identifier(s) == s


class TestPostgresIdentifier:
    """Property-based tests for escape_postgres_identifier.

    Postgres uses double-quote escaping (not backslash escaping), so we
    verify the round-trip with a simple unquote rather than
    parse_string_literal_text (which applies ClickHouse-style backslash
    unescaping that Postgres identifiers don't use).
    """

    @given(s=st.text(min_size=1, max_size=63))
    @settings(max_examples=1000)
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
        assume(s.upper() not in POSTGRES_RESERVED_KEYWORDS)
        assert escape_postgres_identifier(s) == s

    @given(s=st.text(min_size=64, max_size=200))
    def test_rejects_identifiers_over_63_chars(self, s: str) -> None:
        with pytest.raises(QueryError, match="is too long"):
            escape_postgres_identifier(s)


class TestNumericEscaping:
    """Property-based tests for numeric value escaping."""

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
