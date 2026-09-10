from __future__ import annotations

from django.conf import settings

from posthog.utils import get_instance_region


def current_region_host() -> str:
    """Host of the region this instance serves, for URLs handed to partners.

    No region means this is not a Cloud deployment (local dev, self-hosted), so the instance's
    own URL is the only correct answer. Defaulting to a Cloud region instead hands partners a
    host their freshly provisioned account does not exist on.
    """
    region = get_instance_region()
    if not region:
        return settings.SITE_URL
    return region_to_host(region)


def region_to_host(region: str) -> str:
    region_lower = region.lower()
    if region_lower == "eu":
        return "https://eu.posthog.com"
    elif region_lower == "us":
        return "https://us.posthog.com"
    elif region_lower == "dev":
        return "https://app.dev.posthog.dev"
    return settings.SITE_URL
