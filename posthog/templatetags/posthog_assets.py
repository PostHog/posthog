from django.conf import settings
from django.template import Library
from django.utils.html import mark_safe

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


@register.simple_tag
def delta_indicator(direction: str = "up", color: str = "red") -> str:
    """
    Returns an SVG arrow indicator.
    """

    transform_str: str = 'transform="rotate(180)"' if direction != "up" else ""
    color_str: str = "#28a745" if color != "red" else "#f54e00"

    return mark_safe(
        f"""
        <svg width="20" height="22" viewBox="0 0 35 40" fill="none" xmlns="http://www.w3.org/2000/svg" {transform_str}>
            <path fill="{color_str}" d="M18.8258 10.1972L34.0089 25.3802C34.7412 26.1125 34.7412 27.2997 34.0089 28.0319L32.238 29.8027C31.507 30.5338 30.3222 30.5352 29.5895 29.8059L17.5 17.7731L5.41053 29.806C4.6778 30.5352 3.49303 30.5338 2.76201 29.8028L0.991155 28.032C0.258889 27.2997 0.258889 26.1125 0.991155 25.3803L16.1742 10.1973C16.9064 9.46501 18.0936 9.46501 18.8258 10.1972Z" />
        </svg>
        """,
    )
