"""US/EU cross-region forwarding for the Stripe provisioning namespace.

Stripe calls a single base URL (us.posthog.com), but the account or token it is
acting on may live in the EU region. Each view declares a strategy for deciding
whether the request belongs to the other region:

- ``body_region``:   proxy when ``configuration.region`` differs from the
                     current region (account_requests).
- ``token_lookup``:  proxy when the auth code / refresh token isn't found
                     locally (oauth/token).
- ``bearer_lookup``: proxy when the bearer token isn't found locally (all
                     resource endpoints).

Forwarding preserves the request path, so both regions must expose the same
routes (they deploy the same code).
"""

from __future__ import annotations

import json
import hashlib
from typing import Any
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse

import requests
import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import find_oauth_access_token, find_oauth_refresh_token
from posthog.utils import get_instance_region

from ee.partners.stripe.api.provisioning import AUTH_CODE_CACHE_PREFIX
from ee.partners.stripe.api.provisioning.analytics import capture_region_proxy_event

logger = structlog.get_logger(__name__)

PROXY_TIMEOUT = (2, 10)
DEFAULT_US_DOMAIN = "us.posthog.com"
DEFAULT_EU_DOMAIN = "eu.posthog.com"
PROXY_LOOP_HEADER = "X-PostHog-Proxied"

BEARER_PREFIX = "Bearer "
# "Does this bearer exist locally" cache, keyed within this namespace.
BEARER_EXISTS_CACHE_PREFIX = "stripe_provisioning_bearer_exists:"
# Short TTL on "token doesn't exist here" so a newly-minted EU token becomes
# visible to US (for the short window before EU→US replication catches up) and
# so a token revoked on the other region starts getting proxied again soon.
BEARER_EXISTS_POSITIVE_TTL = 300
BEARER_EXISTS_NEGATIVE_TTL = 30

PROXY_HEADER_ALLOWLIST = frozenset(
    {
        "content-type",
        "accept",
        "stripe-signature",
        "api-version",
        "authorization",
        "user-agent",
    }
)

# Match DRF's compact JSON rendering so proxied bodies read the same as
# locally rendered ones.
_JSON_SEPARATORS = (",", ":")


def _region_domains() -> tuple[str, str]:
    """Read at call time, not import time, so @override_settings works in tests."""
    return (
        getattr(settings, "REGION_US_DOMAIN", DEFAULT_US_DOMAIN),
        getattr(settings, "REGION_EU_DOMAIN", DEFAULT_EU_DOMAIN),
    )


def _current_region() -> str | None:
    region = get_instance_region()
    if region is None:
        return None
    return region.upper()


def _other_region_domain(current: str) -> str:
    us_domain, eu_domain = _region_domains()
    if current == "US":
        return eu_domain
    return us_domain


def _request_payload(request: HttpRequest) -> dict[str, Any]:
    """Parse the request body for the strategy checks without consuming the stream.

    Accessing ``request.body`` caches it, so DRF can still parse it downstream.
    """
    try:
        content_type = request.content_type or ""
        if "json" in content_type:
            parsed = json.loads(request.body.decode("utf-8")) if request.body else {}
            return parsed if isinstance(parsed, dict) else {}
        return dict(request.POST.items())
    except Exception:
        return {}


def _proxy_to_region(request: HttpRequest, target_domain: str) -> HttpResponse:
    parsed_url = urlparse(request.build_absolute_uri())
    target_url = urlunparse(parsed_url._replace(netloc=target_domain))

    headers = {k: v for k, v in request.headers.items() if k.lower() in PROXY_HEADER_ALLOWLIST}
    headers["Host"] = target_domain
    headers[PROXY_LOOP_HEADER] = "1"

    try:
        response = requests.request(
            method=request.method or "GET",
            url=target_url,
            headers=headers,
            data=request.body or None,
            timeout=PROXY_TIMEOUT,
        )

        logger.info(
            "stripe_provisioning.proxy.success",
            target_url=target_url,
            status_code=response.status_code,
        )

        if response.status_code == 204:
            return HttpResponse(status=204)

        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {"error": "Invalid response from alternate region"}

        return HttpResponse(
            json.dumps(data, separators=_JSON_SEPARATORS),
            status=response.status_code,
            content_type="application/json",
        )

    except requests.exceptions.RequestException as e:
        capture_exception(e, {"target_url": target_url, "step": "stripe_provisioning.proxy.failed"})
        raise


def _should_proxy_body_region(request: HttpRequest, current_region: str) -> bool:
    configuration = _request_payload(request).get("configuration")
    if not isinstance(configuration, dict):
        configuration = {}
    requested_region = (configuration.get("region") or "US").upper()
    return requested_region != current_region


def _should_proxy_token_lookup(request: HttpRequest, current_region: str) -> bool:
    payload = _request_payload(request)
    grant_type = payload.get("grant_type", "")

    if grant_type == "authorization_code":
        code = payload.get("code", "")
        if not code:
            return False
        return cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}") is None

    if grant_type == "refresh_token":
        refresh_token_value = payload.get("refresh_token", "")
        if not refresh_token_value:
            return False
        return find_oauth_refresh_token(refresh_token_value) is None

    return False


def _bearer_exists_locally(token_value: str) -> bool:
    # TODO: latent bug - cache backend failures here (and in the token-lookup
    # check above) propagate as 500s instead of falling back to the local DB
    # lookup.
    # SHA-256 the token before using it as a cache key so raw bearer tokens
    # never appear in Redis keyspace dumps or logs. Tokens are already
    # high-entropy (256 bits from secrets.token_urlsafe), so an unsalted hash
    # is sufficient - rainbow tables against 2^256 random inputs are a non-issue.
    token_hash = hashlib.sha256(token_value.encode("utf-8")).hexdigest()
    cache_key = f"{BEARER_EXISTS_CACHE_PREFIX}{token_hash}"
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)

    exists = find_oauth_access_token(token_value) is not None
    ttl = BEARER_EXISTS_POSITIVE_TTL if exists else BEARER_EXISTS_NEGATIVE_TTL
    cache.set(cache_key, exists, timeout=ttl)
    return exists


def _should_proxy_bearer_lookup(request: HttpRequest, current_region: str) -> bool:
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith(BEARER_PREFIX):
        return False

    token_value = auth_header[len(BEARER_PREFIX) :].strip()
    if not token_value:
        return False

    return not _bearer_exists_locally(token_value)


_STRATEGY_CHECKS = {
    "body_region": _should_proxy_body_region,
    "token_lookup": _should_proxy_token_lookup,
    "bearer_lookup": _should_proxy_bearer_lookup,
}


class RegionProxyMixin:
    """Forward the request to the other region when its resources live there.

    Set ``region_proxy_strategy`` on the view. Runs before authentication (a
    bearer that only exists in the other region must proxy, not 401 locally).
    On proxy failure, ``body_region`` returns a flat ``proxy_failed`` 502 (the
    request can't be served locally at all); the lookup strategies fall through
    to local handling, which produces the appropriate auth error.

    TODO: latent gap - because this runs before authentication and rate
    limiting, an unauthenticated caller can induce outbound cross-region
    requests (bounded request amplification).
    """

    region_proxy_strategy: str | None = None

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        strategy = self.region_proxy_strategy
        if strategy is None:
            return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

        # Cache the raw body before the strategy checks touch it, so DRF's
        # parsers (and signature verification) can still read it afterwards.
        _ = request.body

        current = _current_region()
        # TODO: latent gap - "E2E" instances are not listed here, so they
        # attempt real cross-region proxying instead of handling locally.
        if current is None or current in ("DEV", "LOCAL"):
            return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

        # TODO: latent gap - the loop-prevention header is trusted from raw
        # client input; a caller can set it to force local handling (and skip
        # proxying) for a resource that lives in the other region. It can only
        # suppress proxying, never trigger it.
        if request.META.get(f"HTTP_{PROXY_LOOP_HEADER.upper().replace('-', '_')}"):
            return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

        if _STRATEGY_CHECKS[strategy](request, current):
            target = _other_region_domain(current)
            logger.info(
                "stripe_provisioning.proxy.routing",
                strategy=strategy,
                current_region=current,
                target_domain=target,
            )
            proxy_props = {
                "strategy": strategy,
                "from_region": current,
                "to_domain": target,
                "endpoint": request.path,
            }
            try:
                response = _proxy_to_region(request, target)
                capture_region_proxy_event("proxied", **proxy_props)
                return response
            except requests.exceptions.RequestException:
                capture_region_proxy_event("proxy_failed", **proxy_props)
                if strategy == "body_region":
                    return HttpResponse(
                        json.dumps(
                            {"error": {"code": "proxy_failed", "message": "Failed to route to correct region"}},
                            separators=_JSON_SEPARATORS,
                        ),
                        status=502,
                        content_type="application/json",
                    )

        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
