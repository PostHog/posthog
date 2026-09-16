"""Replay a verified request to the region that owns the resource it is about.

A third party sends every delivery to the primary region, so a delivery for a resource the other
region holds has to be forwarded there. The forward is the raw signed bytes, unchanged: the other
region verifies the same signature over the same body, which is why no consumer can do this --
by the time a consumer sees a delivery, the body is a parsed mapping.
"""

from urllib.parse import urlparse, urlunparse

from django.http import HttpRequest

import requests
import structlog
from requests import RequestException

from posthog.ingress.observability.metrics import observe_forward
from posthog.regions import SECONDARY_REGION_DOMAIN

logger = structlog.get_logger(__name__)

# The other region reads its own identity off the connection it receives, so a host this region
# put on the request would let it read itself as the primary region and forward the delivery on
# again. X-Forwarded-Proto travels with them because SECURE_PROXY_SSL_HEADER resolves the scheme
# from it. X-Forwarded-For stays: nothing regional reads it, and it holds the third party's address.
HOST_IDENTIFYING_HEADERS = frozenset({"host", "x-forwarded-host", "x-forwarded-port", "x-forwarded-proto", "forwarded"})


def forward_to_secondary_region(request: HttpRequest, *, provider: str, app: str, timeout: float = 3.0) -> bool:
    """Send this request on to the secondary region once. True only when it answered 2xx.

    Forwarding once per request rather than once per delivery: the unit being replayed is the HTTP
    request, so a batched body that carries several unowned deliveries still crosses once.
    """
    target_url = urlunparse(urlparse(request.build_absolute_uri())._replace(netloc=SECONDARY_REGION_DOMAIN))
    headers = {key: value for key, value in request.headers.items() if key.lower() not in HOST_IDENTIFYING_HEADERS}

    try:
        response = requests.request(
            method=request.method or "POST",
            url=target_url,
            data=request.body,
            headers=headers,
            timeout=timeout,
        )
    except RequestException as error:
        logger.exception(
            "ingress_forward_to_secondary_region_failed",
            provider=provider,
            app=app,
            target_url=target_url,
            error=str(error),
        )
        observe_forward(provider=provider, app=app, outcome="failed")
        return False

    if not response.ok:
        logger.warning(
            "ingress_forward_to_secondary_region_rejected",
            provider=provider,
            app=app,
            target_url=target_url,
            status_code=response.status_code,
        )
        observe_forward(provider=provider, app=app, outcome="rejected")
        return False

    logger.info(
        "ingress_forwarded_to_secondary_region",
        provider=provider,
        app=app,
        target_url=target_url,
        status_code=response.status_code,
    )
    observe_forward(provider=provider, app=app, outcome="forwarded")
    return True
