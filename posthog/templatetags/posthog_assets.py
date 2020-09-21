from django.conf import settings
from django.template import Library

from posthog.utils import absolute_uri

register = Library()

register.simple_tag(absolute_uri, name="absolute_uri")


@register.simple_tag
def absolute_asset_url(path: str) -> str:
    """
    Returns a versioned absolute asset URL (located within PostHog's static files).
    Example:
      {% absolute_asset_url 'dist/posthog.css' %}
      =>  "http://posthog.example.com/_static/74d127b78dc7daf2c51f/dist/posthog.css"
    """
    return absolute_uri(f"{settings.STATIC_URL.rstrip('/')}/{path.lstrip('/')}")


@register.simple_tag
def utmify_email_url(url: str, campaign: str) -> str:
    """
    Returns a versioned absolute asset URL (located within PostHog's static files).
    Example:
        {% utmify_email_url 'http://app.posthog.com' 'weekly_report' %}
        =>  "http://app.posthog.com?utm_source=posthog&utm_medium=email&utm_campaign=weekly_report"
    """
    return f"{url}{'&' if '?' in url else '?'}utm_source=posthog&utm_medium=email&utm_campaign={campaign}"
