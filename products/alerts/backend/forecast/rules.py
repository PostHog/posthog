"""How an actual value compares with its forecast. Pure functions, so that every side rule is testable
without the gateway."""

import math
from typing import Any, Literal

from posthog.dataclasses import frozen
from posthog.llm.forecast_client import QUANTILE_LEVELS

Side = Literal["above", "below"]

EXPECTED_QUANTILE = 0.5
UPPER_QUANTILES = tuple(sorted(level for level in QUANTILE_LEVELS if level > EXPECTED_QUANTILE))
LOWER_QUANTILES = tuple(sorted(level for level in QUANTILE_LEVELS if level < EXPECTED_QUANTILE))

# The range shown for a side with no quantile, and the fire range of each side when neither side is set.
DEFAULT_UPPER_QUANTILE = 0.99
DEFAULT_LOWER_QUANTILE = 0.01

_CONFIG_FIELDS = frozenset({"type", "above", "below"})
_SIDE_FIELDS = ("quantile", "min_relative_change", "min_absolute_change")

EXPECTED_ZERO_REASON = "The forecast expected 0, so the relative change can't be calculated and the check didn't fire."


@frozen
class SideRule:
    """The conditions for one side of the forecast. The side fires when every condition it sets is true."""

    quantile: float | None = None
    min_relative_change: float | None = None
    min_absolute_change: float | None = None


@frozen
class ForecastRule:
    """The parts of a forecast detector config that decide whether a point fires. None ignores that side."""

    above: SideRule | None
    below: SideRule | None

    @property
    def quantile_levels(self) -> "QuantileLevels":
        upper = self.above.quantile if self.above is not None and self.above.quantile is not None else None
        lower = self.below.quantile if self.below is not None and self.below.quantile is not None else None
        return QuantileLevels(
            lower=DEFAULT_LOWER_QUANTILE if lower is None else lower,
            expected=EXPECTED_QUANTILE,
            upper=DEFAULT_UPPER_QUANTILE if upper is None else upper,
        )


DEFAULT_RULE = ForecastRule(
    above=SideRule(quantile=DEFAULT_UPPER_QUANTILE), below=SideRule(quantile=DEFAULT_LOWER_QUANTILE)
)


@frozen
class QuantileLevels:
    """The quantiles a rule reads from the forecast: the range ends and the expected value."""

    lower: float
    expected: float
    upper: float

    def as_list(self) -> list[float]:
        return [self.lower, self.expected, self.upper]


def _format_levels(levels: tuple[float, ...]) -> str:
    return ", ".join(f"{level:g}" for level in levels)


def _number(side: Side, field: str, value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{side}.{field} must be a number.")
    try:
        number = float(value)
    except OverflowError:
        # JSON accepts an integer of any size, and one too large for a float would otherwise escape as a 500.
        number = math.inf
    if not math.isfinite(number):
        raise ValueError(f"{side}.{field} must be a number.")
    return number


def _side_rule(side: Side, raw: Any) -> SideRule | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{side} must be an object with quantile, min_relative_change or min_absolute_change.")
    unknown = sorted(set(raw) - set(_SIDE_FIELDS))
    if unknown:
        raise ValueError(f"Unknown field in {side}: {', '.join(unknown)}.")
    quantile, min_relative_change, min_absolute_change = (
        _number(side, field, raw.get(field)) for field in _SIDE_FIELDS
    )
    if quantile is None and min_relative_change is None and min_absolute_change is None:
        raise ValueError(f"{side} needs at least one condition: quantile, min_relative_change or min_absolute_change.")

    if quantile is not None:
        if side == "above" and quantile <= EXPECTED_QUANTILE:
            raise ValueError(f"above.quantile is an upper level, so it must be above 0.5. Got {quantile:g}.")
        if side == "below" and quantile >= EXPECTED_QUANTILE:
            raise ValueError(f"below.quantile is a lower level, so it must be below 0.5. Got {quantile:g}.")
        levels = UPPER_QUANTILES if side == "above" else LOWER_QUANTILES
        if quantile not in levels:
            raise ValueError(f"{side}.quantile must be one of {_format_levels(levels)}. Got {quantile:g}.")
    for field, threshold in (
        ("min_relative_change", min_relative_change),
        ("min_absolute_change", min_absolute_change),
    ):
        if threshold is not None and not threshold > 0:
            raise ValueError(f"{side}.{field} must be above 0.")
    if side == "below" and min_relative_change is not None and min_relative_change > 1:
        raise ValueError(
            "A value can't be more than 100% below the expected value, so below.min_relative_change must be 1 or less."
        )
    return SideRule(quantile=quantile, min_relative_change=min_relative_change, min_absolute_change=min_absolute_change)


def forecast_rule(config: dict[str, Any]) -> ForecastRule:
    """The rule in a stored or submitted config. A missing or null side is ignored, and with neither side
    set the rule watches the default range on both sides.

    Raises ``ValueError`` with a message for the alert's author when the config cannot run.
    """
    unknown = sorted(set(config) - _CONFIG_FIELDS)
    if unknown:
        raise ValueError(f"Unknown field in the forecast detector: {', '.join(unknown)}.")
    above, below = _side_rule("above", config.get("above")), _side_rule("below", config.get("below"))
    if above is None and below is None:
        return DEFAULT_RULE
    return ForecastRule(above=above, below=below)


@frozen
class ForecastComparison:
    """The forecast of one point, the actual value, and whether the point fires."""

    fires: bool
    expected: float
    lower: float
    upper: float
    lower_quantile: float
    upper_quantile: float
    actual: float
    # The side that fired. None when the point did not fire.
    side: Side | None = None
    # Why the point could not fire, whatever its distance from the forecast. None when it was compared.
    reason: str | None = None

    def persisted_metadata(self) -> dict[str, Any]:
        """What the check keeps for a person to read later. A forecast has no score."""
        metadata: dict[str, Any] = {
            "expected": self.expected,
            "lower": self.lower,
            "upper": self.upper,
            "lower_quantile": self.lower_quantile,
            "upper_quantile": self.upper_quantile,
            "actual": self.actual,
        }
        if self.side is not None:
            metadata["side"] = self.side
        if self.reason is not None:
            metadata["reason"] = self.reason
        return metadata


def _side_fires(rule: SideRule, *, distance: float, beyond_quantile: bool, expected: float) -> bool:
    """``distance`` is how far the actual value is from the expected value toward this side. It is
    negative when the actual value is on the other side."""
    if rule.quantile is not None and not beyond_quantile:
        return False
    if rule.min_absolute_change is not None and not distance >= rule.min_absolute_change:
        return False
    if rule.min_relative_change is not None and (
        expected == 0 or not distance / abs(expected) >= rule.min_relative_change
    ):
        return False
    return True


def compare(rule: ForecastRule, *, expected: float, lower: float, upper: float, actual: float) -> ForecastComparison:
    """Whether ``actual`` is far enough from the forecast, on a side the rule watches, to fire.

    ``lower`` and ``upper`` are the forecast at the rule's ``quantile_levels``.
    """
    side: Side | None = None
    if rule.above is not None and _side_fires(
        rule.above, distance=actual - expected, beyond_quantile=actual > upper, expected=expected
    ):
        side = "above"
    elif rule.below is not None and _side_fires(
        rule.below, distance=expected - actual, beyond_quantile=actual < lower, expected=expected
    ):
        side = "below"

    # A relative condition can't be evaluated against a forecast of 0. Say so when it is why the
    # side the actual value is on did not fire.
    side_of_actual = rule.above if actual > expected else rule.below if actual < expected else None
    blocked_by_zero = (
        side is None and expected == 0 and side_of_actual is not None and side_of_actual.min_relative_change is not None
    )
    levels = rule.quantile_levels
    return ForecastComparison(
        fires=side is not None,
        expected=expected,
        lower=lower,
        upper=upper,
        lower_quantile=levels.lower,
        upper_quantile=levels.upper,
        actual=actual,
        side=side,
        reason=EXPECTED_ZERO_REASON if blocked_by_zero else None,
    )


def format_forecast_value(value: float) -> str:
    """A value for the breach message, with thousands separators and at most two decimals."""
    formatted = f"{value:,.2f}"
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def breach_detail(comparison: ForecastComparison) -> str:
    return (
        f"expected about {format_forecast_value(comparison.expected)} "
        f"({format_forecast_value(comparison.lower)} to {format_forecast_value(comparison.upper)}), "
        f"got {format_forecast_value(comparison.actual)}"
    )
