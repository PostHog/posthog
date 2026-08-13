"""Rate limiting for the agentic provisioning API.

Fixed-window cache counters over one set of keys, reachable two ways:

- :class:`~rest_framework.throttling.BaseThrottle` subclasses, declared in
  ``partner_throttle_classes`` on the view, for limits whose key DRF already
  has when it calls ``check_throttles``: the partner on ``request.auth``, a
  grant id in the URL, a client_id in the body. The base view runs these on
  top of ``DEFAULT_THROTTLE_CLASSES`` and renders rejections in the view's
  wire envelope rather than DRF's ``{"detail": ...}``.
- ``enforce_*`` helpers, for limits that can't be spent as early as
  ``check_throttles`` runs: the token endpoint learns the partner only by
  decoding an auth code or refresh token; account_requests and github_grants
  must clear the partner's capability *before* charging quota, so a partner
  that is refused outright keeps its budget; and the wizard budget is shared
  with the bundled account_requests wizard block, which runs outside any view
  dispatch.
- :class:`RegionProxyThrottle`, checked by the region proxy in ``dispatch``,
  before DRF has authenticated the caller and before either of the above can
  run at all.

A caller can burst up to 2x a limit across a window boundary (``limit`` at
:59:59 plus ``limit`` at :00:00); switch to a sliding window if that matters.
"""

from __future__ import annotations

import time
from hashlib import sha256
from typing import ClassVar, cast
from urllib.parse import urlparse

from django.core.cache import cache
from django.http import HttpRequest

import structlog
from rest_framework.request import Request
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.api.oauth import cimd
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.rate_limit import IPThrottle

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.constants import (
    CIMD_DOMAIN_RATE_LIMIT_MAX,
    CIMD_DOMAIN_RATE_LIMIT_PREFIX,
    CIMD_DOMAIN_RATE_LIMIT_WINDOW_SECONDS,
    CLIENT_REGISTRATION_IP_RATE_LIMIT_MAX,
    CLIENT_REGISTRATION_RATE_LIMIT_MAX,
    CLIENT_REGISTRATION_RATE_LIMIT_PREFIX,
    CLIENT_REGISTRATION_RATE_LIMIT_WINDOW_SECONDS,
    GITHUB_GRANT_POLL_RATE_LIMIT_MAX,
    GITHUB_GRANT_POLL_RATE_LIMIT_PREFIX,
    GITHUB_GRANT_POLL_RATE_LIMIT_WINDOW_SECONDS,
    PARTNER_RATE_LIMIT_DEFAULTS,
    PARTNER_RATE_LIMIT_EVENT_NAMES,
    PARTNER_RATE_LIMIT_PREFIX,
    PARTNER_RATE_LIMIT_WINDOW_SECONDS,
    REGION_PROXY_RATE_LIMIT,
    WIZARD_RUN_USER_RATE_LIMIT_PREFIX,
    WIZARD_RUN_USER_RATE_LIMITS,
)
from ee.api.agentic_provisioning.exceptions import Envelope, ProvisioningError

logger = structlog.get_logger(__name__)


def _fixed_window_count(cache_key: str, window_seconds: int) -> int:
    try:
        cache.add(cache_key, 0, timeout=window_seconds)
        return cache.incr(cache_key)
    except (ValueError, ConnectionError, TimeoutError) as e:
        logger.warning("provisioning_rate_limit_cache_error", cache_key=cache_key, error=str(e))
        # cache.add preserves any counter a concurrent request already initialized,
        # so a transient cache error doesn't reset the window for a caller at the limit.
        cache.add(cache_key, 1, timeout=window_seconds)
        return 1


def _window_retry_after(window_seconds: int) -> int:
    return window_seconds - (int(time.time()) % window_seconds)


def _count_partner_request(partner: OAuthApplication, endpoint: str) -> tuple[int, int] | None:
    """Count one request against the partner's per-endpoint fixed window.

    Returns ``(count, limit)``, or None when rate limiting is disabled for the
    endpoint (model override of 0). The model's override field takes precedence
    over the conservative default; the window is keyed on partner id +
    window-of-epoch.
    """
    if endpoint not in PARTNER_RATE_LIMIT_DEFAULTS:
        raise ValueError(f"Unknown rate limit endpoint: {endpoint}")

    override = getattr(partner.provisioning.rate_limits, endpoint, None)
    limit = override if override is not None else PARTNER_RATE_LIMIT_DEFAULTS[endpoint]

    if limit <= 0:
        return None

    window_index = int(time.time()) // PARTNER_RATE_LIMIT_WINDOW_SECONDS
    cache_key = f"{PARTNER_RATE_LIMIT_PREFIX}{endpoint}:{partner.id}:{window_index}"
    return _fixed_window_count(cache_key, PARTNER_RATE_LIMIT_WINDOW_SECONDS), limit


def _capture_partner_rate_limited(partner: OAuthApplication, endpoint: str, limit: int, count: int) -> None:
    capture_provisioning_event(
        PARTNER_RATE_LIMIT_EVENT_NAMES[endpoint], "rate_limited", partner=partner, limit=limit, count=count
    )


def enforce_partner_rate_limit(
    partner: OAuthApplication,
    endpoint: str,
    *,
    message: str | None = None,
    envelope: Envelope | None = None,
) -> None:
    """Mid-flow form of :class:`PartnerRateThrottle`, sharing its counters, for
    flows that identify the partner only after dispatch (token exchange,
    account_requests, wizard runs).

    Raises a ``rate_limited`` :class:`ProvisioningError` when the limit is exceeded.
    """
    counted = _count_partner_request(partner, endpoint)
    if counted is None:
        return
    count, limit = counted

    if count > limit:
        _capture_partner_rate_limited(partner, endpoint, limit, count)
        raise ProvisioningError(
            "rate_limited",
            message or f"Rate limit exceeded for this partner ({endpoint}). Try again later.",
            status=429,
            envelope=envelope or "typed",
            retry_after=_window_retry_after(PARTNER_RATE_LIMIT_WINDOW_SECONDS),
        )


class PartnerRateThrottle(BaseThrottle):
    """Per-partner fixed-window limit as a DRF throttle, for views whose
    partner is on ``request.auth`` after authentication."""

    endpoint: ClassVar[str]
    error_message: ClassVar[str]

    def get_partner(self, request: Request) -> OAuthApplication | None:
        auth = request.auth
        if isinstance(auth, OAuthAccessToken):
            return auth.application
        if isinstance(auth, OAuthApplication):
            return auth
        return None

    def allow_request(self, request: Request, view: APIView) -> bool:
        partner = self.get_partner(request)
        if partner is None:
            return True
        counted = _count_partner_request(partner, self.endpoint)
        if counted is None:
            return True
        count, limit = counted
        if count > limit:
            _capture_partner_rate_limited(partner, self.endpoint, limit, count)
            return False
        return True

    def wait(self) -> int:
        return _window_retry_after(PARTNER_RATE_LIMIT_WINDOW_SECONDS)


class ResourceCreatesThrottle(PartnerRateThrottle):
    endpoint = "resource_creates"
    error_message = "Rate limit exceeded for this partner. Try again later."

    def get_partner(self, request: Request) -> OAuthApplication | None:
        # Plain OAuth apps whose tokens reach this endpoint are not partners and carry no
        # partner quota. Keyed on carrying provisioning config rather than on a capability or
        # on is_provisioning_partner, so neither revoking a capability nor disabling the
        # partner outright also un-throttles its outstanding tokens.
        partner = super().get_partner(request)
        if partner is None or not partner.carries_provisioning_config:
            return None
        return partner


class GrantPollThrottle(BaseThrottle):
    """Cap repository-listing polls per grant while the visitor installs the GitHub App."""

    error_message: ClassVar[str] = "Too many repository listing requests for this grant"

    def allow_request(self, request: Request, view: APIView) -> bool:
        grant_id = getattr(view, "kwargs", {}).get("grant_id", "")
        if not grant_id:
            return True
        # DRF checks throttles before the handler loads the grant and rejects a
        # partner mismatch, so the key carries the caller's partner too. Without it a
        # partner that learns another partner's grant id could spend the owner's
        # budget on it. A grant only ever belongs to one partner, so scoping the key
        # this way does not split any legitimate caller's quota.
        partner_id = getattr(request.auth, "id", "unauthenticated")
        window_index = int(time.time()) // GITHUB_GRANT_POLL_RATE_LIMIT_WINDOW_SECONDS
        key = f"{GITHUB_GRANT_POLL_RATE_LIMIT_PREFIX}{partner_id}:{grant_id}:{window_index}"
        count = _fixed_window_count(key, GITHUB_GRANT_POLL_RATE_LIMIT_WINDOW_SECONDS)
        return count <= GITHUB_GRANT_POLL_RATE_LIMIT_MAX

    def wait(self) -> int:
        return _window_retry_after(GITHUB_GRANT_POLL_RATE_LIMIT_WINDOW_SECONDS)


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
            raise ProvisioningError(
                "rate_limited",
                "Too many wizard runs for this user. Try later.",
                status=429,
                envelope="status",
                resource_id=resource_id,
                retry_after=_window_retry_after(window_seconds),
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
            return False

        ident = self.get_ident(request)
        if not ident:
            return True
        ip_key = f"{CLIENT_REGISTRATION_RATE_LIMIT_PREFIX}ip:{sha256(ident.encode()).hexdigest()}:{window_index}"
        if _fixed_window_count(ip_key, CLIENT_REGISTRATION_RATE_LIMIT_WINDOW_SECONDS) > (
            CLIENT_REGISTRATION_IP_RATE_LIMIT_MAX
        ):
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
        if not cimd.is_cimd_client_id(client_id):
            return True
        if OAuthApplication.objects.filter(cimd_metadata_url=client_id).exists():
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
