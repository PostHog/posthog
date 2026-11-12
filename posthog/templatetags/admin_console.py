from django import template
from django.db.models import Model

from posthog.admin.console.records import console_url_for

register = template.Library()

CONSOLE_HOME = "/admin/console/"


@register.simple_tag
def admin_console_url(original: object = None) -> str:
    """Where the Django admin banner's "Open PostHog Admin" link goes: the console page of the record a change
    form shows, or the console home."""
    # Outside a change form `original` is not set, and the template passes an empty string.
    if not isinstance(original, Model):
        return CONSOLE_HOME
    return console_url_for(original) or CONSOLE_HOME
