from __future__ import annotations

import uuid
import hashlib
import functools
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.core.cache import cache

import requests
import structlog
import posthoganalytics
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import find_oauth_access_token, find_oauth_refresh_token
from posthog.utils import get_instance_region

from . import AUTH_CODE_CACHE_PREFIX

logger = structlog.get_logger(__name__)

PROXY_TIMEOUT = (2, 10)
DEFAULT_US_DOMAIN = "us.posthog.com"
DEFAULT_EU_DOMAIN = "eu.posthog.com"
PROXY_LOOP_HEADER = "X-PostHog-Proxied"

BEARER_PREFIX = "Bearer "
BEARER_EXISTS_CACHE_PREFIX = "agentic_bearer_exists:"
# Short TTL on "token doesn't exist here" so a newly-minted EU token becomes
# visible to US (for the short window before EU→US replication catches up) and
# so a token revoked on the other region starts getting proxied again soon.
BEARER_EXISTS_POSITIVE_TTL = 300
BEARER_EXISTS_NEGATIVE_TTL = 30


def _region_domains() -> tuple[str, str]:
    """Read at call time, not import time, so @override_settings works in tests."""
    return (
        getattr(settings, "REGION_US_DOMAIN", DEFAULT_US_DOMAIN),
        getattr(settings, "REGION_EU_DOMAIN", DEFAULT_EU_DOMAIN),
    )


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


def _proxy_to_region(request: Request, target_domain: str) -> Response:
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
            "provisioning.proxy.success",
            target_url=target_url,
            status_code=response.status_code,
        )

        if response.status_code == 204:
            return Response(status=204)

        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {"error": "Invalid response from alternate region"}

        return Response(data=data, status=response.status_code)

    except requests.exceptions.RequestException as e:
        capture_exception(e, {"target_url": target_url, "step": "provisioning.proxy.failed"})
        raise


def _should_proxy_body_region(request: Request, current_region: str) -> bool:
    configuration = request.data.get("configuration")
    if not isinstance(configuration, dict):
        configuration = {}
    requested_region = (configuration.get("region") or "US").upper()
    return requested_region != current_region


def _should_proxy_token_lookup(request: Request, current_region: str) -> bool:
    grant_type = request.data.get("grant_type", "")

    if grant_type == "authorization_code":
        code = request.data.get("code", "")
        if not code:
            return False
        cache_key = f"{AUTH_CODE_CACHE_PREFIX}{code}"
        return cache.get(cache_key) is None

    if grant_type == "refresh_token":
        refresh_token_value = request.data.get("refresh_token", "")
        if not refresh_token_value:
            return False
        return find_oauth_refresh_token(refresh_token_value) is None

    return False


def _bearer_exists_locally(token_value: str) -> bool:
    # SHA-256 the token before using it as a cache key so raw bearer tokens
    # never appear in Redis keyspace dumps or logs. Tokens are already
    # high-entropy (256 bits from secrets.token_urlsafe), so an unsalted hash
    # is sufficient — rainbow tables against 2^256 random inputs are a non-issue.
    token_hash = hashlib.sha256(token_value.encode("utf-8")).hexdigest()
    cache_key = f"{BEARER_EXISTS_CACHE_PREFIX}{token_hash}"
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)

    exists = find_oauth_access_token(token_value) is not None
    ttl = BEARER_EXISTS_POSITIVE_TTL if exists else BEARER_EXISTS_NEGATIVE_TTL
    cache.set(cache_key, exists, timeout=ttl)
    return exists


def _should_proxy_bearer_lookup(request: Request, current_region: str) -> bool:
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


REGION_PROXY_REGISTRY: dict[str, str] = {}


def region_proxy(strategy: str):
    check_fn = _STRATEGY_CHECKS[strategy]

    def decorator(view_func):
        REGION_PROXY_REGISTRY[view_func.__qualname__] = strategy

        @functools.wraps(view_func)
        def wrapper(request: Request, *args, **kwargs) -> Response:
            # Cache the raw body before any `request.data` access downstream.
            # Without this, DRF parses the stream when a strategy check reads
            # request.data, then _proxy_to_region raises RawPostDataException
            # when it tries to forward request.body. Previously this was a
            # side effect of verify_stripe_signature running here.
            _ = request.body

            current = _current_region()
            if current is None or current in ("DEV", "LOCAL"):
                return view_func(request, *args, **kwargs)

            if request.META.get(f"HTTP_{PROXY_LOOP_HEADER.upper().replace('-', '_')}"):
                return view_func(request, *args, **kwargs)

            if check_fn(request, current):
                target = _other_region_domain(current)
                logger.info(
                    "provisioning.proxy.routing",
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
                    posthoganalytics.capture(
                        "agentic_provisioning region_proxy",
                        distinct_id=f"agentic_provisioning_{uuid.uuid4().hex[:16]}",
                        properties={"outcome": "proxied", **proxy_props},
                    )
                    return response
                except requests.exceptions.RequestException:
                    posthoganalytics.capture(
                        "agentic_provisioning region_proxy",
                        distinct_id=f"agentic_provisioning_{uuid.uuid4().hex[:16]}",
                        properties={"outcome": "proxy_failed", **proxy_props},
                    )
                    if strategy == "body_region":
                        return Response(
                            {"error": {"code": "proxy_failed", "message": "Failed to route to correct region"}},
                            status=502,
                        )

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
