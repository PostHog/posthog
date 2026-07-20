from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict
from rest_framework.exceptions import NotFound

from posthog.cdp.services.icons import MAX_CACHED_ICON_BYTES, CDPIconsService


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
        assert first["X-Content-Type-Options"] == "nosniff"

    @parameterized.expand(
        [
            ("server_error", 500, "image/png"),
            ("non_image_200", 200, "text/html"),
        ]
    )
    def test_bad_upstream_response_raises_not_found_and_is_not_cached(
        self, _name: str, status: int, content_type: str
    ) -> None:
        # A logo.dev error body — or a 200 that isn't an image — must not be proxied through from
        # our origin nor poison the cache for a day.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch(
                "requests.request", return_value=_response(status=status, content=b"boom", content_type=content_type)
            ),
        ):
            with self.assertRaises(NotFound):
                self.service.get_icon_http_response("linear.app")

        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=b"png-bytes")),
        ):
            recovered = self.service.get_icon_http_response("linear.app")

        assert recovered.content == b"png-bytes"

    def test_oversized_icon_is_served_but_not_cached(self) -> None:
        # An oversized body must not squat in the shared cache — but it still renders, so a
        # legitimate huge asset degrades to a re-fetch per render rather than a 404.
        big = b"x" * (MAX_CACHED_ICON_BYTES + 1)
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=big)) as upstream,
        ):
            first = self.service.get_icon_http_response("linear.app")
            second = self.service.get_icon_http_response("linear.app")

        assert upstream.call_count == 2
        assert first.content == big
        assert second.content == big

    @parameterized.expand(
        [
            ("free_text", "not a domain!"),
            ("no_tld", "linear"),
            ("path_traversal", "../../etc/passwd"),
            ("query_injection", "linear.app?fallback=monogram"),
            ("extra_path_segment", "linear.app/evil"),
            ("overlong", "a" * 250 + ".app"),
        ]
    )
    def test_non_domain_id_is_rejected_without_upstream_call(self, _name: str, icon_id: str) -> None:
        # `id` is a caller-supplied query param — anything not domain-shaped must never reach
        # logo.dev nor mint a 24h entry in the shared cache.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request") as upstream,
        ):
            with self.assertRaises(NotFound):
                self.service.get_icon_http_response(icon_id)

        upstream.assert_not_called()

    def test_id_case_variants_share_one_cache_entry(self) -> None:
        # Domains are case-insensitive — without normalization each case variant would mint its
        # own cache entry and upstream fetch.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=b"png-bytes")) as upstream,
        ):
            self.service.get_icon_http_response("Linear.App")
            self.service.get_icon_http_response("linear.app")

        assert upstream.call_count == 1

    @parameterized.expand([("theme", {"theme": "sepia"}), ("fallback", {"fallback": "icon"})])
    def test_unsupported_response_shaping_params_are_rejected(self, _name: str, kwargs: dict[str, str]) -> None:
        # theme/fallback become user-suppliable via the icon endpoint later in this stack — an
        # unvalidated value would partition the cache with unbounded keys.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response()),
        ):
            with self.assertRaises(ValueError):
                self.service.get_icon_http_response("linear.app", **kwargs)

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

    def test_icon_fetch_degrades_to_not_found_when_budget_exhausted(self) -> None:
        # The icon id is user-controlled, so the fetch runs on a sheddable lane: an exhausted
        # budget must stop upstream calls (and cache fill), not proceed as an advisory limit.
        # Nothing is cached, so the next render retries once the budget window rolls over.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=False),
            patch("requests.request") as upstream,
        ):
            with self.assertRaises(NotFound):
                self.service.get_icon_http_response("linear.app")

        upstream.assert_not_called()

        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=b"png-bytes")) as upstream,
        ):
            recovered = self.service.get_icon_http_response("linear.app")

        assert upstream.call_count == 1
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
