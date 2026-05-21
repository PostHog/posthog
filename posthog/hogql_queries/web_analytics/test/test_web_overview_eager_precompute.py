from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from dagster import build_op_context
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

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
    TRUNCATE_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL,
)
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.hogql_queries.web_analytics.web_overview_lazy_precompute import (
    INSERT_QUERY_TEMPLATE,
    LAZY_TTL_SECONDS,
    _build_placeholders,
    can_use_eager_precompute,
    can_use_lazy_precompute,
    can_use_precomputed_path,
    execute_eager_precomputed_read,
    read_web_overview_if_ready,
)
from posthog.models.instance_setting import override_instance_config
from posthog.models.utils import uuid7

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    QueryInfo,
    compute_query_hash,
    ensure_precomputed,
    read_precomputed_jobs_if_ready,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.dags.eager_web_overview_precompute import (
    _build_dag_placeholders,
    _standard_date_ranges,
    warm_eager_precompute_op,
)


@override_settings(IN_UNIT_TESTING=True)
class TestWebOverviewEagerPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        # Truncate the preaggregated sharded table so data from a previous test
        # cannot bleed through. ClickHouse INSERTs are non-transactional and are
        # not rolled back by Django's test-savepoint mechanism.
        sync_execute(TRUNCATE_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL())

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
        opt_in_lazy: bool = True,
    ) -> WebOverviewQuery:
        return WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            compareFilter=CompareFilter(compare=compare) if compare else None,
            useWebAnalyticsPrecompute=opt_in_lazy,
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
        self._seed_two_sessions()
        runner = self._runner(self._build_query())
        with self._enable_eager():
            result = execute_eager_precomputed_read(runner)
        assert result is None

    # ─── eager→lazy fallback ──────────────────────────────────────────────────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_miss_falls_back_to_lazy(self):
        """When eager misses (no pre-warmed jobs), lazy fallback triggers INSERT and returns a valid row."""
        self._seed_two_sessions()
        runner = self._runner(self._build_query())

        with self._enable_eager(), self._enable_lazy():
            row = runner.get_precomputed_row()

        assert row is not None
        assert row[0] > 0

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_fallback_creates_job(self):
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

        with self._enable_lazy():
            lazy_response = WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()
        lazy_visitors = lazy_response.results[0].value

        with self._enable_eager():
            eager_row = execute_eager_precomputed_read(
                WebOverviewQueryRunner(team=self.team, query=self._build_query())
            )

        assert eager_row is not None
        assert abs(eager_row[0] - lazy_visitors) <= 1

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_result_matches_raw_result_full_calculate(self):
        self._seed_two_sessions()

        with self._enable_lazy():
            WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()

        raw_response = WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()
        raw_visitors = raw_response.results[0].value

        with self._enable_eager():
            eager_response = WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()
        eager_visitors = eager_response.results[0].value

        assert abs(eager_visitors - raw_visitors) <= 1

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_with_host_filter_misses_on_different_cache_key(self):
        """Host-filtered eager read returns None (different cache key from unfiltered pre-warm)."""
        self._seed_two_sessions()

        with self._enable_lazy():
            WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()

        host_query = self._build_query(
            properties=[EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)]
        )
        with self._enable_eager():
            result = execute_eager_precomputed_read(WebOverviewQueryRunner(team=self.team, query=host_query))
        assert result is None

    @freeze_time("2040-01-15T12:00:00Z")
    def test_second_call_hits_eager_without_insert(self):
        """After pre-warming, an eager calculate() should not create new jobs."""
        self._seed_two_sessions()

        with self._enable_lazy():
            WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()

        job_count_before = PreaggregationJob.objects.filter(team_id=self.team.pk).count()

        with self._enable_eager():
            WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()

        job_count_after = PreaggregationJob.objects.filter(team_id=self.team.pk).count()
        assert job_count_after == job_count_before

    # ─── compare period ───────────────────────────────────────────────────────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_eager_compare_period_previous_values(self):
        self._seed_two_sessions()

        with self._enable_lazy():
            WebOverviewQueryRunner(team=self.team, query=self._build_query(compare=True)).calculate()

        with self._enable_eager():
            response = WebOverviewQueryRunner(team=self.team, query=self._build_query(compare=True)).calculate()

        assert response.results is not None
        assert len(response.results) == 5

    # ─── disabled team fallthrough ────────────────────────────────────────────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_disabled_team_uses_raw_path(self):
        self._seed_two_sessions()
        response = WebOverviewQueryRunner(team=self.team, query=self._build_query()).calculate()
        assert response.results is not None
        assert len(response.results) == 5

    # ─── hash parity: DAG placeholders must match query-path placeholders ────

    def _compute_hash(self, placeholders: dict) -> str:
        """Compute the cache-key hash using the same logic as ensure_precomputed."""
        hash_placeholders = {
            **placeholders,
            "time_window_min": ast.Constant(value="__TIME_WINDOW_MIN__"),
            "time_window_max": ast.Constant(value="__TIME_WINDOW_MAX__"),
        }
        parsed = parse_select(INSERT_QUERY_TEMPLATE, placeholders=hash_placeholders)
        assert isinstance(parsed, ast.SelectQuery)
        query_info = QueryInfo(
            query=parsed,
            table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
            timezone=self.team.timezone,
        )
        return compute_query_hash(query_info)

    @freeze_time("2040-01-15T12:00:00Z")
    def test_dag_placeholder_hash_matches_query_path_unfiltered(self):
        """DAG and query-path produce identical cache keys for the unfiltered case."""
        runner = WebOverviewQueryRunner(team=self.team, query=self._build_query())

        query_path_hash = self._compute_hash(_build_placeholders(runner))
        dag_hash = self._compute_hash(_build_dag_placeholders(self.team, host_filter=None, test_account_filter=None))

        assert query_path_hash == dag_hash, (
            "DAG placeholder AST does not match query-path AST — pre-warmed jobs will not be found by read queries"
        )

    @freeze_time("2040-01-15T12:00:00Z")
    def test_dag_placeholder_hash_matches_query_path_with_host_filter(self):
        """DAG and query-path produce identical cache keys when a $host filter is present."""
        host_query = self._build_query(
            properties=[EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)]
        )
        runner = WebOverviewQueryRunner(team=self.team, query=host_query)

        query_path_hash = self._compute_hash(_build_placeholders(runner))
        dag_hash = self._compute_hash(
            _build_dag_placeholders(self.team, host_filter="example.com", test_account_filter=None)
        )

        assert query_path_hash == dag_hash

    @freeze_time("2040-01-15T12:00:00Z")
    def test_dag_placeholder_host_filter_differs_from_unfiltered(self):
        """Different host values hash to different keys (sanity check)."""
        dag_hash_none = self._compute_hash(_build_dag_placeholders(self.team, host_filter=None))
        dag_hash_example = self._compute_hash(_build_dag_placeholders(self.team, host_filter="example.com"))
        dag_hash_other = self._compute_hash(_build_dag_placeholders(self.team, host_filter="other.com"))

        assert dag_hash_none != dag_hash_example
        assert dag_hash_example != dag_hash_other

    # ─── read_precomputed_jobs_if_ready edge cases ────────────────────────────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_pending_job_does_not_satisfy_eager_read(self):
        """A PENDING job is not yet READY — eager read must return not-ready."""
        self._seed_two_sessions()
        runner = self._runner(self._build_query())
        bounds = (
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 8, tzinfo=UTC),
        )
        # Create a PENDING job (not yet committed to ClickHouse)
        PreaggregationJob.objects.create(
            team=self.team,
            query_hash="dummy_pending_hash",
            time_range_start=bounds[0],
            time_range_end=bounds[1],
            status=PreaggregationJob.Status.PENDING,
            expires_at=datetime(2040, 2, 1, tzinfo=UTC),
        )
        with self._enable_eager():
            result = execute_eager_precomputed_read(runner)
        # Must return None because there is no READY job, only PENDING
        assert result is None

    @freeze_time("2040-01-15T12:00:00Z")
    def test_read_precomputed_jobs_if_ready_returns_not_ready_when_no_jobs(self):
        """read_precomputed_jobs_if_ready returns ready=False when no jobs exist at all."""
        runner = self._runner(self._build_query())
        result = read_web_overview_if_ready(
            runner=runner,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 8, tzinfo=UTC),
        )
        assert not result.ready
        assert result.job_ids == []

    @freeze_time("2040-01-15T12:00:00Z")
    def test_read_precomputed_jobs_if_ready_returns_not_ready_when_only_pending(self):
        """read_precomputed_jobs_if_ready ignores PENDING jobs — only READY counts."""
        runner = self._runner(self._build_query())
        placeholders = _build_placeholders(runner)
        hash_placeholders = {
            **placeholders,
            "time_window_min": ast.Constant(value="__TIME_WINDOW_MIN__"),
            "time_window_max": ast.Constant(value="__TIME_WINDOW_MAX__"),
        }
        parsed = parse_select(INSERT_QUERY_TEMPLATE, placeholders=hash_placeholders)
        assert isinstance(parsed, ast.SelectQuery)
        query_info = QueryInfo(
            query=parsed,
            table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
            timezone=self.team.timezone,
        )
        query_hash = compute_query_hash(query_info)

        # Manually create a PENDING job with the correct hash
        PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 8, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=datetime(2040, 2, 1, tzinfo=UTC),
        )

        result = read_web_overview_if_ready(
            runner=runner,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 8, tzinfo=UTC),
        )
        assert not result.ready

    # ─── standard date ranges coverage ───────────────────────────────────────

    @freeze_time("2024-01-15T12:00:00Z")
    def test_standard_date_ranges_covers_7d_query(self):
        """The standard date ranges must include a range that covers a 7-day query."""
        now_utc = datetime.now(UTC)
        ranges = _standard_date_ranges(now_utc)
        query_start = datetime(2024, 1, 8, tzinfo=UTC)
        query_end = datetime(2024, 1, 16, tzinfo=UTC)

        covered = any(r_start <= query_start and r_end >= query_end for r_start, r_end in ranges)
        assert covered, f"No standard range covers [{query_start}, {query_end}). Ranges: {ranges}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_standard_date_ranges_are_five_ranges(self):
        """Expect exactly 5 standard ranges: today, yesterday, 7d, 14d, 30d."""
        now_utc = datetime.now(UTC)
        ranges = _standard_date_ranges(now_utc)
        assert len(ranges) == 5

    @freeze_time("2024-01-15T12:00:00Z")
    def test_standard_date_ranges_today_is_correct(self):
        now_utc = datetime.now(UTC)
        ranges = _standard_date_ranges(now_utc)
        today_start = datetime(2024, 1, 15, tzinfo=UTC)
        today_end = datetime(2024, 1, 16, tzinfo=UTC)
        assert ranges[0] == (today_start, today_end)

    # ─── warm_eager_precompute_op e2e ─────────────────────────────────────────

    @freeze_time("2024-01-15T12:00:00Z")
    def test_warm_op_prewarms_and_query_finds_it(self):
        """End-to-end: warm_eager_precompute_op pre-warms data; subsequent eager read hits without INSERT."""
        self._seed_two_sessions()

        mock_context = build_op_context()

        with self._enable_eager():
            # Run the Dagster op that pre-warms for the team
            warm_eager_precompute_op(mock_context, [self.team.pk])

        # After pre-warming, the eager read should hit on a query spanning the seeded events
        job_count_before = PreaggregationJob.objects.filter(team_id=self.team.pk).count()

        with self._enable_eager():
            runner = WebOverviewQueryRunner(team=self.team, query=self._build_query())
            row = execute_eager_precomputed_read(runner)

        job_count_after = PreaggregationJob.objects.filter(team_id=self.team.pk).count()

        assert row is not None, "Eager read should find pre-warmed data after warm_eager_precompute_op"
        assert job_count_after == job_count_before, "Eager read should not create new jobs on a hit"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_warm_op_creates_jobs_for_team(self):
        """warm_eager_precompute_op creates PreaggregationJob rows for the team."""
        self._seed_two_sessions()
        mock_context = build_op_context()

        with self._enable_eager():
            warm_eager_precompute_op(mock_context, [self.team.pk])

        jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk, status=PreaggregationJob.Status.READY))
        assert len(jobs) > 0, "warm_eager_precompute_op must create at least one READY job"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_warm_op_skips_nonexistent_team(self):
        """warm_eager_precompute_op silently skips a team ID that doesn't exist."""
        mock_context = build_op_context()

        # Should not raise; the op silently skips unknown team IDs
        warm_eager_precompute_op(mock_context, [999_999_999])

    @freeze_time("2024-01-15T12:00:00Z")
    def test_warm_op_idempotent_second_run_reuses_jobs(self):
        """Running warm_eager_precompute_op twice does not create duplicate jobs."""
        self._seed_two_sessions()
        mock_context = build_op_context()

        with self._enable_eager():
            warm_eager_precompute_op(mock_context, [self.team.pk])
            count_after_first = PreaggregationJob.objects.filter(team_id=self.team.pk).count()
            warm_eager_precompute_op(mock_context, [self.team.pk])
            count_after_second = PreaggregationJob.objects.filter(team_id=self.team.pk).count()

        assert count_after_second == count_after_first, "Second warm run must reuse existing READY jobs"

    # ─── ensure_precomputed + read_precomputed_jobs_if_ready round-trip ──────

    @freeze_time("2040-01-15T12:00:00Z")
    def test_ensure_then_read_returns_ready(self):
        """ensure_precomputed (lazy INSERT) followed by read_precomputed_jobs_if_ready returns ready=True."""
        self._seed_two_sessions()
        runner = self._runner(self._build_query())
        time_range_start = datetime(2024, 1, 1, tzinfo=UTC)
        time_range_end = datetime(2024, 1, 8, tzinfo=UTC)
        placeholders = _build_placeholders(runner)

        # Write (lazy INSERT path)
        ensure_result = ensure_precomputed(
            team=self.team,
            insert_query=INSERT_QUERY_TEMPLATE,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            ttl_seconds=LAZY_TTL_SECONDS,
            table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
            placeholders=placeholders,
        )
        assert ensure_result.ready

        # Read (eager read-only path)
        read_result = read_precomputed_jobs_if_ready(
            team=self.team,
            insert_query=INSERT_QUERY_TEMPLATE,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            ttl_seconds=LAZY_TTL_SECONDS,
            table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
            placeholders=placeholders,
        )
        assert read_result.ready
        assert set(read_result.job_ids) == set(ensure_result.job_ids)

    @freeze_time("2040-01-15T12:00:00Z")
    def test_read_with_different_placeholders_misses(self):
        """read_precomputed_jobs_if_ready returns not-ready when placeholders differ from the INSERT."""
        self._seed_two_sessions()
        runner = self._runner(self._build_query())
        time_range_start = datetime(2024, 1, 1, tzinfo=UTC)
        time_range_end = datetime(2024, 1, 8, tzinfo=UTC)
        placeholders = _build_placeholders(runner)

        # Write with unfiltered placeholders
        ensure_precomputed(
            team=self.team,
            insert_query=INSERT_QUERY_TEMPLATE,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            ttl_seconds=LAZY_TTL_SECONDS,
            table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
            placeholders=placeholders,
        )

        # Read with host-filtered placeholders — different cache key → miss
        host_runner = self._runner(
            self._build_query(
                properties=[EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)]
            )
        )
        host_placeholders = _build_placeholders(host_runner)
        read_result = read_precomputed_jobs_if_ready(
            team=self.team,
            insert_query=INSERT_QUERY_TEMPLATE,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            ttl_seconds=LAZY_TTL_SECONDS,
            table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
            placeholders=host_placeholders,
        )
        assert not read_result.ready
