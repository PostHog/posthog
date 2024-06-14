from django.conf import settings
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

        res = requests.get(
            f"https://search.logo.dev/api/icons",
            params={
                "token": settings.LOGO_DEV_TOKEN,
                "query": query,
            },
        )
        data = res.json()

        parsed = [
            {
                "id": item["domain"],
                "name": item["name"],
                "url": f"{icon_url_base}{item['domain']}",
            }
            for item in data
        ]

        return parsed

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
