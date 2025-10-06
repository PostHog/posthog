from base64 import b64encode

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse

import requests
from rest_framework.exceptions import NotFound


class CDPIconsService:
    @property
    def supported(self):
        return bool(settings.LOGO_DEV_TOKEN)

    def list_icons(self, query: str, icon_url_base: str):
        if not self.supported:
            return []

        cache_key = f"@cdp/list_icons/{b64encode(query.encode()).decode()}"
        data = cache.get(cache_key)

        if data is None:
            res = requests.get(
                f"https://search.logo.dev/api/icons",
                params={
                    "token": settings.LOGO_DEV_TOKEN,
                    "query": query,
                },
            )
            data = res.json() or []

            data = [
                {
                    "id": item["domain"],
                    "name": item["name"],
                    "url": f"{icon_url_base}{item['domain']}",
                }
                for item in res.json() or []
            ]

            cache.set(cache_key, data, 60 * 60 * 24)

        return data

    def get_icon_http_response(self, id: str):
        if not self.supported:
            raise NotFound()

        res = requests.get(
            f"https://img.logo.dev/{id}",
            {
                "token": settings.LOGO_DEV_TOKEN,
            },
        )

        return HttpResponse(res.content, content_type=res.headers["Content-Type"])
