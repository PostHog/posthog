# Number formatting filters for the email templates under posthog/templates/email.
# Every one of those templates loads this library, even when it extends email/base.html,
# because Django resolves {% load %} per file rather than through template inheritance.

from typing import Optional, Union

from django import template

from posthog.utils import compact_number

register = template.Library()

Number = Union[int, float]

register.filter(compact_number)


@register.filter
def intcomma(value: Optional[Number]) -> str:
    """
    Converts an integer to a string containing commas every three digits.
    Example:
      {% intcomma 1000 %}
      =>  "1,000"
    """
    if value is None:
        return "-"

    return f"{int(value):,}"
