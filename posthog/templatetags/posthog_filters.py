# Number formatting filters for the email templates under posthog/templates/email.
# Registered as a template builtin in posthog/settings/web.py, so templates use these
# filters without a {% load %}. Django resolves {% load %} per file, so without the builtin
# every template would have to repeat it, including those that extend email/base.html.

from typing import Optional, Union

from django import template
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.html import json_script
from django.utils.safestring import SafeString

from posthog.exceptions_capture import capture_exception
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


class TolerantJSONEncoder(DjangoJSONEncoder):
    # One unserializable value writes null instead of failing every page render.
    def default(self, o: object) -> object:
        try:
            return super().default(o)
        except TypeError:
            capture_exception(TypeError(f"unserializable {type(o).__name__} in page context"))
            return None


@register.filter
def page_json_script(value: object, element_id: str) -> SafeString:
    return json_script(value, element_id, encoder=TolerantJSONEncoder)
