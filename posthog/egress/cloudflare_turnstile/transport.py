"""Recorded transport for the Cloudflare Turnstile siteverify API.

Cloudflare publishes no request limit for siteverify, so these calls are recorded but not gated.
"""

import requests

from posthog.egress.cloudflare_turnstile.observability import cloudflare_turnstile_egress
from posthog.egress.transport.transport import RecordedEgressClient

TURNSTILE_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class CloudflareTurnstileClient(RecordedEgressClient):
    observability = cloudflare_turnstile_egress
    egress_domain = "cloudflare_turnstile"


_cloudflare_turnstile_client = CloudflareTurnstileClient()


def turnstile_siteverify_request(
    data: dict[str, str], *, source: str, timeout: float | tuple[float, float]
) -> requests.Response:
    # One secret key for the whole instance, so the identity is constant.
    return _cloudflare_turnstile_client.request(
        "POST",
        TURNSTILE_SITEVERIFY_URL,
        source=source,
        scope="public",
        endpoint="siteverify",
        timeout=timeout,
        data=data,
    )
