from __future__ import annotations

from django.conf import settings

from posthog.utils import get_instance_region


def current_region_host() -> str:
    """Host of the region this instance serves, for URLs handed to partners."""
    return region_to_host(get_instance_region() or "US")


def region_to_host(region: str) -> str:
    region_lower = region.lower()
    if region_lower == "eu":
        return "https://eu.posthog.com"
    elif region_lower in ("us", "dev"):
        return "https://us.posthog.com"
    return settings.SITE_URL
