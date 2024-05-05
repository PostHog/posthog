from typing import Optional, Union

from django import template

from posthog.utils import compact_number
from dateutil.parser import parse

register = template.Library()

Number = Union[int, float]

register.filter(compact_number)


@register.filter
def percentage(value: Optional[Number], decimals: int = 1) -> str:
    """
    Returns a rounded formatted with a specific number of decimal digits and a % sign. Expects a decimal-based ratio.
    Example:
      {% percentage 0.2283113 %}
      =>  "22.8%"
    """

    if value is None:
        return "-"

    return "{0:.{decimals}f}%".format(value * 100, decimals=decimals)


@register.filter
def humanize_time_diff(date_from, date_to):
    """
    Returns a humanized string representing time difference
    between now() and the input timestamp.

    The output rounds up to days, hours, minutes, or seconds.
    4 days 5 hours returns '4 days'
    0 days 4 hours 3 minutes returns '4 hours', etc...
    """

    timeDiff = parse(date_to) - parse(date_from)
    days = timeDiff.days
    hours = timeDiff.seconds / 3600
    minutes = timeDiff.seconds % 3600 / 60
    seconds = timeDiff.seconds % 3600 % 60

    str = ""
    tStr = ""
    if days > 0:
        if days == 1:
            tStr = "day"
        else:
            tStr = "days"
        str = str + "{} {}".format(days, tStr)
        return str
    elif hours > 0:
        if hours == 1:
            tStr = "hour"
        else:
            tStr = "hours"
        str = str + "{} {}".format(hours, tStr)
        return str
    elif minutes > 0:
        if minutes == 1:
            tStr = "min"
        else:
            tStr = "mins"
        str = str + "{} {}".format(minutes, tStr)
        return str
    elif seconds > 0:
        if seconds == 1:
            tStr = "sec"
        else:
            tStr = "secs"
        str = str + "{} {}".format(seconds, tStr)
        return str
    else:
        return None
