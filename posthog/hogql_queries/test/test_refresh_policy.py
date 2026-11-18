from typing import cast

from unittest import mock

from django.http import HttpRequest
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.request import Request

from posthog.schema import EventsNode, InsightVizNode, MetricsQuery, TrendsQuery

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.hogql_queries.refresh_policy import ComputeSurface, resolve_execution_mode


def _request(refresh: str | None = None) -> Request:
    drf_request = cast(Request, Request(HttpRequest()))
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

    @parameterized.expand(
        [
            ("metrics", MetricsQuery(clauses=[]).model_dump(), 30),
            ("logs", {"kind": "LogsQuery"}, 5),
            (
                "analytics",
                InsightVizNode(source=TrendsQuery(series=[EventsNode(event="$pageview")])).model_dump(),
                None,
            ),
        ]
    )
    def test_live_refresh_uses_the_class_cache_age(
        self, _name: str, query: dict, expected_cache_age: int | None
    ) -> None:
        with mock.patch("posthog.hogql_queries.refresh_policy.team_flag_enabled_locally", return_value=True):
            mode, cache_age = resolve_execution_mode(
                _request("live"), surface=ComputeSurface.DASHBOARD_TILE, query=query, team=mock.Mock()
            )

        assert mode == ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        assert cache_age == expected_cache_age

    @parameterized.expand([("flag_off", False, False), ("shared_link", True, True)])
    def test_live_refresh_never_computes_without_the_flag_or_on_a_shared_link(
        self, _name: str, flag_on: bool, is_shared: bool
    ) -> None:
        with mock.patch("posthog.hogql_queries.refresh_policy.team_flag_enabled_locally", return_value=flag_on):
            mode, _ = resolve_execution_mode(
                _request("live"),
                surface=ComputeSurface.DASHBOARD_TILE,
                is_shared=is_shared,
                query=MetricsQuery(clauses=[]).model_dump(),
                team=mock.Mock(),
            )

        assert mode not in (
            ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        )
