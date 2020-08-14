from enum import Enum


class Interval(str, Enum):
    """Analytics interval, used in date_trunc and the like."""

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class CachedEndpoint(str, Enum):
    """Cached endpoint type."""

    TRENDS = "Trends"
    FUNNEL_STEPS = "FunnelSteps"


class DisplayMode(str, Enum):
    """Insight display mode."""

    FUNNEL_STEPS = "FunnelSteps"
    FUNNEL_TRENDS = "FunnelTrends"


TREND_FILTER_TYPE_ACTIONS = "actions"
TREND_FILTER_TYPE_EVENTS = "events"

TRENDS_CUMULATIVE = "ActionsLineGraphCumulative"
TRENDS_LINEAR = "ActionsLineGraph"

TRENDS_STICKINESS = "Stickiness"
