import re

from django.conf import settings
from django.template import Library

from posthog.utils import absolute_uri as util_absolute_uri

register = Library()


@register.simple_tag
def absolute_uri(url: str = "") -> str:
    return util_absolute_uri(url)


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
def human_social_providers(providers: list[str]) -> str:
    """
    Returns a human-friendly name for a social login provider.
    Example:
      {% human_social_providers ["google-oauth2", "github"] %}
      =>  "Google, GitHub"
    """

    def friendly_provider(prov: str) -> str:
        if prov == "google-oauth2":
            return "Google"
        elif prov == "github":
            return "GitHub"
        elif prov == "gitlab":
            return "GitLab"
        return "single sign-on (SAML)"

    return ", ".join(map(friendly_provider, providers))


@register.simple_tag
def strip_protocol(path: str) -> str:
    """
    Returns a URL removing the http/https protocol
    Example:
      {% strip_protocol 'https://app.posthog.com' %}
      =>  "app.posthog.com"
    """
    return re.sub(r"https?:\/\/", "", path)
