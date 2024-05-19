from typing import Optional, Union

from django import template

from posthog.utils import compact_number
from dateutil.relativedelta import relativedelta
from django.template.defaultfilters import pluralize

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
    between the given timestamps

    The output trims out time diff to years, months, days, or hours
    1 month 20 days returns '1 month'
    4 days 5 hours returns '4 days'
    0 days 4 hours 3 minutes returns '4 hours', etc...
    """

    time_diff = relativedelta(date_to, date_from)

    years = time_diff.years
    months = time_diff.months
    days = time_diff.days
    hours = time_diff.hours

    str = ""
    tStr = ""

    if years > 0:
        tStr = "year{}".format(pluralize(years))
        str = "{} {}".format(years, tStr)
    elif months > 0:
        tStr = "month{}".format(pluralize(months))
        str = "{} {}".format(months, tStr)
    elif days > 0:
        tStr = "day{}".format(pluralize(days))
        str = "{} {}".format(days, tStr)
    else:
        tStr = "hour{}".format(pluralize(hours or 1))
        str = "{} {}".format(hours or 1, tStr)

    return str
