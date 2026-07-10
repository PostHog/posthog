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

    def get_icon_http_response(self, id: str) -> HttpResponse:
        if not self.supported:
            raise NotFound()

        cache_key = f"@cdp/icon/{b64encode(id.encode()).decode()}"
        cached = cache.get(cache_key)

        if cached is None:
            res = logodev_request(
                "GET",
                f"https://img.logo.dev/{id}",
                source="cdp_icons",
                priority=Priority.CRITICAL,
                params={"token": settings.LOGO_DEV_TOKEN},
                timeout=10,
            )
            if res.status_code != 200:
                raise NotFound()
            cached = (res.content, res.headers.get("Content-Type", "image/png"))
            cache.set(cache_key, cached, ICON_CACHE_SECONDS)

        content, content_type = cached
        response = HttpResponse(content, content_type=content_type)
        # Public brand assets — let browsers and any CDN cache them instead of re-proxying per render.
        response["Cache-Control"] = f"public, max-age={ICON_CACHE_SECONDS}"
        return response
