import re
from base64 import b64encode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse

from rest_framework.exceptions import NotFound

from posthog.egress.limiter.policies import Priority
from posthog.egress.logodev.transport import LogoDevEgressBudgetExhausted, logodev_request

ICON_CACHE_SECONDS = 60 * 60 * 24

# Icons are tens of KB even at retina — the cap keeps user-triggered fetches from squatting in the
# shared cache with oversized bodies.
MAX_CACHED_ICON_BYTES = 512 * 1024

# Dot-separated LDH labels, lowercase — the only shape logo.dev serves. Rejecting everything else
# keeps caller-supplied ids from reaching logo.dev or minting cache entries.
_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_DOMAIN_LENGTH = 253

_ALLOWED_THEMES: frozenset[str | None] = frozenset({None, "dark", "light"})
_ALLOWED_FALLBACKS: frozenset[str] = frozenset({"monogram", "404"})


class CDPIconsService:
    @property
    def supported(self) -> bool:
        return bool(settings.LOGO_DEV_TOKEN)

    def list_icons(self, query: str, icon_url_base: str) -> list[dict[str, str]]:
        if not self.supported:
            return []

        cache_key = f"@cdp/list_icons/{b64encode(query.encode()).decode()}"
        data = cache.get(cache_key)

        if data is None:
            try:
                # NORMAL: a typeahead search degrades to no results when the shared budget is tight.
                res = logodev_request(
                    "GET",
                    "https://search.logo.dev/api/icons",
                    source="cdp_icons",
                    priority=Priority.NORMAL,
                    params={"token": settings.LOGO_DEV_TOKEN, "query": query},
                    timeout=10,
                )
            except LogoDevEgressBudgetExhausted:
                return []

            data = [
                {
                    "id": item["domain"],
                    "name": item["name"],
                    "url": f"{icon_url_base}{item['domain']}",
                }
                for item in res.json() or []
            ]

            cache.set(cache_key, data, ICON_CACHE_SECONDS)

        return data

    def get_icon_http_response(self, id: str, theme: str | None = None, fallback: str = "monogram") -> HttpResponse:
        if not self.supported:
            raise NotFound()
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

        # Every parameter that changes logo.dev's response bytes must be part of the key. The
        # validated charset ([a-z0-9.-]) is cache-key-safe raw.
        cache_key = f"@cdp/icon/3/{domain}/{theme or ''}/{fallback}"
        cached = cache.get(cache_key)

        if cached is None:
            params = {
                "token": settings.LOGO_DEV_TOKEN,
                # PNG keeps the logo's transparency — the jpg default flattens it onto a white tile.
                "format": "png",
                "retina": "true",
                "fallback": fallback,
            }
            if theme:
                params["theme"] = theme
            try:
                # NORMAL, not CRITICAL: steady-state renders are served by the cache, and `id` is
                # user-controlled — an exhausted budget must actually stop upstream fetches (and
                # cache fill) rather than being advisory, so this lane is sheddable too.
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
                raise NotFound() from None
            if res.status_code == 404 and fallback == "404":
                # A definitive "no logo for this domain" — cache the miss so rendering an
                # unknown domain doesn't re-proxy to logo.dev for a day. Other upstream
                # errors are treated as transient and stay uncached.
                cached = (None, None)
                cache.set(cache_key, cached, ICON_CACHE_SECONDS)
            elif res.status_code != 200:
                raise NotFound()
            else:
                content_type = res.headers.get("Content-Type", "image/png")
                if not content_type.startswith("image/"):
                    # A 200 that isn't an image (upstream anomaly, error page) must not be proxied
                    # from our origin — and certainly not cached and served publicly for a day.
                    raise NotFound()
                cached = (res.content, content_type)
                # Oversized bodies still render (served through) but must not squat in the cache.
                if len(res.content) <= MAX_CACHED_ICON_BYTES:
                    cache.set(cache_key, cached, ICON_CACHE_SECONDS)

        content, content_type = cached
        if content is None:
            raise NotFound()
        response = HttpResponse(content, content_type=content_type)
        # Public brand assets — let browsers and any CDN cache them instead of re-proxying per render.
        response["Cache-Control"] = f"public, max-age={ICON_CACHE_SECONDS}"
        # The body is upstream-controlled — never let a browser sniff it into something executable.
        response["X-Content-Type-Options"] = "nosniff"
        return response
