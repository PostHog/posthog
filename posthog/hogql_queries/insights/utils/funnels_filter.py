from posthog.constants import FUNNEL_WINDOW_INTERVAL_TYPES
from rest_framework.exceptions import ValidationError

from posthog.schema import FunnelConversionWindowTimeUnit


def funnel_window_interval_unit_to_sql(
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | None,
) -> FUNNEL_WINDOW_INTERVAL_TYPES:
    if funnelWindowIntervalUnit is None:
        return "DAY"
    elif funnelWindowIntervalUnit == "second":
        return "SECOND"
    elif funnelWindowIntervalUnit == "minute":
        return "MINUTE"
    elif funnelWindowIntervalUnit == "hour":
        return "HOUR"
    elif funnelWindowIntervalUnit == "week":
        return "WEEK"
    elif funnelWindowIntervalUnit == "month":
        return "MONTH"
    elif funnelWindowIntervalUnit == "day":
        return "DAY"
    else:
        raise ValidationError("{funnelWindowIntervalUnit} not supported")
