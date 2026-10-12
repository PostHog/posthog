from datetime import timedelta
from typing import Any

from posthog.dataclasses import frozen
from posthog.schema_enums import IntervalType
from posthog.tasks.alerts.detectors.statistical.zscore import ZScoreDetector

from products.alerts.backend.models import InsightAnomalyConfig

DEFAULT_ENABLED = True
DEFAULT_MAX_BREAKDOWNS = 10

# The scorer needs a longer baseline than the chart usually renders. Intervals not listed here
# are not scored.
DEFAULT_LOOKBACK_BY_INTERVAL: dict[IntervalType, timedelta] = {
    IntervalType.HOUR: timedelta(days=28),
    IntervalType.DAY: timedelta(days=120),
    IntervalType.WEEK: timedelta(days=730),
}


def default_detector_config() -> dict[str, Any]:
    return ZScoreDetector.get_default_config()


@frozen
class EffectiveAnomalyConfig:
    enabled: bool
    detector_config: dict[str, Any]
    max_breakdowns: int

    def lookback_for(self, interval: IntervalType) -> timedelta | None:
        return DEFAULT_LOOKBACK_BY_INTERVAL.get(interval)


def effective_config(override: InsightAnomalyConfig | None) -> EffectiveAnomalyConfig:
    enabled = DEFAULT_ENABLED
    # Replaced whole, never merged key by key: keys from one detector type are invalid for another.
    detector_config = default_detector_config()
    if override is not None:
        if override.enabled is not None:
            enabled = override.enabled
        if override.detector_config:
            detector_config = override.detector_config
    return EffectiveAnomalyConfig(
        enabled=enabled,
        detector_config=detector_config,
        max_breakdowns=DEFAULT_MAX_BREAKDOWNS,
    )
