"""Regional routing helpers for conversations webhooks.

EU is the primary region (external callback URLs point here).
If the primary region doesn't own the resource, it proxies the
request to the secondary region (US).
"""

from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.http import HttpRequest
from django.http.request import RawPostDataException

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


def _build_proxy_kwargs(request: HttpRequest, headers: dict[str, str]) -> dict:
    """Build data/files kwargs for the proxy request.

    Prefers the raw body for an exact byte-for-byte forward.  Under ASGI,
    if request.POST/FILES have already been accessed the raw stream is
    consumed and request.body raises RawPostDataException.  In that case
    we reconstruct from the parsed multipart data.
    """
    try:
        body = request.body
        return {"data": body or None, "headers": headers}
    except RawPostDataException:
        # Drop Content-Type so `requests` generates a fresh multipart
        # boundary matching the reconstructed payload.
        cleaned_headers = {k: v for k, v in headers.items() if k.lower() != "content-type"}
        data = [(key, value) for key, values in request.POST.lists() for value in values]
        files = []
        for key in request.FILES:
            for f in request.FILES.getlist(key):
                f.seek(0)
                files.append((key, (f.name, f.read(), f.content_type)))
        # When files is empty, `requests` will use form-encoding instead of
        # multipart. That's fine — the receiving handler reads via
        # request.POST.get() which Django populates for both encodings.
        return {"data": data, "files": files, "headers": cleaned_headers}


def proxy_to_secondary_region(request: HttpRequest, *, log_prefix: str, timeout: int = 3) -> bool:
    """Forward an incoming webhook to the secondary region.

    Returns True if the proxy request succeeded (2xx), False otherwise.
    """
    parsed_url = urlparse(request.build_absolute_uri())
    target_url = urlunparse(parsed_url._replace(netloc=SECONDARY_REGION_DOMAIN))
    headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}

    try:
        proxy_kwargs = _build_proxy_kwargs(request, headers)
        response = requests.request(
            method=request.method or "POST",
            url=target_url,
            params=dict(request.GET.lists()) if request.GET else None,
            timeout=timeout,
            **proxy_kwargs,
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
