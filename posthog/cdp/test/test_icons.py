from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import requests
from requests.structures import CaseInsensitiveDict
from rest_framework.exceptions import NotFound

from posthog.cdp.services.icons import CDPIconsService


def _response(status: int = 200, content: bytes = b"", content_type: str = "image/png") -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response._content = content
    response.headers = CaseInsensitiveDict({"Content-Type": content_type})
    prepared = requests.models.PreparedRequest()
    prepared.method = "GET"
    prepared.url = "https://img.logo.dev/linear.app"
    response.request = prepared
    return response


@override_settings(LOGO_DEV_TOKEN="test-token")
class TestCDPIconsService(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.service = CDPIconsService()

    def test_icon_is_served_from_cache_after_first_fetch(self) -> None:
        # The store/CDP UIs render dozens of icons per page view — without the cache every render
        # proxies to logo.dev again, which is the regression this locks out.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=b"png-bytes")) as upstream,
        ):
            first = self.service.get_icon_http_response("linear.app")
            second = self.service.get_icon_http_response("linear.app")

        assert upstream.call_count == 1
        assert first.content == b"png-bytes"
        assert second.content == b"png-bytes"
        assert first["Cache-Control"] == "public, max-age=86400"

    def test_upstream_error_raises_not_found_and_is_not_cached(self) -> None:
        # A logo.dev error body must not be proxied through as an image nor poison the cache for a day.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(status=500, content=b"boom")),
        ):
            with self.assertRaises(NotFound):
                self.service.get_icon_http_response("linear.app")

        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=b"png-bytes")),
        ):
            recovered = self.service.get_icon_http_response("linear.app")

        assert recovered.content == b"png-bytes"

    def test_search_degrades_to_empty_when_budget_exhausted(self) -> None:
        # Icon search is sheddable (NORMAL lane) — when the shared budget is spent it must return no
        # results, not surface a 500 to the icon picker.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=False),
            patch("requests.request") as upstream,
        ):
            assert self.service.list_icons("linear", icon_url_base="/base?id=") == []

        upstream.assert_not_called()
