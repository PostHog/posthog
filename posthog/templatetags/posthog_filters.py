# Number formatting filters for the email templates under posthog/templates/email.
# Registered as a template builtin in posthog/settings/web.py, so templates use these
# filters without a {% load %}. Django resolves {% load %} per file, so without the builtin
# every template would have to repeat it, including those that extend email/base.html.

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
