from __future__ import annotations

import functools
from urllib.parse import urlparse, urlunparse

from django.core.cache import cache

import requests
import structlog
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.oauth import find_oauth_refresh_token
from posthog.security.outbound_proxy import external_requests
from posthog.utils import get_instance_region

from . import AUTH_CODE_CACHE_PREFIX
from .signature import verify_stripe_signature

logger = structlog.get_logger(__name__)

PROXY_TIMEOUT = 10
US_DOMAIN = "us.posthog.com"
EU_DOMAIN = "eu.posthog.com"
PROXY_LOOP_HEADER = "X-PostHog-Proxied"

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
    if current == "US":
        return EU_DOMAIN
    return US_DOMAIN


def _proxy_to_region(request: Request, target_domain: str) -> Response:
    parsed_url = urlparse(request.build_absolute_uri())
    target_url = urlunparse(parsed_url._replace(netloc=target_domain))

    headers = {k: v for k, v in request.headers.items() if k.lower() in PROXY_HEADER_ALLOWLIST}
    headers["Host"] = target_domain
    headers[PROXY_LOOP_HEADER] = "1"

    try:
        response = external_requests.request(
            method=request.method or "GET",
            url=target_url,
            headers=headers,
            data=request.body or None,
            timeout=PROXY_TIMEOUT,
        )

        logger.info(
            "stripe_app.proxy.success",
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
        logger.exception(
            "stripe_app.proxy.failed",
            target_url=target_url,
            error=str(e),
        )
        raise


def _should_proxy_body_region(request: Request, current_region: str) -> bool:
    configuration = request.data.get("configuration") or {}
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


_STRATEGY_CHECKS = {
    "body_region": _should_proxy_body_region,
    "token_lookup": _should_proxy_token_lookup,
}


def stripe_region_proxy(strategy: str):
    check_fn = _STRATEGY_CHECKS[strategy]

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request: Request, *args, **kwargs) -> Response:
            error = verify_stripe_signature(request)
            if error:
                return error

            current = _current_region()
            if current is None or current in ("DEV", "LOCAL"):
                return view_func(request, *args, **kwargs)

            if request.META.get(f"HTTP_{PROXY_LOOP_HEADER.upper().replace('-', '_')}"):
                return view_func(request, *args, **kwargs)

            if check_fn(request, current):
                target = _other_region_domain(current)
                logger.info(
                    "stripe_app.proxy.routing",
                    strategy=strategy,
                    current_region=current,
                    target_domain=target,
                )
                try:
                    return _proxy_to_region(request, target)
                except requests.exceptions.RequestException:
                    if strategy == "body_region":
                        return Response(
                            {"error": {"code": "proxy_failed", "message": "Failed to route to correct region"}},
                            status=502,
                        )

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
