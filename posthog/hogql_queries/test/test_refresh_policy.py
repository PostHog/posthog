from typing import cast

from unittest import mock

from django.http import HttpRequest
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.request import Request

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.refresh_policy import ComputeSurface, resolve_execution_mode


def _request(refresh: str | None = None, **query_params: str) -> Request:
    http_request = HttpRequest()
    for key, value in query_params.items():
        http_request.GET[key] = value
    drf_request = cast(Request, Request(http_request))
    drf_request._full_data = {"refresh": refresh} if refresh is not None else {}  # type: ignore[attr-defined]
    return drf_request


class TestResolveExecutionMode(SimpleTestCase):
    @parameterized.expand([(surface,) for surface in ComputeSurface])
    def test_default_is_cache_only_for_every_surface(self, surface: ComputeSurface) -> None:
        # Parity snapshot: with no client refresh param, every surface is cache-only today.
        # When a surface default is deliberately changed, update the expected value here — this
        # assertion is the tripwire that forces that change to be conscious and reviewed.
        mode, cache_age = resolve_execution_mode(_request(), surface=surface)
        assert mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE
        assert cache_age is None

    @parameterized.expand(
        [
            ("blocking", ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE),
            ("force_blocking", ExecutionMode.CALCULATE_BLOCKING_ALWAYS),
            ("async", ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE),
            ("force_cache", ExecutionMode.CACHE_ONLY_NEVER_CALCULATE),
        ]
    )
    def test_explicit_refresh_overrides_surface_default(self, refresh: str, expected: ExecutionMode) -> None:
        # An explicit ?refresh= wins over the surface default, on every surface. This invariant
        # must survive any future change to the default table.
        for surface in ComputeSurface:
            mode, cache_age = resolve_execution_mode(_request(refresh), surface=surface)
            assert mode == expected, surface
            assert cache_age is None

    def test_explicit_refresh_false_stays_cache_only_when_surface_default_is_flipped(self) -> None:
        # An explicit ?refresh=false is the client opting out of a recompute; it must stay
        # cache-only even once a surface default is flipped off cache-only, whereas an absent
        # param follows the (flipped) surface default. Guards the exact regression where explicit
        # opt-out silently inherits a non-cache default.
        with mock.patch.dict(
            "posthog.hogql_queries.refresh_policy.SURFACE_DEFAULT_EXECUTION_MODE",
            {ComputeSurface.DASHBOARD_TILE: ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE},
        ):
            absent_mode, _ = resolve_execution_mode(_request(), surface=ComputeSurface.DASHBOARD_TILE)
            assert absent_mode == ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE

            false_mode, _ = resolve_execution_mode(_request("false"), surface=ComputeSurface.DASHBOARD_TILE)
            assert false_mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE

    @parameterized.expand([("filters_override",), ("variables_override",), ("tile_filters_override",)])
    def test_client_overrides_escalate_past_cache_only(self, param: str) -> None:
        # Overrides change the cache key, so nothing warms it — cache-only would hand the UI
        # result: null and a "Chart data didn't load" tile.
        for surface in ComputeSurface:
            mode, _ = resolve_execution_mode(_request(**{param: '{"date_from":"-14d"}'}), surface=surface)
            assert mode == ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS, surface

    def test_overrides_do_not_escalate_an_explicit_opt_out(self) -> None:
        mode, _ = resolve_execution_mode(
            _request("force_cache", filters_override='{"date_from":"-14d"}'), surface=ComputeSurface.DASHBOARD_TILE
        )
        assert mode == ExecutionMode.CACHE_ONLY_NEVER_CALCULATE

    def test_overrides_do_not_change_the_shared_path(self) -> None:
        # Shared/embedded rendering ignores client overrides entirely, so its cache key — and its
        # execution mode — must be identical with and without them.
        without = resolve_execution_mode(_request(), surface=ComputeSurface.SHARED, is_shared=True)
        with_override = resolve_execution_mode(
            _request(filters_override='{"date_from":"-14d"}'), surface=ComputeSurface.SHARED, is_shared=True
        )
        assert with_override == without

    def test_shared_flag_applies_the_clamp(self) -> None:
        # resolve_execution_mode's own responsibility is to route through the shared clamp iff
        # is_shared (the exhaustive clamp mapping is covered in test_query_runner). Contrast the
        # same request with/without the flag: only the shared path carries a staleness window,
        # and dropping that cache_age would silently disable the shared force-refresh throttle.
        unshared_mode, unshared_cache_age = resolve_execution_mode(
            _request("force_blocking"), surface=ComputeSurface.SHARED, is_shared=False
        )
        assert unshared_mode == ExecutionMode.CALCULATE_BLOCKING_ALWAYS
        assert unshared_cache_age is None

        shared_mode, shared_cache_age = resolve_execution_mode(
            _request("force_blocking"), surface=ComputeSurface.SHARED, is_shared=True
        )
        assert shared_mode == ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        assert shared_cache_age is not None and shared_cache_age > 0
