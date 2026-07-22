import re
from base64 import b64encode
from typing import NoReturn, cast

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse

import requests
import structlog
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound

from posthog.egress.limiter.outbound import get_outbound_rate_limiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy
from posthog.egress.logodev.transport import LogoDevEgressBudgetExhausted, logodev_request

ICON_CACHE_SECONDS = 60 * 60 * 24

logger = structlog.get_logger(__name__)

# Per-team fairness gate in front of the instance-wide logo.dev account budget. Icon domains and
# search queries are caller-supplied and only definitive misses are cached, so without a per-team
# ceiling one team requesting endless unique domains could drain the shared account budget and
# blank icons for every other team on the instance. The ceilings leave a cold catalog render (tens
# of uncached icons) untouched while sitting well below the account budget, so a single team can't
# sustain instance-wide exhaustion. This is a consumer-side concern: the logodev egress limiter
# stays a pure account-budget mirror of what logo.dev actually meters.
_TEAM_BUDGET_DOMAIN = "cdp_icons"
_DEFAULT_TEAM_PER_MINUTE_BUDGET = 120
_DEFAULT_TEAM_HOURLY_BUDGET = 1_000


# Registered as a provider so the budgets are read at acquire time — a settings override applies
# without a process restart, matching the egress domains.
def _team_budget_policy(key: str) -> RatePolicy:
    per_minute = int(getattr(settings, "CDP_ICONS_TEAM_PER_MINUTE_BUDGET", _DEFAULT_TEAM_PER_MINUTE_BUDGET))
    hourly = int(getattr(settings, "CDP_ICONS_TEAM_HOURLY_BUDGET", _DEFAULT_TEAM_HOURLY_BUDGET))
    return RatePolicy(limits=((per_minute, 60.0), (hourly, 3600.0)), in_memory_divider=4)


register_policy(_TEAM_BUDGET_DOMAIN, _team_budget_policy)


def _consume_team_icon_budget(team_id: int) -> bool:
    """Reserve one upstream logo.dev call against ``team_id``'s icon budget. Returns False when the
    team's budget is exhausted — degrade for that team only, before touching the account budget."""
    return get_outbound_rate_limiter().consume_sync(
        f"{_TEAM_BUDGET_DOMAIN}:team:{team_id}", priority=Priority.NORMAL, source="cdp_icons"
    )


# Dot-separated LDH labels, lowercase — the only shape logo.dev serves. Rejecting everything else
# keeps caller-supplied ids from reaching logo.dev or minting cache entries.
_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_DOMAIN_LENGTH = 253

_ALLOWED_THEMES: frozenset[str | None] = frozenset({None, "dark", "light"})
_ALLOWED_FALLBACKS: frozenset[str] = frozenset({"monogram", "404"})


class LogoDevBadGateway(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The logo provider returned an invalid response."
    default_code = "logo_provider_error"


class LogoDevUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The logo provider is temporarily unavailable."
    default_code = "logo_provider_unavailable"


def _parse_search_results(payload: object, icon_url_base: str) -> list[dict[str, str]] | None:
    if not isinstance(payload, list):
        return None

    results: list[dict[str, str]] = []
    for raw_item in cast(list[object], payload):
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[object, object], raw_item)
        domain = item.get("domain")
        name = item.get("name")
        if not isinstance(domain, str) or not isinstance(name, str):
            continue
        domain = domain.lower()
        if len(domain) > _MAX_DOMAIN_LENGTH or not _DOMAIN_RE.match(domain):
            continue
        results.append({"id": domain, "name": name, "url": f"{icon_url_base}{domain}"})

    return results


def _raise_icon_provider_error(status_code: int) -> NoReturn:
    logger.warning("logodev_icon_request_failed", status_code=status_code)
    if status_code == status.HTTP_429_TOO_MANY_REQUESTS or status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        raise LogoDevUnavailable()
    raise LogoDevBadGateway()


class CDPIconsService:
    def list_icons(self, query: str, icon_url_base: str, *, team_id: int) -> list[dict[str, str]]:
        secret_key = settings.LOGO_DEV_SECRET_KEY
        if not secret_key:
            return []
        if not secret_key.startswith("sk_"):
            logger.warning("logodev_configuration_invalid", credential_type="secret_key")
            return []

        cache_key = f"@cdp/list_icons/{b64encode(query.encode()).decode()}"
        cached_data: list[dict[str, str]] | None = cache.get(cache_key)

        if cached_data is not None:
            return cached_data

        # Queries are free-text, so cached entries don't bound upstream volume — gate uncached
        # searches on the caller's team budget before they reach the shared account budget.
        if not _consume_team_icon_budget(team_id):
            return []
        try:
            # NORMAL: a typeahead search degrades to no results when the shared budget is tight.
            res = logodev_request(
                "GET",
                "https://api.logo.dev/search",
                source="cdp_icons",
                priority=Priority.NORMAL,
                headers={"Authorization": f"Bearer {secret_key}"},
                params={"q": query},
                timeout=10,
            )
        except LogoDevEgressBudgetExhausted:
            return []
        except requests.RequestException:
            logger.warning("logodev_search_request_failed", failure_type="transport")
            return []

        if res.status_code != status.HTTP_200_OK:
            logger.warning("logodev_search_request_failed", status_code=res.status_code)
            return []

        try:
            payload: object = res.json()
        except requests.exceptions.JSONDecodeError:
            logger.warning("logodev_search_request_failed", failure_type="invalid_json")
            return []

        data = _parse_search_results(payload, icon_url_base)
        if data is None:
            logger.warning("logodev_search_request_failed", failure_type="invalid_schema")
            return []

        cache.set(cache_key, data, ICON_CACHE_SECONDS)
        return data

    def get_icon_http_response(
        self, id: str, theme: str | None = None, fallback: str = "monogram", *, team_id: int
    ) -> HttpResponse:
        if theme not in _ALLOWED_THEMES:
            raise ValueError(f"Unsupported logo.dev theme: {theme!r}")
        if fallback not in _ALLOWED_FALLBACKS:
            raise ValueError(f"Unsupported logo.dev fallback mode: {fallback!r}")

        # `id` is caller-supplied (a query param on the icon endpoint) — anything not domain-shaped
        # must never reach logo.dev nor mint a 24h entry in the shared cache. Domains are
        # case-insensitive, so lowercase first or each case variant would cache separately.
        domain = id.lower()
        if len(domain) > _MAX_DOMAIN_LENGTH or not _DOMAIN_RE.match(domain):
            raise NotFound()

        publishable_key = settings.LOGO_DEV_PUBLISHABLE_KEY
        if not publishable_key:
            raise LogoDevUnavailable("The logo provider is not configured.")
        if not publishable_key.startswith("pk_"):
            logger.warning("logodev_configuration_invalid", credential_type="publishable_key")
            raise LogoDevUnavailable("The logo provider is configured with an invalid publishable key.")

        # Only the *fact* of a definitive miss is ever cached. Logo bytes must not be stored on our
        # infrastructure — logo.dev gates that behind a data-caching license our plan doesn't
        # include — so byte-level dedup is delegated to browser caching via Cache-Control below.
        # Every parameter that changes logo.dev's answer is part of the key; the validated charset
        # ([a-z0-9.-]) is cache-key-safe raw.
        miss_cache_key = f"@cdp/icon_miss/1/{domain}/{theme or ''}/{fallback}"
        if cache.get(miss_cache_key):
            raise NotFound()

        # Unique domains bypass the miss cache by construction, so gate the uncached fetch on the
        # caller's team budget. Transient and uncached, like account-budget exhaustion below.
        if not _consume_team_icon_budget(team_id):
            raise LogoDevUnavailable()

        params = {
            "token": publishable_key,
            # PNG keeps the logo's transparency — the jpg default flattens it onto a white tile.
            "format": "png",
            "retina": "true",
            "fallback": fallback,
        }
        if theme:
            params["theme"] = theme
        try:
            # NORMAL, not CRITICAL: `id` is user-controlled — an exhausted budget must actually
            # stop upstream fetches rather than being advisory, so this lane is sheddable too.
            res = logodev_request(
                "GET",
                f"https://img.logo.dev/{domain}",
                source="cdp_icons",
                priority=Priority.NORMAL,
                params=params,
                timeout=10,
            )
        except LogoDevEgressBudgetExhausted:
            # Transient and uncached — the next render retries once the budget window rolls over.
            raise LogoDevUnavailable() from None
        except requests.RequestException:
            logger.warning("logodev_icon_request_failed", failure_type="transport")
            raise LogoDevUnavailable() from None
        if res.status_code == 404 and fallback == "404":
            # A definitive "no logo for this domain" — cache the miss so rendering an unknown
            # domain doesn't re-proxy to logo.dev for a day. Other upstream errors are treated
            # as transient and stay uncached.
            cache.set(miss_cache_key, True, ICON_CACHE_SECONDS)
            raise NotFound()
        if res.status_code != 200:
            _raise_icon_provider_error(res.status_code)
        content_type = res.headers.get("Content-Type", "image/png")
        if not content_type.startswith("image/"):
            # A 200 that isn't an image (upstream anomaly, error page) must not be proxied from
            # our origin.
            logger.warning("logodev_icon_request_failed", failure_type="non_image_response")
            raise LogoDevBadGateway()

        response = HttpResponse(res.content, content_type=content_type)
        # Public brand assets — browser caching is the only dedup layer, so honor logo.dev's own
        # caching directive when present (their TTL tuning propagates) and match it otherwise.
        response["Cache-Control"] = res.headers.get("Cache-Control", f"public, max-age={ICON_CACHE_SECONDS}")
        # The body is upstream-controlled — never let a browser sniff it into something executable.
        response["X-Content-Type-Options"] = "nosniff"
        return response
