import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

from posthog.settings.base_variables import CLOUD_DEPLOYMENT


def validate_surveys_public_url(value: str, cloud_deployment: str | None) -> str:
    public_url = value.rstrip("/")
    if not public_url:
        return ""

    parsed = urlparse(public_url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ImproperlyConfigured("SURVEYS_PUBLIC_URL must be an HTTP(S) origin without a path or credentials")

    if (cloud_deployment or "").upper() in ("US", "EU"):
        if parsed.scheme != "https":
            raise ImproperlyConfigured("SURVEYS_PUBLIC_URL must use HTTPS on PostHog Cloud")
        if parsed.hostname == "posthog.com" or parsed.hostname.endswith(".posthog.com"):
            raise ImproperlyConfigured("SURVEYS_PUBLIC_URL must not share the posthog.com cookie domain")

    return public_url


SURVEYS_PUBLIC_URL = validate_surveys_public_url(os.getenv("SURVEYS_PUBLIC_URL", ""), CLOUD_DEPLOYMENT)
