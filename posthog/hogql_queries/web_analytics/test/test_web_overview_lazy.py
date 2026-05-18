import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    SessionTableVersion,
    WebAnalyticsOverviewPrecomputationMode,
    WebOverviewQuery,
)

from posthog.hogql import ast

from posthog.hogql_queries.web_analytics.overview_lazy_strategy import (
    OVERVIEW_LAZY_FEATURE_FLAG_KEY,
    LazyPrecomputationNotReady,
    OverviewLazyStrategy,
    _is_eligible_for_lazy_overview,
    resolve_lazy_overview_mode,
)
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models.utils import uuid7

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
)


class TestWebOverviewLazyDispatch(ClickhouseTestMixin, APIBaseTest):
    """Unit-style tests for the dispatch + resolver. Stubs out ensure_precomputed."""

    QUERY_TIMESTAMP = "2025-01-29T12:00:00"

    def _create_pageview(self, distinct_id: str, session_id: str, pathname: str, timestamp: str):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                "$session_id": session_id,
                "$pathname": pathname,
                "$current_url": f"http://example.com{pathname}",
                "$host": "example.com",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$os": "Mac OS X",
                "$geoip_country_code": "US",
            },
        )

    def _setup_two_sessions(self):
        for p in ("p1", "p2"):
            with freeze_time("2023-12-02"):
                _create_person(team_id=self.team.pk, distinct_ids=[p], properties={"name": p})
        s1, s2 = (str(uuid7("2023-12-02")) for _ in range(2))
        self._create_pageview("p1", s1, "/a", "2023-12-02T12:00:00")
        self._create_pageview("p2", s2, "/a", "2023-12-02T12:00:00")
        self._create_pageview("p2", s2, "/b", "2023-12-02T12:00:30")
        flush_persons_and_events()

    def _runner(
        self,
        *,
        query_mode: WebAnalyticsOverviewPrecomputationMode | None = None,
        date_from: str = "2023-12-01",
        date_to: str = "2023-12-10",
        properties: list | None = None,
        compare: bool = False,
    ) -> WebOverviewQueryRunner:
        modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2)
        query = WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            overviewPrecomputationMode=query_mode,
            compareFilter=CompareFilter(compare=compare) if compare else None,
        )
        return WebOverviewQueryRunner(team=self.team, query=query, modifiers=modifiers)

    def _patch_feature_flag(self, variant: str | None):
        def fake_flag(flag_key, *args, **kwargs):
            if flag_key == OVERVIEW_LAZY_FEATURE_FLAG_KEY:
                return variant
            return None

        return patch(
            "posthog.hogql_queries.web_analytics.overview_lazy_strategy.posthoganalytics.get_feature_flag",
            side_effect=fake_flag,
        )

    def test_dispatch_skipped_when_flag_off_and_no_query_override(self):
        self._setup_two_sessions()
        with self._patch_feature_flag("off"):
            with patch("posthog.hogql_queries.web_analytics.overview_lazy_strategy.ensure_precomputed") as mock_ensure:
                with freeze_time(self.QUERY_TIMESTAMP):
                    self._runner().calculate()
                mock_ensure.assert_not_called()

    def test_dispatch_skipped_when_flag_returns_none(self):
        self._setup_two_sessions()
        with self._patch_feature_flag(None):
            with patch("posthog.hogql_queries.web_analytics.overview_lazy_strategy.ensure_precomputed") as mock_ensure:
                with freeze_time(self.QUERY_TIMESTAMP):
                    self._runner().calculate()
                mock_ensure.assert_not_called()

    def test_dispatch_skipped_when_query_override_off_even_if_flag_on(self):
        self._setup_two_sessions()
        with self._patch_feature_flag("lazy"):
            with patch("posthog.hogql_queries.web_analytics.overview_lazy_strategy.ensure_precomputed") as mock_ensure:
                with freeze_time(self.QUERY_TIMESTAMP):
                    self._runner(query_mode=WebAnalyticsOverviewPrecomputationMode.OFF).calculate()
                mock_ensure.assert_not_called()

    def test_flag_drives_dispatch_when_no_query_override(self):
        self._setup_two_sessions()
        with self._patch_feature_flag("lazy"):
            with patch(
                "posthog.hogql_queries.web_analytics.overview_lazy_strategy.ensure_precomputed",
                return_value=LazyComputationResult(ready=False, job_ids=[]),
            ) as mock_ensure:
                with freeze_time(self.QUERY_TIMESTAMP):
                    self._runner().calculate()
                mock_ensure.assert_called_once()
                assert mock_ensure.call_args.kwargs["table"] == LazyComputationTable.WEB_ANALYTICS_OVERVIEW_LAZY

    def test_query_override_beats_flag(self):
        self._setup_two_sessions()
        with self._patch_feature_flag(None):
            with patch(
                "posthog.hogql_queries.web_analytics.overview_lazy_strategy.ensure_precomputed",
                return_value=LazyComputationResult(ready=False, job_ids=[]),
            ) as mock_ensure:
                with freeze_time(self.QUERY_TIMESTAMP):
                    self._runner(query_mode=WebAnalyticsOverviewPrecomputationMode.LAZY).calculate()
                mock_ensure.assert_called_once()

    def test_flag_unknown_variant_is_ignored(self):
        self._setup_two_sessions()
        with self._patch_feature_flag("not_a_real_mode"):
            with patch("posthog.hogql_queries.web_analytics.overview_lazy_strategy.ensure_precomputed") as mock_ensure:
                with freeze_time(self.QUERY_TIMESTAMP):
                    self._runner().calculate()
                mock_ensure.assert_not_called()

    def test_eligibility_rejects_conversion_goal(self):
        from posthog.schema import CustomEventConversionGoal

        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebOverviewQuery(
                dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-10"),
                properties=[],
                conversionGoal=CustomEventConversionGoal(customEventName="signup"),
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            assert _is_eligible_for_lazy_overview(runner) is False

    def test_eligibility_rejects_unsupported_property(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebOverviewQuery(
                dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-10"),
                properties=[
                    EventPropertyFilter(key="$some_unsupported_prop", operator=PropertyOperator.EXACT, value="x"),
                ],
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            assert _is_eligible_for_lazy_overview(runner) is False

    def test_eligibility_accepts_supported_property(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebOverviewQuery(
                dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-10"),
                properties=[
                    EventPropertyFilter(key="$host", operator=PropertyOperator.EXACT, value="example.com"),
                ],
            )
            runner = WebOverviewQueryRunner(team=self.team, query=query)
            assert _is_eligible_for_lazy_overview(runner) is True

    def test_resolve_mode_returns_none_for_off(self):
        with self._patch_feature_flag(None):
            with freeze_time(self.QUERY_TIMESTAMP):
                runner = self._runner()
                assert resolve_lazy_overview_mode(runner) is None
                runner = self._runner(query_mode=WebAnalyticsOverviewPrecomputationMode.OFF)
                assert resolve_lazy_overview_mode(runner) is None

    def test_resolve_mode_query_override_wins(self):
        with self._patch_feature_flag(None):
            with freeze_time(self.QUERY_TIMESTAMP):
                runner = self._runner(query_mode=WebAnalyticsOverviewPrecomputationMode.LAZY)
                assert resolve_lazy_overview_mode(runner) == WebAnalyticsOverviewPrecomputationMode.LAZY

    def test_strategy_raises_not_ready_on_failure(self):
        self._setup_two_sessions()
        with patch(
            "posthog.hogql_queries.web_analytics.overview_lazy_strategy.ensure_precomputed",
            return_value=LazyComputationResult(ready=False, job_ids=[], errors=["fail"]),
        ):
            with freeze_time(self.QUERY_TIMESTAMP):
                runner = self._runner(query_mode=WebAnalyticsOverviewPrecomputationMode.LAZY)
                strategy = OverviewLazyStrategy(runner)
                with pytest.raises(LazyPrecomputationNotReady, match="fail"):
                    strategy.build_query()

    def test_strategy_passes_properties_placeholder(self):
        """The INSERT must receive a `properties` placeholder so filters end up in the cache key."""
        self._setup_two_sessions()
        with patch(
            "posthog.hogql_queries.web_analytics.overview_lazy_strategy.ensure_precomputed",
            return_value=LazyComputationResult(ready=False, job_ids=[]),
        ) as mock_ensure:
            with freeze_time(self.QUERY_TIMESTAMP):
                self._runner(
                    query_mode=WebAnalyticsOverviewPrecomputationMode.LAZY,
                    properties=[EventPropertyFilter(key="$host", operator=PropertyOperator.EXACT, value="example.com")],
                ).calculate()
            kwargs = mock_ensure.call_args.kwargs
            assert "properties" in kwargs["placeholders"]
            assert isinstance(kwargs["placeholders"]["properties"], ast.Expr)

    def test_fallback_on_not_ready_still_returns_response(self):
        """ready=False → fall through to live (or Dagster). Response shape is unchanged."""
        self._setup_two_sessions()
        with patch(
            "posthog.hogql_queries.web_analytics.overview_lazy_strategy.ensure_precomputed",
            return_value=LazyComputationResult(ready=False, job_ids=[]),
        ):
            with freeze_time(self.QUERY_TIMESTAMP):
                response = self._runner(query_mode=WebAnalyticsOverviewPrecomputationMode.LAZY).calculate()
            assert response.results
            # 5 metrics for non-conversion path (visitors, views, sessions, duration, bounce_rate)
            assert len(response.results) == 5


class TestWebOverviewLazyParity(ClickhouseTestMixin, APIBaseTest):
    """Real lazy-vs-live parity tests. Runs `ensure_precomputed` against the
    test ClickHouse instance and compares results to the live baseline.
    """

    QUERY_TIMESTAMP = "2025-01-29T12:00:00"

    def setUp(self):
        super().setUp()
        from posthog.clickhouse.client import sync_execute

        from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob

        # Isolate the cache between tests in the same class. APIBaseTest reuses
        # team_id, so a second test with the same query_hash could otherwise
        # find stale READY rows from the prior test.
        sync_execute("TRUNCATE TABLE IF EXISTS sharded_web_analytics_overview_lazy")
        PreaggregationJob.objects.filter(team=self.team).delete()

    def _create_pageview(
        self,
        distinct_id: str,
        session_id: str,
        pathname: str,
        timestamp: str,
        properties: dict | None = None,
    ):
        base = {
            "$session_id": session_id,
            "$pathname": pathname,
            "$current_url": f"http://example.com{pathname}",
            "$host": "example.com",
            "$device_type": "Desktop",
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "$geoip_country_code": "US",
        }
        if properties:
            base.update(properties)
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=base,
        )

    def _setup_diverse_sessions(self):
        for p in ("p1", "p2", "p3", "p4", "p5"):
            with freeze_time("2023-12-02"):
                _create_person(team_id=self.team.pk, distinct_ids=[p], properties={"name": p})
        s1, s2, s3, s4, s5 = (str(uuid7("2023-12-02")) for _ in range(5))
        # bounce
        self._create_pageview("p1", s1, "/a", "2023-12-02T12:00:00")
        # non-bounce (2 pageviews)
        self._create_pageview("p2", s2, "/a", "2023-12-02T12:00:00")
        self._create_pageview("p2", s2, "/b", "2023-12-02T12:00:30")
        # bounce
        self._create_pageview("p3", s3, "/b", "2023-12-02T12:00:00")
        # Mobile / FR — non-bounce
        self._create_pageview(
            "p4",
            s4,
            "/a",
            "2023-12-02T13:00:00",
            properties={"$device_type": "Mobile", "$geoip_country_code": "FR"},
        )
        self._create_pageview(
            "p4",
            s4,
            "/b",
            "2023-12-02T13:00:30",
            properties={"$device_type": "Mobile", "$geoip_country_code": "FR"},
        )
        # Tablet / FR — bounce
        self._create_pageview(
            "p5",
            s5,
            "/a",
            "2023-12-02T14:00:00",
            properties={"$device_type": "Tablet", "$geoip_country_code": "FR"},
        )
        flush_persons_and_events()

    def _query(
        self,
        *,
        mode: WebAnalyticsOverviewPrecomputationMode | None,
        properties: list | None = None,
        date_from: str = "2023-12-01",
        date_to: str = "2023-12-10",
        compare: bool = False,
    ):
        modifiers = HogQLQueryModifiers(sessionTableVersion=SessionTableVersion.V2)
        query = WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            overviewPrecomputationMode=mode,
            compareFilter=CompareFilter(compare=compare) if compare else None,
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query, modifiers=modifiers)
        result = runner.calculate()
        # Stash whether the lazy path was actually taken so silent-fallback
        # parity passes are caught by the test assertions.
        result._used_lazy_precomputation = runner.used_lazy_precomputation  # type: ignore[attr-defined]
        return result

    @staticmethod
    def _scalars_by_key(results: list) -> dict:
        """Map WebOverviewItem list to {key: (value, previous)} for comparison."""
        return {item.key: (item.value, item.previous) for item in results}

    def _assert_parity(self, live: list, lazy: list):
        live_map = self._scalars_by_key(live)
        lazy_map = self._scalars_by_key(lazy)
        assert live_map.keys() == lazy_map.keys(), f"key set differs: live={list(live_map)} lazy={list(lazy_map)}"
        for key, (live_v, live_p) in live_map.items():
            lazy_v, lazy_p = lazy_map[key]
            for live_val, lazy_val in ((live_v, lazy_v), (live_p, lazy_p)):
                if live_val is None or lazy_val is None:
                    assert live_val == lazy_val, f"key={key}: live={live_val} lazy={lazy_val}"
                else:
                    # Bounce rate has a Dagster-vs-live divergence on NULL is_bounce
                    # (see overview_lazy_strategy.py KNOWN LIMITATION #6). The test
                    # fixtures avoid NULL is_bounce so this divergence shouldn't trigger.
                    assert abs(live_val - lazy_val) < 1e-6, f"key={key}: live={live_val} lazy={lazy_val}"

    def test_lazy_matches_live_no_filters(self):
        self._setup_diverse_sessions()
        with freeze_time(self.QUERY_TIMESTAMP):
            live = self._query(mode=None)
            lazy = self._query(mode=WebAnalyticsOverviewPrecomputationMode.LAZY)
        assert lazy._used_lazy_precomputation, "lazy path was NOT taken (silent fallback to live)"  # type: ignore[attr-defined]
        self._assert_parity(live.results, lazy.results)

    @parameterized.expand(
        [
            ("device_type", "$device_type", "Desktop"),
            ("country", "$geoip_country_code", "FR"),
            ("host", "$host", "example.com"),
        ]
    )
    def test_lazy_matches_live_with_filter(self, _name, key, value):
        self._setup_diverse_sessions()
        prop_filter = [EventPropertyFilter(key=key, operator=PropertyOperator.EXACT, value=value)]
        with freeze_time(self.QUERY_TIMESTAMP):
            live = self._query(mode=None, properties=prop_filter)
            lazy = self._query(mode=WebAnalyticsOverviewPrecomputationMode.LAZY, properties=prop_filter)
        assert lazy._used_lazy_precomputation, f"lazy path NOT taken (filter={key})"  # type: ignore[attr-defined]
        self._assert_parity(live.results, lazy.results)

    def test_lazy_matches_live_with_compare_filter(self):
        """compareFilter=True → readback must compute both current and previous period scalars."""
        self._setup_diverse_sessions()
        with freeze_time(self.QUERY_TIMESTAMP):
            live = self._query(mode=None, compare=True)
            lazy = self._query(mode=WebAnalyticsOverviewPrecomputationMode.LAZY, compare=True)
        assert lazy._used_lazy_precomputation, "lazy path NOT taken (compareFilter=True)"  # type: ignore[attr-defined]
        self._assert_parity(live.results, lazy.results)
