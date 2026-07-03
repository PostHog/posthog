"""Format alert-breach values and breakdown labels the way the insight itself displays them.

This is a backend port of the frontend `formatAggregationAxisValue`
(`frontend/src/scenes/insights/aggregationAxisFormat.ts`): given a trends insight's axis config
(`aggregationAxisFormat`, prefix/postfix, decimal places) plus the team's base currency, render a
raw metric value as the user sees it on the chart — so notification messages read "($803.77)" and
"(Other (i.e. all remaining values))" instead of "(803.7740196999998)" and a raw breakdown sentinel.
"""

import math
from collections.abc import Callable

from posthog.schema import AggregationAxisFormat, TrendsFilter

from posthog.utils import compact_number

DEFAULT_DECIMAL_PLACES = 2

# en-US currency symbols for common currencies, mirroring the Intl.NumberFormat('en-US') output the
# frontend's formatCurrency relies on. Unlisted currencies fall back to a "<CODE> " prefix, and a
# missing currency falls back to "$" (matching the frontend humanFriendlyCurrency fallback).
_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "CN¥",
    "INR": "₹",
    "KRW": "₩",
    "RUB": "₽",
    "BRL": "R$",
    "CAD": "CA$",
    "AUD": "A$",
    "NZD": "NZ$",
    "HKD": "HK$",
    "SGD": "S$",
    "MXN": "MX$",
    "TRY": "₺",
    "THB": "฿",
    "PHP": "₱",
    "IDR": "Rp",
    "ILS": "₪",
    "ZAR": "R",
    "CHF": "CHF ",
    "SEK": "SEK ",
    "NOK": "NOK ",
    "DKK": "DKK ",
    "PLN": "PLN ",
    "AED": "AED ",
    "SAR": "SAR ",
}


def make_trends_value_formatter(trends_filter: TrendsFilter | None, currency: str | None) -> Callable[[float], str]:
    """Bind a trends insight's axis config into a one-arg value formatter for the comparator.

    Tolerates ``trends_filter=None`` (a valid trends query state) by rendering a plain humanized number.
    """
    axis_format = trends_filter.aggregationAxisFormat if trends_filter else None
    prefix = trends_filter.aggregationAxisPrefix if trends_filter else None
    postfix = trends_filter.aggregationAxisPostfix if trends_filter else None
    decimal_places = trends_filter.decimalPlaces if trends_filter else None
    min_decimal_places = trends_filter.minDecimalPlaces if trends_filter else None

    def _format(value: float) -> str:
        return format_aggregation_value(
            value,
            axis_format=axis_format,
            prefix=prefix,
            postfix=postfix,
            decimal_places=decimal_places,
            min_decimal_places=min_decimal_places,
            currency=currency,
        )

    return _format


def format_aggregation_value(
    value: float,
    *,
    axis_format: AggregationAxisFormat | None = None,
    prefix: str | None = None,
    postfix: str | None = None,
    decimal_places: float | None = None,
    min_decimal_places: float | None = None,
    currency: str | None = None,
) -> str:
    """Render a single metric value per the insight's axis format, wrapped in its prefix/postfix."""
    if not math.isfinite(value):
        formatted = "∞" if value > 0 else "-∞" if value < 0 else "NaN"
        return f"{prefix or ''}{formatted}{postfix or ''}"

    match axis_format:
        case AggregationAxisFormat.DURATION:
            formatted = _format_duration_seconds(value)
        case AggregationAxisFormat.DURATION_MS:
            formatted = _format_duration_seconds(value / 1000, seconds_fixed=1)
        case AggregationAxisFormat.PERCENTAGE:
            formatted = _percentage(value / 100, decimal_places)
        case AggregationAxisFormat.PERCENTAGE_SCALED:
            formatted = _percentage(value, decimal_places)
        case AggregationAxisFormat.CURRENCY:
            formatted = _format_currency(value, currency)
        case AggregationAxisFormat.SHORT:
            formatted = compact_number(value)
        case _:  # NUMERIC or unset
            formatted = _human_friendly_number(value, decimal_places, min_decimal_places)

    return f"{prefix or ''}{formatted}{postfix or ''}"


def _clamp_decimal_places(value: float | None, fallback: int) -> int:
    """Mirror the frontend validateFractionDigits: only accept a whole number in [0, 100]."""
    if value is None:
        return fallback
    as_int = int(value)
    if as_int != value or as_int < 0 or as_int > 100:
        return fallback
    return as_int


def _human_friendly_number(
    value: float, max_decimal_places: float | None = None, min_decimal_places: float | None = None
) -> str:
    """Thousands-separated number, trimming trailing zeros down to min_decimal_places.

    Port of the frontend humanFriendlyNumber (`(n).toLocaleString('en-US', {...})`).
    """
    max_dp = _clamp_decimal_places(max_decimal_places, DEFAULT_DECIMAL_PLACES)
    min_dp = _clamp_decimal_places(min_decimal_places, 0)
    if min_dp > max_dp:
        min_dp = max_dp

    formatted = f"{value:,.{max_dp}f}"
    if "." not in formatted:
        return formatted
    integer_part, _, frac = formatted.partition(".")
    frac = frac.rstrip("0")
    if len(frac) < min_dp:
        frac = frac.ljust(min_dp, "0")
    return f"{integer_part}.{frac}" if frac else integer_part


def _percentage(division: float, max_decimal_places: float | None = None) -> str:
    """Render a fraction as a percentage, e.g. 0.5 -> "50%" (port of the frontend percentage())."""
    if not math.isfinite(division):
        return "∞%" if division > 0 else "-∞%" if division < 0 else "NaN%"
    return f"{_human_friendly_number(division * 100, max_decimal_places, 0)}%"


def _format_currency(value: float, currency: str | None) -> str:
    """Prefix the humanized number (fixed 2 decimals, like the frontend formatCurrency) with the
    currency symbol. Unknown currencies fall back to the code; a missing currency falls back to "$"."""
    number = _human_friendly_number(value, DEFAULT_DECIMAL_PLACES, DEFAULT_DECIMAL_PLACES)
    if not currency:
        return f"${number}"
    symbol = _CURRENCY_SYMBOLS.get(currency.upper())
    if symbol is not None:
        return f"{symbol}{number}"
    return f"{currency.upper()} {number}"


def _format_duration_seconds(value: float, *, seconds_fixed: int | None = None) -> str:
    """Convert seconds to a human-readable duration ("45s", "2m 12s", "1h 4m", "850ms").

    Port of the frontend humanFriendlyDuration; handles negative (relative differences) and zero.
    """
    if value < 0:
        return f"-{_format_duration_seconds(-value, seconds_fixed=seconds_fixed)}"
    if value == 0:
        return "0s"
    if value < 1:
        return f"{round(value * 1000)}ms"
    if value < 60:
        return f"{_trim_float(f'{value:.{seconds_fixed or 0}f}')}s"

    days = math.floor(value / 86400)
    hours = math.floor((value % 86400) / 3600)
    minutes = math.floor((value % 3600) / 60)
    seconds = math.floor((value % 3600) % 60)

    day_display = f"{days}d" if days > 0 else ""
    hour_display = f"{hours}h" if hours > 0 else ""
    minute_display = f"{minutes}m" if minutes > 0 else ""
    second_display = f"{seconds}s" if seconds > 0 else ("" if (hour_display or minute_display) else "0s")

    if days > 0:
        units = [u for u in (day_display, hour_display) if u]
    else:
        units = [u for u in (hour_display, minute_display, second_display) if u]
    return " ".join(units)


def _trim_float(formatted: str) -> str:
    """Strip trailing zeros (and a bare trailing dot) from a fixed-point string, like JS parseFloat."""
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted
