# Number formatting filters for the email templates under posthog/templates/email, and a JSON data block filter for head.html.
# Registered as a template builtin in posthog/settings/web.py, so templates use these
# filters without a {% load %}. Django resolves {% load %} per file, so without the builtin
# every template would have to repeat it, including those that extend email/base.html.

from typing import Optional, Union

from django import template
from django.utils.html import format_html
from django.utils.safestring import SafeString, mark_safe

from posthog.utils import compact_number

register = template.Library()

Number = Union[int, float]

# The escapes Django's json_script applies, plus U+2028 and U+2029 for parsers that treat them as line breaks.
# JSON only allows these characters inside strings, where the \uXXXX form decodes to the same value.
_JSON_SCRIPT_ESCAPES = {
    ord(">"): "\\u003E",
    ord("<"): "\\u003C",
    ord("&"): "\\u0026",
    ord("\u2028"): "\\u2028",
    ord("\u2029"): "\\u2029",
}

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


@register.filter(is_safe=True)
def serialized_json_script(value: str, element_id: str) -> SafeString:
    """
    Wraps an already-serialized JSON string in a non-executable `<script type="application/json">` block.
    Django's json_script serializes the value itself, which would double-encode a string.
    Without `<`, the content cannot close the element or open an HTML comment.
    Read it with `JSON.parse(document.getElementById(element_id).textContent)`.
    """
    return format_html(
        '<script type="application/json" id="{}">{}</script>',
        element_id,
        mark_safe(str(value).translate(_JSON_SCRIPT_ESCAPES)),
    )
