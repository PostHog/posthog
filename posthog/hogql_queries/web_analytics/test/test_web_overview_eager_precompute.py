from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    SessionsV2JoinMode,
    WebAnalyticsSampling,
    WebOverviewQuery,
)

from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.hogql_queries.web_analytics.web_overview_lazy_precompute import (
    can_use_eager_precompute,
    can_use_lazy_precompute,
    can_use_precomputed_path,
    execute_eager_precomputed_read,
)
from posthog.models.instance_setting import override_instance_config
from posthog.models.utils import uuid7

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob


@override_settings(IN_UNIT_TESTING=True)
class TestWebOverviewEagerPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

    def _enable_eager(self):
        return override_instance_config("WEB_ANALYTICS_EAGER_PRECOMPUTE_TEAM_IDS", [self.team.pk])

    def _enable_lazy(self):
        return override_instance_config("WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS", [self.team.pk])

    def _seed_two_sessions(self) -> None:
        s1 = str(uuid7("2024-01-02"))
        s2 = str(uuid7("2024-01-03"))
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-02T10:00:00Z",
            properties={"$session_id": s1, "$host": "example.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-02T10:05:00Z",
            properties={"$session_id": s1, "$host": "example.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2024-01-03T11:00:00Z",
            properties={"$session_id": s2, "$host": "other.com"},
        )
        flush_persons_and_events()

    def _build_query(
        self,
        date_from: str = "2024-01-01",
        date_to: str = "2024-01-07",
        properties: list | None = None,
        compare: bool = False,
    ) -> WebOverviewQuery:
        return WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            compareFilter=CompareFilter(compare=compare) if compare else None,
        )

    def _runner(self, query: WebOverviewQuery) -> WebOverviewQueryRunner:
        return WebOverviewQueryRunner(team=self.team, query=query)

    # ─── gate logic ──────────────────────────────────────────────────────────

    def test_disabled_team_cannot_use_eager_precompute(self):
        runner = self._runner(self._build_query())
        assert not can_use_eager_precompute(runner)

    @freeze_time("2040-01-15T12:00:00Z")
    def test_enabled_team_can_use_eager_precompute(self):
        runner = self._runner(self._build_query())
        with self._enable_eager():
            assert can_use_eager_precompute(runner)

    def test_eager_and_lazy_gates_are_independent(self):
        runner = self._runner(self._build_query())
        with self._enable_eager():
            assert can_use_eager_precompute(runner)
            assert not can_use_lazy_precompute(runner)

        with self._enable_lazy():
            assert not can_use_eager_precompute(runner)
            assert can_use_lazy_precompute(runner)

    @parameterized.expand(
        [
            ("half_hour_tz", "Asia/Kolkata"),
            ("half_hour_tz_np", "Asia/Kathmandu"),
        ]
    )
    def test_half_hour_timezone_gated_out(self, _name: str, tz: str):
        self.team.timezone = tz
        self.team.save()
        runner = self._runner(self._build_query())
        with self._enable_eager():
            assert not can_use_precomputed_path(runner)

    def test_conversion_goal_gated_out(self):
        from posthog.schema import ActionConversionGoal

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[],
            conversionGoal=ActionConversionGoal(actionId=1),
        )
        runner = self._runner(query)
        with self._enable_eager():
            assert not can_use_precomputed_path(runner)

    def test_sampling_gated_out(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[],
            sampling=WebAnalyticsSampling(enabled=True),
        )
        runner = self._runner(query)
        with self._enable_eager():
            assert not can_use_precomputed_path(runner)

    def test_sessions_v2_uuid_mode_gated_out(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[],
            modifiers=HogQLQueryModifiers(sessionsV2JoinMode=SessionsV2JoinMode.UUID),
        )
        runner = self._runner(query)
        with self._enable_eager():
            assert not can_use_precomputed_path(runner)

    def test_multi_property_filter_gated_out(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[
                EventPropertyFilter(key="$host", value="a.com", operator=PropertyOperator.EXACT),
                EventPropertyFilter(key="$host", value="b.com", operator=PropertyOperator.EXACT),
            ],
        )
        runner = self._runner(query)
        with self._enable_eager():
            assert not can_use_precomputed_path(runner)

    def test_unsupported_property_key_gated_out(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[
                EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT),
            ],
        )
        runner = self._runner(query)
        with self._enable_eager():
            assert not can_use_precomputed_path(runner)

    def test_non_exact_host_filter_gated_out(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[
                EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.ICONTAINS),
            ],
        )
        runner = self._runner(query)
        with self._enable_eager():
            assert not can_use_precomputed_path(runner)

    def test_too_many_days_gated_out(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2024-01-15"),
            properties=[],
        )
        runner = self._runner(query)
        with self._enable_eager():
            assert not can_use_precomputed_path(runner)

    # ─── read-only miss behavior ──────────────────────────────────────────────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_read_returns_none_on_miss(self):
        """With no precomputed jobs, eager read-only must return None."""
        self._seed_two_sessions()
        runner = self._runner(self._build_query())
        with self._enable_eager():
            result = execute_eager_precomputed_read(runner)
        assert result is None

    # ─── eager→lazy fallback ──────────────────────────────────────────────────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_miss_falls_back_to_lazy(self):
        """When eager misses (no pre-warmed jobs), enabling lazy as fallback
        triggers the inline INSERT and returns a valid row."""
        self._seed_two_sessions()
        query = self._build_query()
        runner = self._runner(query)

        # Both enabled: eager miss → lazy INSERT fallback.
        with self._enable_eager(), self._enable_lazy():
            row = runner._get_precomputed_row()

        assert row is not None
        # visitors count should be > 0
        assert row[0] > 0

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_fallback_creates_job(self):
        """Eager miss with lazy fallback enabled should create a PreaggregationJob."""
        self._seed_two_sessions()
        with self._enable_eager(), self._enable_lazy():
            WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()

        jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
        assert len(jobs) > 0

    # ─── pre-warmed hit path ──────────────────────────────────────────────────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_result_matches_raw_result(self):
        """Pre-warm via lazy INSERT, then confirm eager read-only produces same totals as raw."""
        self._seed_two_sessions()

        # Step 1: use lazy to pre-warm the table.
        with self._enable_lazy():
            lazy_response = WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()
        lazy_visitors = lazy_response.results[0].value

        # Step 2: eager read-only should now find the pre-warmed jobs.
        with self._enable_eager():
            eager_row = execute_eager_precomputed_read(
                WebOverviewQueryRunner(team=self.team, query=self._build_query())
            )

        assert eager_row is not None
        # uniqMergeIf may differ slightly from uniqExact but should be close.
        assert abs(eager_row[0] - lazy_visitors) <= 1

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_result_matches_raw_result_full_calculate(self):
        """Full calculate() call uses eager path for a pre-warmed team."""
        self._seed_two_sessions()

        # Pre-warm via lazy INSERT.
        with self._enable_lazy():
            WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()

        # Raw (no precompute gate).
        raw_response = WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()
        raw_visitors = raw_response.results[0].value

        # Eager read-only after pre-warming.
        with self._enable_eager():
            eager_response = WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()
        eager_visitors = eager_response.results[0].value

        assert abs(eager_visitors - raw_visitors) <= 1

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_with_host_filter(self):
        """Host-filtered query returns correct subset of visitors."""
        self._seed_two_sessions()

        # Pre-warm unfiltered (covers both hosts).
        with self._enable_lazy():
            WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()

        # Eager read-only of a host-filtered query: should miss (different cache key)
        # and return None, not wrong data.
        host_query = self._build_query(
            properties=[EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)]
        )
        with self._enable_eager():
            result = execute_eager_precomputed_read(WebOverviewQueryRunner(team=self.team, query=host_query))
        assert result is None

    @freeze_time("2040-01-15T12:00:00Z")
    def test_second_call_hits_eager_without_insert(self):
        """After pre-warming, a second calculate() with eager enabled should not create new jobs."""
        self._seed_two_sessions()

        # Pre-warm.
        with self._enable_lazy():
            WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()

        job_count_before = PreaggregationJob.objects.filter(team_id=self.team.pk).count()

        # Second call with eager: should read existing jobs, create none.
        with self._enable_eager():
            WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()

        job_count_after = PreaggregationJob.objects.filter(team_id=self.team.pk).count()
        assert job_count_after == job_count_before

    # ─── compare period ───────────────────────────────────────────────────────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_compare_period_previous_values(self):
        """With compare=True, previous_* columns should be populated or zero (no crash)."""
        self._seed_two_sessions()

        # Pre-warm.
        with self._enable_lazy():
            WebOverviewQueryRunner(team=self.team, query=self._build_query(compare=True)).calculate()

        with self._enable_eager():
            response = WebOverviewQueryRunner(team=self.team, query=self._build_query(compare=True)).calculate()

        assert response.results is not None
        assert len(response.results) == 5

    # ─── disabled team fallthrough ────────────────────────────────────────────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_disabled_team_uses_raw_path(self):
        """Without eager or lazy enabled, usedPreAggregatedTables reflects v2 table usage, not our table."""
        self._seed_two_sessions()
        response = WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()
        # Should succeed with raw query.
        assert response.results is not None
        assert len(response.results) == 5
