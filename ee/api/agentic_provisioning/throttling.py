"""Rate limiting for the agentic provisioning API that is NOT per partner.

The per-partner budgets live in :mod:`ee.api.agentic_provisioning.ratelimits`
(tier-scaled token buckets declared on the handlers). What stays here are the
limits keyed on something other than a partner:

- :class:`ClientRegistrationThrottle` and :class:`CIMDRegistrationThrottle`,
  per client_id / IP / domain, screening callers that are not partners yet.
- ``enforce_wizard_run_user_rate_limit``, per end user, shared between the
  granular wizard_runs action and the bundled account_requests wizard block.
- :class:`RegionProxyThrottle`, per IP, checked by the region proxy in
  ``dispatch`` before DRF has authenticated the caller.
- ``enforce_caller_ip_cap`` and ``enforce_caller_email_caps``, per caller IP
  and per normalized email, on account_requests: a partner budget alone lets
  an abuser reset every limit by self-registering a new partner.

These are fixed-window cache counters: a caller can burst up to 2x a limit
across a window boundary (``limit`` at :59:59 plus ``limit`` at :00:00).
"""

from __future__ import annotations

import time
from hashlib import sha256
from typing import ClassVar, cast
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

import structlog
from django_redis.exceptions import ConnectionInterrupted
from redis.exceptions import RedisError
from rest_framework.request import Request
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.api.oauth import cimd
from posthog.llm.wizard_blocklist import blocklist_properties
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import PartnerTier
from posthog.rate_limit import IPThrottle
from posthog.utils import get_trusted_client_ip

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.constants import (
    CALLER_ACCOUNT_REQUEST_WINDOW_SECONDS,
    CALLER_DOMAIN_RATE_LIMIT_PREFIX,
    CALLER_EMAIL_ROOT_RATE_LIMIT_PREFIX,
    CALLER_IP_RATE_LIMIT_PREFIX,
    CIMD_DOMAIN_RATE_LIMIT_MAX,
    CIMD_DOMAIN_RATE_LIMIT_PREFIX,
    CIMD_DOMAIN_RATE_LIMIT_WINDOW_SECONDS,
    CLIENT_REGISTRATION_IP_RATE_LIMIT_MAX,
    CLIENT_REGISTRATION_RATE_LIMIT_MAX,
    CLIENT_REGISTRATION_RATE_LIMIT_PREFIX,
    CLIENT_REGISTRATION_RATE_LIMIT_WINDOW_SECONDS,
    PROVISIONING_FREE_EMAIL_DOMAINS,
    REGION_PROXY_RATE_LIMIT,
    WIZARD_RUN_USER_RATE_LIMIT_PREFIX,
    WIZARD_RUN_USER_RATE_LIMITS,
)
from ee.api.agentic_provisioning.exceptions import ProvisioningError

logger = structlog.get_logger(__name__)


def _fixed_window_count(cache_key: str, window_seconds: int) -> int:
    try:
        cache.add(cache_key, 0, timeout=window_seconds)
        return cache.incr(cache_key)
    except ValueError as e:
        # incr raises ValueError when the key expired between add and incr.
        logger.warning("provisioning_rate_limit_cache_error", cache_key=cache_key, error=str(e))
        try:
            # cache.add preserves any counter a concurrent request already initialized,
            # so a transient cache error doesn't reset the window for a caller at the limit.
            cache.add(cache_key, 1, timeout=window_seconds)
        except (RedisError, ConnectionInterrupted):
            pass
        return 1
    except (RedisError, ConnectionInterrupted) as e:
        # Redis is unreachable (its errors subclass RedisError/Exception, not the
        # builtin ConnectionError/TimeoutError). Fail open without touching the
        # cache again: a second cache call would raise the same way and turn every
        # provisioning request into a 500 for as long as Redis is down.
        logger.warning("provisioning_rate_limit_cache_error", cache_key=cache_key, error=str(e))
        return 1


def _window_retry_after(window_seconds: int) -> int:
    return window_seconds - (int(time.time()) % window_seconds)


class RegionProxyThrottle(IPThrottle):
    """Per-IP cap on forwarding a request to the other region.

    The region proxy decides to forward inside ``dispatch``, so DRF hasn't run
    ``initial()`` yet: no authentication, none of the throttles above. Without this,
    an unauthenticated caller sending a mismatched region or an unknown token
    turns each request into an outbound cross-region call that holds a worker
    until the other region answers.
    """

    scope = "agentic_provisioning_region_proxy"
    rate = REGION_PROXY_RATE_LIMIT
    error_message: ClassVar[str] = "Too many cross-region requests. Try again later."

    def allow_http_request(self, request: HttpRequest) -> bool:
        """Count a request from the proxy's ``dispatch``, where DRF's ``Request`` doesn't exist yet.

        The key comes from the IP alone, so the plain Django request carries
        everything this throttle reads, and the view argument goes unused.
        """
        return self.allow_request(cast(Request, request), cast(APIView, None))


def enforce_wizard_run_user_rate_limit(user_id: int, resource_id: str = "") -> None:
    """Cache-counter equivalent of the session cloud_run endpoint's per-user throttles;
    shared across the granular wizard_runs action and the bundled account_requests path
    so retries can't double-spend the budget."""
    for label, limit, window_seconds in WIZARD_RUN_USER_RATE_LIMITS:
        window_index = int(time.time()) // window_seconds
        key = f"{WIZARD_RUN_USER_RATE_LIMIT_PREFIX}{label}:{user_id}:{window_index}"
        count = _fixed_window_count(key, window_seconds)
        if count > limit:
            capture_provisioning_event(
                "rate_limited", "rate_limited", endpoint="wizard_runs_user", limit=limit, window=label
            )
            raise ProvisioningError(
                "rate_limited",
                "Too many wizard runs for this user. Try later.",
                status=429,
                envelope="status",
                resource_id=resource_id,
                retry_after=_window_retry_after(window_seconds),
            )


def _enforce_caller_cap(partner: OAuthApplication, *, key_kind: str, value: str, limit: int, prefix: str) -> None:
    window_index = int(time.time()) // CALLER_ACCOUNT_REQUEST_WINDOW_SECONDS
    cache_key = f"{prefix}{sha256(value.encode()).hexdigest()}:{window_index}"
    if _fixed_window_count(cache_key, CALLER_ACCOUNT_REQUEST_WINDOW_SECONDS) > limit:
        capture_provisioning_event("account_request", "caller_rate_limited", partner=partner, key_kind=key_kind)
        raise ProvisioningError(
            "rate_limited",
            "Too many account requests from this caller. Try again later.",
            status=429,
            retry_after=_window_retry_after(CALLER_ACCOUNT_REQUEST_WINDOW_SECONDS),
        )


def enforce_caller_ip_cap(request: Request, partner: OAuthApplication) -> None:
    """Per-IP daily ceiling on account_requests, independent of the partner's own budget.

    Skipped for JWKS-tier partners: a confidential partner calls from its own servers,
    so many requests sharing one IP is ordinary traffic rather than abuse. Also skipped
    when the caller's IP can't be validated against the trusted-proxy chain (a direct
    caller outside TRUSTED_PROXIES, or a cross-region proxy hop it doesn't cover) rather
    than falling back to a shared key, which would let every such caller throttle
    each other on one bucket.
    """
    if partner.partner_tier in (PartnerTier.JWKS, PartnerTier.JWKS_ATTESTED):
        return
    ip = get_trusted_client_ip(request)
    if ip is None:
        return
    _enforce_caller_cap(
        partner,
        key_kind="ip",
        value=ip,
        limit=settings.PROVISIONING_ACCOUNT_REQUESTS_PER_IP_PER_DAY,
        prefix=CALLER_IP_RATE_LIMIT_PREFIX,
    )


def enforce_caller_email_caps(partner: OAuthApplication, email: str) -> None:
    """Per-email-root and per-domain daily ceilings on account_requests that create a
    new user. Call only once ``existing_user`` resolves to None: an existing account is
    routed to consent rather than created, so counting it here would cap a caller for a
    request that spent no partner budget and created no account.
    """
    properties = blocklist_properties(email=email)
    email_root = properties["email_root"]
    if email_root:
        _enforce_caller_cap(
            partner,
            key_kind="email_root",
            value=email_root,
            limit=settings.PROVISIONING_ACCOUNT_REQUESTS_PER_EMAIL_ROOT_PER_DAY,
            prefix=CALLER_EMAIL_ROOT_RATE_LIMIT_PREFIX,
        )
    domain = properties["email_domain"]
    if domain and domain not in PROVISIONING_FREE_EMAIL_DOMAINS:
        _enforce_caller_cap(
            partner,
            key_kind="domain",
            value=domain,
            limit=settings.PROVISIONING_ACCOUNT_REQUESTS_PER_DOMAIN_PER_DAY,
            prefix=CALLER_DOMAIN_RATE_LIMIT_PREFIX,
        )


class ClientRegistrationThrottle(BaseThrottle):
    """Cap client_registration calls per client_id.

    That endpoint performs a synchronous outbound fetch of a caller-supplied URL, so unlike
    :class:`CIMDRegistrationThrottle` this applies whether or not the client already exists:
    an already-registered partner re-running diagnostics is exactly the case that would
    otherwise fetch without limit.

    Counted per client_id and per address. CIMDRegistrationThrottle only screens by IP and
    domain while a client is new, so without the second counter a caller could register a
    stack of client_ids and then spend a full per-client budget on each of them from one
    address, turning the per-client cap into an arbitrarily large total.
    """

    # Not a ClassVar: the per-address refusal narrows the message on the instance, the same way
    # CIMDRegistrationThrottle distinguishes its domain limit.
    error_message: str = "Too many registration checks for this client. Try again later."

    def allow_request(self, request: Request, view: APIView) -> bool:
        client_id = request.data.get("client_id") or ""
        if not client_id:
            return True
        window_index = int(time.time()) // CLIENT_REGISTRATION_RATE_LIMIT_WINDOW_SECONDS
        key = f"{CLIENT_REGISTRATION_RATE_LIMIT_PREFIX}{sha256(client_id.encode()).hexdigest()}:{window_index}"
        if _fixed_window_count(key, CLIENT_REGISTRATION_RATE_LIMIT_WINDOW_SECONDS) > CLIENT_REGISTRATION_RATE_LIMIT_MAX:
            capture_provisioning_event("rate_limited", "rate_limited", endpoint="client_registration")
            return False

        ident = self.get_ident(request)
        if not ident:
            return True
        ip_key = f"{CLIENT_REGISTRATION_RATE_LIMIT_PREFIX}ip:{sha256(ident.encode()).hexdigest()}:{window_index}"
        if _fixed_window_count(ip_key, CLIENT_REGISTRATION_RATE_LIMIT_WINDOW_SECONDS) > (
            CLIENT_REGISTRATION_IP_RATE_LIMIT_MAX
        ):
            capture_provisioning_event("rate_limited", "rate_limited", endpoint="client_registration_ip")
            self.error_message = "Too many registration checks from this address. Try again later."
            return False
        return True

    def wait(self) -> int:
        return _window_retry_after(CLIENT_REGISTRATION_RATE_LIMIT_WINDOW_SECONDS)


class CIMDRegistrationThrottle(BaseThrottle):
    """Rate-limit first-time CIMD app registration by IP and domain to match /authorize protections.

    Declared on the account_requests view, so it runs before the handler
    identifies the partner — keeping this check first, where an unregistered
    client_id can't spend anything else's quota.
    """

    error_message: str = "Too many new client registrations. Try again later."

    def allow_request(self, request: Request, view: APIView) -> bool:
        client_id = request.data.get("client_id") or request.query_params.get("client_id")
        if not client_id or not cimd.is_cimd_client_id(client_id):
            return True
        if OAuthApplication.objects.filter(client_id=client_id).exists():
            return True

        # Attribute access (not a from-import) so tests patching
        # posthog.api.oauth.cimd.CIMD_THROTTLE_CLASSES take effect here.
        for throttle_cls in cimd.CIMD_THROTTLE_CLASSES:
            throttle = throttle_cls()
            if not throttle.allow_request(request, view):
                logger.warning("cimd_rate_limited", client_id=client_id, scope=throttle.scope, wait=throttle.wait())
                return False

        return self._allow_domain(cast(str, client_id))

    def _allow_domain(self, client_id: str) -> bool:
        """Prevent a single domain from registering unlimited CIMD apps via different URL paths."""
        domain = urlparse(client_id).hostname
        if not domain:
            return True

        window_index = int(time.time()) // CIMD_DOMAIN_RATE_LIMIT_WINDOW_SECONDS
        key = f"{CIMD_DOMAIN_RATE_LIMIT_PREFIX}{domain}:{window_index}"
        count = _fixed_window_count(key, CIMD_DOMAIN_RATE_LIMIT_WINDOW_SECONDS)

        if count > CIMD_DOMAIN_RATE_LIMIT_MAX:
            logger.warning("cimd_domain_rate_limited", client_id=client_id, domain=domain, count=count)
            capture_provisioning_event("account_request", "cimd_domain_rate_limited", domain=domain, count=count)
            self.error_message = "Too many new client registrations from this domain. Try again later."
            return False
        return True

    def wait(self) -> None:
        # CIMD registration 429s carry no Retry-After: the window is shared
        # across clients, so a per-caller hint would be misleading.
        return None
