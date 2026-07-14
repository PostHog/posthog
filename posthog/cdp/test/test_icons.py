from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
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

    def test_theme_and_fallback_partition_the_cache(self) -> None:
        # A dark-variant logo must never be served to the light UI (nor a monogram where the
        # caller expects a 404) — every parameter that changes logo.dev's bytes keys the cache.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch(
                "requests.request",
                side_effect=[_response(content=b"dark-png"), _response(content=b"light-png")],
            ) as upstream,
        ):
            dark = self.service.get_icon_http_response("linear.app", theme="dark", fallback="404")
            light = self.service.get_icon_http_response("linear.app", theme="light", fallback="404")

        assert upstream.call_count == 2
        assert dark.content == b"dark-png"
        assert light.content == b"light-png"
        params = upstream.call_args.kwargs["params"]
        assert params["format"] == "png"
        assert params["retina"] == "true"
        assert params["fallback"] == "404"
        assert params["theme"] == "light"

    @parameterized.expand(
        [
            ("definitive_miss_is_cached", "404", 1),
            ("monogram_mode_stays_transient", "monogram", 2),
        ]
    )
    def test_upstream_404_caching_depends_on_fallback_mode(
        self, _name: str, fallback: str, expected_calls: int
    ) -> None:
        # With fallback="404" a miss is a definitive answer — without negative caching, every
        # render of an unknown domain would re-proxy to logo.dev. Monogram-mode 404s are
        # anomalies and must stay transient (uncached), as before.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(status=404)) as upstream,
        ):
            for _ in range(2):
                with self.assertRaises(NotFound):
                    self.service.get_icon_http_response("unknown.example", fallback=fallback)

        assert upstream.call_count == expected_calls

    def test_search_degrades_to_empty_when_budget_exhausted(self) -> None:
        # Icon search is sheddable (NORMAL lane) — when the shared budget is spent it must return no
        # results, not surface a 500 to the icon picker.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=False),
            patch("requests.request") as upstream,
        ):
            assert self.service.list_icons("linear", icon_url_base="/base?id=") == []

        upstream.assert_not_called()
