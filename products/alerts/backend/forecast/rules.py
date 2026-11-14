"""How an actual value compares with its forecast. Pure functions, so that every mode and direction is
testable without the gateway."""

from typing import Any, Literal, get_args

from posthog.dataclasses import frozen

Mode = Literal["band", "relative", "absolute"]
Direction = Literal["above", "below", "both"]

# The lower and upper quantile of each forecast interval that a person can pick.
BAND_QUANTILES: dict[float, tuple[float, float]] = {0.8: (0.1, 0.9), 0.9: (0.05, 0.95), 0.98: (0.01, 0.99)}
EXPECTED_QUANTILE = 0.5

DEFAULT_MODE: Mode = "band"
DEFAULT_BAND = 0.9
DEFAULT_DIRECTION: Direction = "both"

RELATIVE_THRESHOLD_REQUIRED_MESSAGE = "Set a relative threshold above 0 for relative mode."
ABSOLUTE_THRESHOLD_REQUIRED_MESSAGE = "Set an absolute threshold above 0 for absolute mode."
EXPECTED_ZERO_REASON = "The forecast expected 0, so the relative change can't be calculated and the check didn't fire."


@frozen
class ForecastRule:
    """The parts of a forecast detector config that decide whether a point fires."""

    mode: Mode = DEFAULT_MODE
    # Picks the range shown in every mode, and the fire range in band mode.
    band: float = DEFAULT_BAND
    direction: Direction = DEFAULT_DIRECTION
    # The threshold of the relative or absolute mode. None in band mode.
    threshold: float | None = None

    def __post_init__(self) -> None:
        if self.band not in BAND_QUANTILES:
            raise ValueError(f"The forecast band must be one of {sorted(BAND_QUANTILES)}, got {self.band}")
        if self.mode != "band" and (self.threshold is None or not self.threshold > 0):
            raise ValueError(
                RELATIVE_THRESHOLD_REQUIRED_MESSAGE if self.mode == "relative" else ABSOLUTE_THRESHOLD_REQUIRED_MESSAGE
            )

    @property
    def quantile_levels(self) -> "QuantileLevels":
        lower, upper = BAND_QUANTILES[self.band]
        return QuantileLevels(lower=lower, expected=EXPECTED_QUANTILE, upper=upper)


@frozen
class QuantileLevels:
    """The quantiles a rule reads from the forecast: the range ends and the expected value."""

    lower: float
    expected: float
    upper: float

    def as_list(self) -> list[float]:
        return [self.lower, self.expected, self.upper]


def forecast_rule(config: dict[str, Any]) -> ForecastRule:
    """The rule in a stored or submitted config. A missing or null field takes its default.

    Raises ``ValueError`` with a message for the alert's author when the config cannot run.
    """
    mode = config.get("mode") or DEFAULT_MODE
    direction = config.get("direction") or DEFAULT_DIRECTION
    if mode not in get_args(Mode):
        raise ValueError(f"The forecast mode must be one of {list(get_args(Mode))}, got {mode!r}")
    if direction not in get_args(Direction):
        raise ValueError(f"The forecast direction must be one of {list(get_args(Direction))}, got {direction!r}")
    threshold = config.get("relative_threshold") if mode == "relative" else config.get("absolute_threshold")
    if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, int | float)):
        threshold = None
    band = config.get("band")
    return ForecastRule(
        mode=mode,
        band=float(band) if isinstance(band, int | float) and not isinstance(band, bool) else DEFAULT_BAND,
        direction=direction,
        threshold=float(threshold) if threshold is not None and mode != "band" else None,
    )


@frozen
class ForecastComparison:
    """The forecast of one point, the actual value, and whether the point fires."""

    fires: bool
    expected: float
    lower: float
    upper: float
    actual: float
    mode: Mode
    # Why the point could not fire, whatever its distance from the forecast. None when it was compared.
    reason: str | None = None

    def persisted_metadata(self) -> dict[str, Any]:
        """What the check keeps for a person to read later. A forecast has no score."""
        metadata: dict[str, Any] = {
            "expected": self.expected,
            "lower": self.lower,
            "upper": self.upper,
            "actual": self.actual,
            "mode": self.mode,
        }
        if self.reason is not None:
            metadata["reason"] = self.reason
        return metadata


def compare(rule: ForecastRule, *, expected: float, lower: float, upper: float, actual: float) -> ForecastComparison:
    """Whether ``actual`` is far enough from the forecast, on a side the rule watches, to fire."""
    if rule.mode == "band":
        above, below = actual > upper, actual < lower
    else:
        assert rule.threshold is not None
        if rule.mode == "relative" and expected == 0:
            return ForecastComparison(
                fires=False,
                expected=expected,
                lower=lower,
                upper=upper,
                actual=actual,
                mode=rule.mode,
                reason=EXPECTED_ZERO_REASON,
            )
        distance = actual - expected
        if rule.mode == "relative":
            distance /= abs(expected)
        above, below = distance > rule.threshold, -distance > rule.threshold
    return ForecastComparison(
        fires=(above and rule.direction != "below") or (below and rule.direction != "above"),
        expected=expected,
        lower=lower,
        upper=upper,
        actual=actual,
        mode=rule.mode,
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
