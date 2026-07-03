import pytest

from posthog.schema import AggregationAxisFormat, TrendsFilter

from products.alerts.backend.evaluation.formatting import format_aggregation_value, make_trends_value_formatter

A = AggregationAxisFormat


@pytest.mark.parametrize(
    "value,kwargs,expected",
    [
        # numeric: thousands separators + trailing-zero trimming (fixes the raw-float leak)
        (803.7740196999998, {}, "803.77"),
        (2.0, {}, "2"),
        (1234.5, {}, "1,234.5"),
        (1000.0, {}, "1,000"),
        (803.77, {"decimal_places": 0}, "804"),
        (5.0, {"min_decimal_places": 2}, "5.00"),
        (float("inf"), {}, "∞"),
        (float("-inf"), {}, "-∞"),
        # currency: symbol + fixed 2 decimals; unknown code and missing currency both degrade safely
        (803.7740196999998, {"axis_format": A.CURRENCY, "currency": "USD"}, "$803.77"),
        (10.0, {"axis_format": A.CURRENCY, "currency": "USD"}, "$10.00"),
        (1234.5, {"axis_format": A.CURRENCY, "currency": "EUR"}, "€1,234.50"),
        (1234.5, {"axis_format": A.CURRENCY, "currency": "SEK"}, "SEK 1,234.50"),
        (50.0, {"axis_format": A.CURRENCY, "currency": None}, "$50.00"),
        # prefix/postfix wrap the formatted value verbatim (they carry their own spacing)
        (1234.0, {"prefix": "$", "postfix": " reqs"}, "$1,234 reqs"),
        # currency format + redundant matching prefix must not double the symbol
        (94.02, {"axis_format": A.CURRENCY, "currency": "USD", "prefix": "$"}, "$94.02"),
        (10.0, {"axis_format": A.CURRENCY, "currency": "EUR", "prefix": "€"}, "€10.00"),
        # mismatched prefix should still apply (e.g. "USD $94.02")
        (94.02, {"axis_format": A.CURRENCY, "currency": "USD", "prefix": "USD "}, "USD $94.02"),
        # duration: seconds humanized; negative (relative differences) and zero handled
        (72.0, {"axis_format": A.DURATION}, "1m 12s"),
        (0.0, {"axis_format": A.DURATION}, "0s"),
        (-72.0, {"axis_format": A.DURATION}, "-1m 12s"),
        (3660.0, {"axis_format": A.DURATION}, "1h 1m"),
        (1500.0, {"axis_format": A.DURATION_MS}, "1.5s"),
        # percentage variants (axis %, distinct from a PERCENTAGE threshold's own rendering)
        (50.0, {"axis_format": A.PERCENTAGE}, "50%"),
        (0.5, {"axis_format": A.PERCENTAGE_SCALED}, "50%"),
        # short / compact
        (1234000.0, {"axis_format": A.SHORT}, "1.23M"),
    ],
)
def test_format_aggregation_value(value: float, kwargs: dict, expected: str) -> None:
    assert format_aggregation_value(value, **kwargs) == expected


def test_make_trends_value_formatter_reads_filter_and_currency() -> None:
    fmt = make_trends_value_formatter(TrendsFilter(aggregationAxisFormat=A.CURRENCY), "USD")
    assert fmt(803.7740196999998) == "$803.77"


def test_make_trends_value_formatter_handles_none_filter() -> None:
    fmt = make_trends_value_formatter(None, None)
    assert fmt(803.7740196999998) == "803.77"
