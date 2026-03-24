"""Regional routing helpers for conversations webhooks.

EU is the primary region (external callback URLs point here).
If the primary region doesn't own the resource, it proxies the
request to the secondary region (US).
"""

from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.http import HttpRequest

import requests
import structlog
from requests import RequestException

logger = structlog.get_logger(__name__)

PRIMARY_REGION_DOMAIN = "eu.posthog.com"
SECONDARY_REGION_DOMAIN = "us.posthog.com"

if settings.DEBUG:
    PRIMARY_REGION_DOMAIN = urlparse(settings.SITE_URL).netloc
    SECONDARY_REGION_DOMAIN = "localhost:8000"


def is_primary_region(request: HttpRequest) -> bool:
    return request.get_host() == PRIMARY_REGION_DOMAIN


def proxy_to_secondary_region(request: HttpRequest, *, log_prefix: str, timeout: int = 3) -> bool:
    """Forward an incoming webhook to the secondary region.

    Returns True if the proxy request succeeded (2xx), False otherwise.
    """
    parsed_url = urlparse(request.build_absolute_uri())
    target_url = urlunparse(parsed_url._replace(netloc=SECONDARY_REGION_DOMAIN))
    headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}

    try:
        response = requests.request(
            method=request.method or "POST",
            url=target_url,
            headers=headers,
            params=dict(request.GET.lists()) if request.GET else None,
            data=request.body or None,
            timeout=timeout,
        )
        if response.ok:
            logger.info(
                f"{log_prefix}_proxy_to_secondary_region",
                target_url=target_url,
                status_code=response.status_code,
            )
        else:
            logger.warning(
                f"{log_prefix}_proxy_to_secondary_region_bad_status",
                target_url=target_url,
                status_code=response.status_code,
            )
        return response.ok
    except RequestException as exc:
        logger.exception(
            f"{log_prefix}_proxy_to_secondary_region_failed",
            error=str(exc),
            target_url=target_url,
        )
        return False
