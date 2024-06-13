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

        # Query could be full of noise so we try and find words that seem like they could be a domain

        good_query_options: list[str] = []
        possible_queries = query.strip().split(" ")

        if len(possible_queries) == 1:
            good_query_options = possible_queries
        else:
            for term in possible_queries:
                if "." in query:
                    # Looks like a domain - lets just use this
                    good_query_options = [query]
                    break
                if len(query) < 5:
                    continue

                good_query_options.append(term)

                if len(good_query_options) >= 3:
                    break

        results = []
        for q in good_query_options:
            res = requests.get(
                f"https://search.logo.dev/api/icons",
                params={
                    "token": settings.LOGO_DEV_TOKEN,
                    "query": q,
                },
            )
            if res.status_code == 200:
                results += res.json()

        parsed = [
            {
                "id": item["domain"],
                "name": item["name"],
                "url": f"{icon_url_base}{item['domain']}",
            }
            for item in results
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
