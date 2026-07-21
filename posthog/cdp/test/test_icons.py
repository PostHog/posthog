import time
from itertools import count

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict
from rest_framework.exceptions import NotFound

from posthog.cdp.services.icons import CDPIconsService
from posthog.egress.limiter.outbound import get_outbound_rate_limiter

# Fresh team id per test (and per run) so consuming the real per-team budget never accumulates
# into a denial across tests or repeated local runs against a persistent Redis.
_TEAM_IDS = count(time.time_ns() % 1_000_000_000)


def _response(
    status: int = 200,
    content: bytes = b"",
    content_type: str = "image/png",
    cache_control: str | None = None,
) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response._content = content
    response.headers = CaseInsensitiveDict({"Content-Type": content_type})
    if cache_control:
        response.headers["Cache-Control"] = cache_control
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
        self.team_id = next(_TEAM_IDS)

    def test_icon_bytes_are_never_stored_and_browser_caching_is_directed(self) -> None:
        # Storing logo bytes server-side needs a logo.dev data-caching license our plan lacks —
        # every render must re-fetch upstream, with dedup delegated to the browser: logo.dev's own
        # Cache-Control passed through when present, our 24h directive otherwise.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch(
                "requests.request",
                side_effect=[
                    _response(content=b"png-bytes", cache_control="max-age=86400, stale-while-revalidate=600"),
                    _response(content=b"png-bytes"),
                ],
            ) as upstream,
        ):
            first = self.service.get_icon_http_response("linear.app", team_id=self.team_id)
            second = self.service.get_icon_http_response("linear.app", team_id=self.team_id)

        assert upstream.call_count == 2
        assert first.content == b"png-bytes"
        assert first["Cache-Control"] == "max-age=86400, stale-while-revalidate=600"
        assert second["Cache-Control"] == "public, max-age=86400"
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
        # our origin, nor mint a 24h miss entry for a transient failure.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch(
                "requests.request", return_value=_response(status=status, content=b"boom", content_type=content_type)
            ),
        ):
            with self.assertRaises(NotFound):
                self.service.get_icon_http_response("linear.app", team_id=self.team_id)

        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=b"png-bytes")),
        ):
            recovered = self.service.get_icon_http_response("linear.app", team_id=self.team_id)

        assert recovered.content == b"png-bytes"

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
                self.service.get_icon_http_response(icon_id, team_id=self.team_id)

        upstream.assert_not_called()

    def test_id_case_variants_share_one_cached_miss(self) -> None:
        # Domains are case-insensitive — without normalization each case variant would mint its
        # own miss entry and upstream fetch.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(status=404)) as upstream,
        ):
            for icon_id in ("Unknown.Example", "unknown.example"):
                with self.assertRaises(NotFound):
                    self.service.get_icon_http_response(icon_id, fallback="404", team_id=self.team_id)

        assert upstream.call_count == 1

    @parameterized.expand([("theme", {"theme": "sepia"}), ("fallback", {"fallback": "icon"})])
    def test_unsupported_response_shaping_params_are_rejected(self, _name: str, kwargs: dict[str, str]) -> None:
        # theme/fallback become user-suppliable via the icon endpoint later in this stack — an
        # unvalidated value would partition the miss cache with unbounded keys.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response()),
        ):
            with self.assertRaises(ValueError):
                self.service.get_icon_http_response("linear.app", team_id=self.team_id, **kwargs)

    def test_response_shaping_params_are_forwarded_upstream(self) -> None:
        # format/retina/theme/fallback shape logo.dev's bytes — dropping any of them regresses the
        # rendered icon (white-tiled jpg, wrong theme, monogram where the caller expects a 404).
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=b"dark-png")) as upstream,
        ):
            response = self.service.get_icon_http_response(
                "linear.app", theme="dark", fallback="404", team_id=self.team_id
            )

        assert response.content == b"dark-png"
        params = upstream.call_args.kwargs["params"]
        assert params["format"] == "png"
        assert params["retina"] == "true"
        assert params["fallback"] == "404"
        assert params["theme"] == "dark"

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
                    self.service.get_icon_http_response("unknown.example", fallback=fallback, team_id=self.team_id)

        assert upstream.call_count == expected_calls

    def test_cached_miss_is_scoped_to_fallback_mode(self) -> None:
        # A 404-mode miss means "no real logo" — monogram mode can still render a generated
        # monogram for the same domain, so the cached miss must not leak across modes.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch(
                "requests.request",
                side_effect=[_response(status=404), _response(content=b"monogram-png")],
            ) as upstream,
        ):
            with self.assertRaises(NotFound):
                self.service.get_icon_http_response("unknown.example", fallback="404", team_id=self.team_id)
            monogram = self.service.get_icon_http_response("unknown.example", fallback="monogram", team_id=self.team_id)

        assert upstream.call_count == 2
        assert monogram.content == b"monogram-png"

    def test_icon_fetch_degrades_to_not_found_when_budget_exhausted(self) -> None:
        # The icon id is user-controlled, so the fetch runs on a sheddable lane: an exhausted
        # budget must stop upstream calls, not proceed as an advisory limit. Nothing is cached,
        # so the next render retries once the budget window rolls over.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=False),
            patch("requests.request") as upstream,
        ):
            with self.assertRaises(NotFound):
                self.service.get_icon_http_response("linear.app", team_id=self.team_id)

        upstream.assert_not_called()

        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=b"png-bytes")) as upstream,
        ):
            recovered = self.service.get_icon_http_response("linear.app", team_id=self.team_id)

        assert upstream.call_count == 1
        assert recovered.content == b"png-bytes"

    def test_search_degrades_to_empty_when_budget_exhausted(self) -> None:
        # Icon search is sheddable (NORMAL lane) — when the shared budget is spent it must return no
        # results, not surface a 500 to the icon picker.
        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=False),
            patch("requests.request") as upstream,
        ):
            assert self.service.list_icons("linear", icon_url_base="/base?id=", team_id=self.team_id) == []

        upstream.assert_not_called()

    def test_icon_fetch_degrades_to_not_found_when_team_budget_exhausted(self) -> None:
        # The account budget is instance-wide, so the per-team gate is what stops one team's
        # arbitrary-domain requests from blanking icons for every other team. Denial must be
        # charged to the calling team's own key, stay uncached, and never reach upstream.
        with (
            patch("posthog.cdp.services.icons.get_outbound_rate_limiter") as limiter,
            patch("requests.request") as upstream,
        ):
            limiter.return_value.consume_sync.return_value = False
            with self.assertRaises(NotFound):
                self.service.get_icon_http_response("linear.app", team_id=self.team_id)

        upstream.assert_not_called()
        assert limiter.return_value.consume_sync.call_args.args == (f"cdp_icons:team:{self.team_id}",)

        with (
            patch("posthog.egress.logodev.transport.consume_logodev_sync", return_value=True),
            patch("requests.request", return_value=_response(content=b"png-bytes")) as upstream,
        ):
            recovered = self.service.get_icon_http_response("linear.app", team_id=self.team_id)

        assert upstream.call_count == 1
        assert recovered.content == b"png-bytes"

    def test_search_degrades_to_empty_when_team_budget_exhausted(self) -> None:
        # Search queries are free text — the same per-team gate must cover them or a team could
        # drain the shared account budget through the search path instead.
        with (
            patch("posthog.cdp.services.icons.get_outbound_rate_limiter") as limiter,
            patch("requests.request") as upstream,
        ):
            limiter.return_value.consume_sync.return_value = False
            assert self.service.list_icons("linear", icon_url_base="/base?id=", team_id=self.team_id) == []

        upstream.assert_not_called()

    def test_team_budget_policy_is_registered(self) -> None:
        # consume raises for a domain with no registered policy — this catches the registration
        # side effect being lost (e.g. an import shuffle dropping the register_policy call).
        assert get_outbound_rate_limiter().consume_sync(f"cdp_icons:team:{self.team_id}", source="test") is True
