from base64 import b64encode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse

from rest_framework.exceptions import NotFound

from posthog.egress.limiter.policies import Priority
from posthog.egress.logodev.transport import LogoDevEgressBudgetExhausted, logodev_request

ICON_CACHE_SECONDS = 60 * 60 * 24


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
                # NORMAL: a typeahead search degrades to no results when the shared budget is tight,
                # leaving headroom for CRITICAL icon renders.
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

        # Every parameter that changes logo.dev's response bytes must be part of the key.
        cache_key = f"@cdp/icon/2/{b64encode(id.encode()).decode()}/{theme or ''}/{fallback}"
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
            res = logodev_request(
                "GET",
                f"https://img.logo.dev/{id}",
                source="cdp_icons",
                priority=Priority.CRITICAL,
                params=params,
                timeout=10,
            )
            if res.status_code == 404 and fallback == "404":
                # A definitive "no logo for this domain" — cache the miss so rendering an
                # unknown domain doesn't re-proxy to logo.dev for a day. Other upstream
                # errors are treated as transient and stay uncached.
                cached = (None, None)
                cache.set(cache_key, cached, ICON_CACHE_SECONDS)
            elif res.status_code != 200:
                raise NotFound()
            else:
                cached = (res.content, res.headers.get("Content-Type", "image/png"))
                cache.set(cache_key, cached, ICON_CACHE_SECONDS)

        content, content_type = cached
        if content is None:
            raise NotFound()
        response = HttpResponse(content, content_type=content_type)
        # Public brand assets — let browsers and any CDN cache them instead of re-proxying per render.
        response["Cache-Control"] = f"public, max-age={ICON_CACHE_SECONDS}"
        return response
