import time as time_mod
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.db import IntegrityError
from django.utils import timezone as django_timezone

from clickhouse_driver.errors import ServerException
from parameterized import parameterized

from posthog.schema import BaseMathType, DateRange, EventsNode, HogQLQueryModifiers, TrendsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner

from products.analytics_platform.backend.lazy_computation.computation_notifications import (
    job_channel,
    set_ch_query_started,
)
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_TTL_SCHEDULE,
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    NON_RETRYABLE_CLICKHOUSE_ERROR_CODES,
    ComputationExecutor,
    ComputationResult,
    LazyComputationTable,
    QueryInfo,
    TtlSchedule,
    _build_manual_insert_sql,
    build_lazy_computation_insert_sql,
    compute_query_hash,
    create_lazy_computation_job,
    ensure_precomputed,
    filter_overlapping_jobs,
    find_missing_contiguous_windows,
    is_non_retryable_error,
    parse_ttl_schedule,
    split_ranges_by_ttl,
)
from products.analytics_platform.backend.models import PreaggregationJob


class TestComputationJob(BaseTest):
    def test_create_and_read_job_by_hash(self):
        query_hash = "abc123def456"

        job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )

        retrieved = PreaggregationJob.objects.filter(
            team=self.team,
            query_hash=query_hash,
        ).first()

        assert retrieved is not None
        assert retrieved.id == job.id
        assert retrieved.query_hash == query_hash


class TestComputeQueryHash(BaseTest):
    @parameterized.expand(
        [
            (
                "different_event_filter",
                ("SELECT uniqExact(person_id) FROM events WHERE event = '$pageview'", None),
                ("SELECT uniqExact(person_id) FROM events WHERE event = '$pageleave'", None),
            ),
            (
                "different_aggregation",
                ("SELECT uniqExact(person_id) FROM events WHERE event = '$pageview'", None),
                ("SELECT count() FROM events WHERE event = '$pageview'", None),
            ),
            (
                "different_timezone",
                ("SELECT uniqExact(person_id) FROM events", "UTC"),
                ("SELECT uniqExact(person_id) FROM events", "America/New_York"),
            ),
        ]
    )
    def test_similar_queries_hash_differently(self, name, qt1, qt2):
        (q1, t1) = qt1
        (q2, t2) = qt2
        s1 = parse_select(q1)
        s2 = parse_select(q2)
        assert isinstance(s1, ast.SelectQuery)
        assert isinstance(s2, ast.SelectQuery)
        query_info1 = QueryInfo(query=s1, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone=t1)
        query_info2 = QueryInfo(query=s2, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone=t2)

        hash1 = compute_query_hash(query_info1)
        hash2 = compute_query_hash(query_info2)

        assert hash1 != hash2, f"Expected different hashes for {name}"


class TestFindMissingContiguousWindows(BaseTest):
    def test_returns_single_contiguous_range_if_no_jobs_exist(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 4, tzinfo=UTC)

        existing_jobs: list[PreaggregationJob] = []

        missing = find_missing_contiguous_windows(existing_jobs, start, end)

        # Should merge Jan 1, 2, 3 into a single contiguous range
        assert len(missing) == 1
        assert missing[0] == (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 4, tzinfo=UTC))

    def test_returns_two_ranges_when_middle_job_exists(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 4, tzinfo=UTC)

        # Create a job for Jan 2
        jan2_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 2, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 3, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )

        missing = find_missing_contiguous_windows([jan2_job], start, end)

        # Should return two separate ranges: Jan 1 and Jan 3
        assert len(missing) == 2
        assert missing[0] == (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
        assert missing[1] == (datetime(2024, 1, 3, tzinfo=UTC), datetime(2024, 1, 4, tzinfo=UTC))

    def test_returns_multiple_ranges_with_gaps(self):
        """Test that multiple non-contiguous gaps result in multiple ranges."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 10, tzinfo=UTC)

        # Create jobs for Jan 3-4 and Jan 7
        jan3_4_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 3, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 5, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        jan7_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 7, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 8, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )

        missing = find_missing_contiguous_windows([jan3_4_job, jan7_job], start, end)

        # Missing: Jan 1-2, Jan 5-6, Jan 8-9 -> 3 contiguous ranges
        assert len(missing) == 3
        assert missing[0] == (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 3, tzinfo=UTC))
        assert missing[1] == (datetime(2024, 1, 5, tzinfo=UTC), datetime(2024, 1, 7, tzinfo=UTC))
        assert missing[2] == (datetime(2024, 1, 8, tzinfo=UTC), datetime(2024, 1, 10, tzinfo=UTC))

    def test_treats_pending_job_as_covered(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 4, tzinfo=UTC)

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 2, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 3, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
        )

        missing = find_missing_contiguous_windows([pending_job], start, end)

        # PENDING job should be treated as covered (someone is already working on it)
        assert len(missing) == 2
        assert missing[0] == (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC))
        assert missing[1] == (datetime(2024, 1, 3, tzinfo=UTC), datetime(2024, 1, 4, tzinfo=UTC))


class TestFilterOverlappingJobs(BaseTest):
    def test_empty_list(self):
        result = filter_overlapping_jobs([])
        assert result == []

    def test_single_job(self):
        job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        result = filter_overlapping_jobs([job])
        assert len(result) == 1
        assert result[0].id == job.id

    def test_non_overlapping_jobs(self):
        job1 = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        job2 = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 3, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 4, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        result = filter_overlapping_jobs([job1, job2])
        assert len(result) == 2

    def test_overlapping_jobs_keeps_newer(self):
        """When two jobs overlap, the more recently created one should be kept."""
        older_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 3, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        newer_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 2, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 4, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        result = filter_overlapping_jobs([older_job, newer_job])
        assert len(result) == 1
        assert result[0].id == newer_job.id

    def test_adjacent_jobs_not_overlapping(self):
        """Jobs that touch at boundaries [1,2) and [2,3) should not be considered overlapping."""
        job1 = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        job2 = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 2, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 3, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        result = filter_overlapping_jobs([job1, job2])
        assert len(result) == 2

    def test_multiple_overlapping_keeps_newest(self):
        """With multiple overlapping jobs, only the newest should be kept."""
        job1 = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 5, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        job2 = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 2, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 4, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        job3 = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 3, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 6, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        result = filter_overlapping_jobs([job1, job2, job3])
        # job3 is newest, so it's selected first. Then job1 and job2 both overlap with job3.
        assert len(result) == 1
        assert result[0].id == job3.id

    def test_mixed_overlapping_and_non_overlapping(self):
        """Some jobs overlap, others don't - keep non-overlapping ones plus newest of overlapping."""
        # Non-overlapping job at the start
        job_early = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        # Two overlapping jobs in the middle
        job_mid_old = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 5, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 8, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        job_mid_new = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 6, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 9, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )
        # Non-overlapping job at the end
        job_late = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 15, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 16, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
        )

        result = filter_overlapping_jobs([job_early, job_mid_old, job_mid_new, job_late])

        # Should have: job_late (newest), job_mid_new (newest of overlap), job_early (no overlap)
        assert len(result) == 3
        result_ids = {j.id for j in result}
        assert job_early.id in result_ids
        assert job_mid_new.id in result_ids
        assert job_late.id in result_ids
        assert job_mid_old.id not in result_ids


class TestBuildComputationInsertSQL(BaseTest):
    def _make_select_query(self, where_clause: str = "") -> ast.SelectQuery:
        """Create a valid computation select query with 3 expressions."""
        where = f"WHERE {where_clause}" if where_clause else ""
        s = parse_select(f"SELECT 1 as col1, 2 as col2, 3 as col3 FROM events {where}")
        assert isinstance(s, ast.SelectQuery)
        return s

    def test_query_without_where(self):
        job_id = "11111111-1111-1111-1111-111111111111"
        select_query = self._make_select_query()
        expires_at = datetime(2024, 1, 8, tzinfo=UTC)

        sql, values = build_lazy_computation_insert_sql(
            team=self.team,
            job_id=job_id,
            select_query=select_query,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            expires_at=expires_at,
        )

        # Check that SQL structure is correct
        assert "INSERT INTO preaggregation_results" in sql
        assert "team_id" in sql
        assert "job_id" in sql
        assert "expires_at" in sql

    def test_query_with_existing_where(self):
        job_id = "11111111-1111-1111-1111-111111111111"
        select_query = self._make_select_query("event = 'test'")
        expires_at = datetime(2024, 1, 8, tzinfo=UTC)

        sql, values = build_lazy_computation_insert_sql(
            team=self.team,
            job_id=job_id,
            select_query=select_query,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            expires_at=expires_at,
        )

        # Check that SQL structure is correct and includes event filter
        assert "INSERT INTO preaggregation_results" in sql
        assert "expires_at" in sql

    @parameterized.expand(
        [
            ("job_id_1", "11111111-1111-1111-1111-111111111111"),
            ("job_id_2", "22222222-2222-2222-2222-222222222222"),
        ]
    )
    def test_different_job_ids(self, name, job_id):
        select_query = self._make_select_query()
        expires_at = datetime(2024, 1, 8, tzinfo=UTC)

        sql, values = build_lazy_computation_insert_sql(
            team=self.team,
            job_id=job_id,
            select_query=select_query,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            expires_at=expires_at,
        )

        # Check that SQL structure is correct and job_id is in the parameterized values
        assert "job_id" in sql
        assert job_id in values.values()

    def test_does_not_mutate_original_query(self):
        job_id = "11111111-1111-1111-1111-111111111111"
        select_query = self._make_select_query()
        original_where = select_query.where
        original_select_len = len(select_query.select)
        expires_at = datetime(2024, 1, 8, tzinfo=UTC)

        build_lazy_computation_insert_sql(
            team=self.team,
            job_id=job_id,
            select_query=select_query,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            expires_at=expires_at,
        )

        assert select_query.where == original_where
        assert len(select_query.select) == original_select_len


class TestExecuteComputationJobs(ClickhouseTestMixin, BaseTest):
    def _make_computation_query(self) -> ast.SelectQuery:
        """Create a query that produces columns matching the computation table schema."""
        s = parse_select(
            """
            SELECT
                toStartOfDay(timestamp) as time_window_start,
                [] as breakdown_value,
                uniqExactState(person_id) as uniq_exact_state
            FROM events
            WHERE event = '$pageview'
            GROUP BY time_window_start
            """
        )
        assert isinstance(s, ast.SelectQuery)
        return s

    def _create_pageview_events(self):
        """Create pageview events across Jan 2024."""
        _create_event(
            team=self.team, event="$pageview", distinct_id="user1", timestamp=datetime(2024, 1, 1, 12, tzinfo=UTC)
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="user2", timestamp=datetime(2024, 1, 2, 12, tzinfo=UTC)
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="user3", timestamp=datetime(2024, 1, 3, 12, tzinfo=UTC)
        )

    def _query_computation_results(self, job_ids: list) -> list:
        """Query the computation results table for specific job IDs."""
        job_id_strs = [str(job_id) for job_id in job_ids]
        result = sync_execute(
            f"""
            SELECT
                team_id,
                job_id,
                time_window_start,
                breakdown_value,
                uniqExactMerge(uniq_exact_state) as unique_users
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
            GROUP BY team_id, job_id, time_window_start, breakdown_value
            ORDER BY time_window_start
            """,
            {"team_id": self.team.id, "job_ids": job_id_strs},
        )
        return result

    def test_creates_single_job_for_contiguous_date_range(self):
        self._create_pageview_events()

        query = self._make_computation_query()
        query_info = QueryInfo(query=query, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone="UTC")

        result = ComputationExecutor().execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 4, tzinfo=UTC),
        )

        assert isinstance(result, ComputationResult)
        assert result.ready is True
        assert len(result.errors) == 0
        assert len(result.job_ids) == 1

        # Verify job exists in PostgreSQL with correct range
        job = PreaggregationJob.objects.get(id=result.job_ids[0])
        assert job.status == PreaggregationJob.Status.READY
        assert job.time_range_start == datetime(2024, 1, 1, tzinfo=UTC)
        assert job.time_range_end == datetime(2024, 1, 4, tzinfo=UTC)

        # Verify actual data in ClickHouse
        ch_results = self._query_computation_results(result.job_ids)
        assert len(ch_results) == 3  # 3 days with events
        # Each day has 1 unique user
        assert ch_results[0][4] == 1  # Jan 1: user1
        assert ch_results[1][4] == 1  # Jan 2: user2
        assert ch_results[2][4] == 1  # Jan 3: user3

    def test_reuses_existing_job(self):
        self._create_pageview_events()

        query = self._make_computation_query()
        query_info = QueryInfo(query=query, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone="UTC")

        # First: run for Jan 1-2
        first_result = ComputationExecutor().execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert first_result.ready is True
        assert len(first_result.job_ids) == 1
        first_job_id = first_result.job_ids[0]

        # Verify data was inserted
        ch_results_1 = self._query_computation_results([first_job_id])
        assert len(ch_results_1) == 1  # Jan 1

        # Second: run again for same range
        second_result = ComputationExecutor().execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        # Should reuse the existing job
        assert second_result.ready is True
        assert len(second_result.job_ids) == 1
        assert second_result.job_ids[0] == first_job_id

        # Verify only 1 job exists in PostgreSQL
        job = PreaggregationJob.objects.get(id=first_job_id)
        total_jobs = PreaggregationJob.objects.filter(
            team=self.team,
            query_hash=job.query_hash,
            status=PreaggregationJob.Status.READY,
        ).count()
        assert total_jobs == 1

    def test_creates_two_contiguous_ranges_when_middle_exists(self):
        """Test that contiguous missing ranges are created when some jobs already exist."""
        self._create_pageview_events()

        query = self._make_computation_query()
        query_info = QueryInfo(query=query, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone="UTC")

        # First: Create job for Jan 2 only
        jan2_result = ComputationExecutor().execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 3, tzinfo=UTC),
        )
        assert jan2_result.ready is True
        assert len(jan2_result.job_ids) == 1
        jan2_job_id = jan2_result.job_ids[0]

        # Verify Jan 2 data
        ch_results_jan2 = self._query_computation_results([jan2_job_id])
        assert len(ch_results_jan2) == 1
        assert ch_results_jan2[0][4] == 1  # user2

        # Second: Run for Jan 1-4 (Jan 2 is covered)
        # Missing: Jan 1, Jan 3 -> 2 contiguous ranges
        result = ComputationExecutor().execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 4, tzinfo=UTC),
        )

        assert result.ready is True
        # 3 jobs: existing Jan 2 + 2 new ranges (Jan 1, Jan 3)
        assert len(result.job_ids) == 3
        assert jan2_job_id in result.job_ids

        # Verify jobs in PostgreSQL
        postgres_jobs = list(
            PreaggregationJob.objects.filter(
                team=self.team,
                id__in=result.job_ids,
                status=PreaggregationJob.Status.READY,
            ).order_by("time_range_start")
        )
        assert len(postgres_jobs) == 3
        assert postgres_jobs[0].time_range_start == datetime(2024, 1, 1, tzinfo=UTC)
        assert postgres_jobs[0].time_range_end == datetime(2024, 1, 2, tzinfo=UTC)
        assert postgres_jobs[1].time_range_start == datetime(2024, 1, 2, tzinfo=UTC)
        assert postgres_jobs[1].time_range_end == datetime(2024, 1, 3, tzinfo=UTC)
        assert postgres_jobs[2].time_range_start == datetime(2024, 1, 3, tzinfo=UTC)
        assert postgres_jobs[2].time_range_end == datetime(2024, 1, 4, tzinfo=UTC)

        # Verify all data in ClickHouse
        ch_results = self._query_computation_results(result.job_ids)
        assert len(ch_results) == 3  # 3 days total
        assert ch_results[0][4] == 1  # Jan 1: user1
        assert ch_results[1][4] == 1  # Jan 2: user2
        assert ch_results[2][4] == 1  # Jan 3: user3


class TestHogQLQueryWithPrecomputation(ClickhouseTestMixin, BaseTest):
    """Test execute_hogql_query with usePreaggregatedIntermediateResults modifier (lazy computation)."""

    def _create_pageview_events(self):
        """Create pageview events for Jan 1-2, 2025."""
        _create_event(
            team=self.team, event="$pageview", distinct_id="user1", timestamp=datetime(2025, 1, 1, 10, tzinfo=UTC)
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="user2", timestamp=datetime(2025, 1, 1, 14, tzinfo=UTC)
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="user3", timestamp=datetime(2025, 1, 2, 9, tzinfo=UTC)
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="user1", timestamp=datetime(2025, 1, 2, 16, tzinfo=UTC)
        )

    def test_precomputation_modifier_returns_same_results(self):
        """Test that queries with and without precomputation modifier return the same results."""
        self._create_pageview_events()

        # Query must match the pattern: SELECT uniqExact(person_id), toStartOfDay(timestamp) FROM events
        # WHERE event='$pageview' AND timestamp >= ... AND timestamp < ...
        # GROUP BY toStartOfDay(timestamp)
        query = """
            SELECT uniqExact(person_id),
                toStartOfDay(timestamp) as day
            FROM events
            WHERE event = '$pageview'
                AND timestamp >= '2025-01-01'
                AND timestamp < '2025-01-03'
            GROUP BY toStartOfDay(timestamp)
        """

        # Run without precomputation modifier
        result_without = execute_hogql_query(
            parse_select(query),
            team=self.team,
        )

        # Run with precomputation modifier
        result_with = execute_hogql_query(
            parse_select(query),
            team=self.team,
            modifiers=HogQLQueryModifiers(usePreaggregatedIntermediateResults=True),
        )

        # Both should return the same results (order may differ, so compare sorted)
        assert sorted(result_without.results) == sorted(result_with.results)

        # Verify the expected data: Jan 1 has 2 unique users, Jan 2 has 2 unique users (user1 + user3)
        assert len(result_with.results) == 2
        sorted_results = sorted(result_with.results)
        assert sorted_results[0][0] == 2  # 2 unique users on one day
        assert sorted_results[1][0] == 2  # 2 unique users on the other day

        # Verify data exists in precomputed table
        preagg_results = sync_execute(
            f"""
            SELECT count()
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.id},
        )
        assert preagg_results[0][0] > 0

    def test_trends_query_dau_with_precomputation_modifier(self):
        """Test that TrendsQuery with DAU returns same results with and without precomputation modifier.

        TrendsQuery generates a nested query with count(DISTINCT person_id) which our
        precomputation pattern supports. The inner query should be transformed to use
        the preaggregation_results table.
        """
        self._create_pageview_events()

        # Run TrendsQuery without precomputation modifier
        query_without = TrendsQuery(
            series=[EventsNode(name="$pageview", event="$pageview", math=BaseMathType.DAU)],
            dateRange=DateRange(date_from="2025-01-01", date_to="2025-01-02"),
        )
        runner_without = TrendsQueryRunner(team=self.team, query=query_without)
        response_without = runner_without.calculate()

        # Run TrendsQuery with precomputation modifier
        query_with = TrendsQuery(
            series=[EventsNode(name="$pageview", event="$pageview", math=BaseMathType.DAU)],
            dateRange=DateRange(date_from="2025-01-01", date_to="2025-01-02"),
            modifiers=HogQLQueryModifiers(usePreaggregatedIntermediateResults=True),
        )
        runner_with = TrendsQueryRunner(team=self.team, query=query_with)
        response_with = runner_with.calculate()

        # Both should return the same results
        assert len(response_without.results) == len(response_with.results) == 1
        series_without = response_without.results[0]
        series_with = response_with.results[0]

        assert series_without["days"] == series_with["days"]
        assert series_without["data"] == series_with["data"]
        assert series_without["count"] == series_with["count"]

        # Verify expected data: 2 unique users on Jan 1, 2 unique users on Jan 2
        assert series_with["days"] == ["2025-01-01", "2025-01-02"]
        assert series_with["data"] == [2, 2]

        # Note: TrendsQueryResponse only has `hogql` (not `clickhouse`), and `hogql` is generated
        # before execute_hogql_query runs, so it shows the original AST. The transformation happens
        # inside execute_hogql_query. To verify the transformation worked, we check that
        # precomputed rows were created in the table.
        preagg_results = sync_execute(
            f"""
            SELECT count()
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.id},
        )
        assert preagg_results[0][0] > 0, "Expected precomputed data to be created"

    def test_trends_line_inner_query_format(self):
        """Test the inner query format that TrendsQuery generates for DAU queries.

        This format uses:
        - and() function call instead of AND operator
        - greaterOrEquals() and lessOrEquals() function calls
        - toStartOfInterval(assumeNotNull(toDateTime(...)), toIntervalDay(1)) for date comparison
        - Table alias (events AS e)
        - SAMPLE 1
        - GROUP BY uses alias (day_start) instead of toStartOfDay(timestamp)
        """
        self._create_pageview_events()

        # This is the query format used by TrendsQuery for DAU, with count() replaced by uniqExact(person_id)
        query = """
            SELECT
                uniqExact(person_id) AS total,
                toStartOfDay(timestamp) AS day_start
            FROM events AS e
            SAMPLE 1
            WHERE
                and(
                    greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2025-01-01 00:00:00')), toIntervalDay(1))),
                    lessOrEquals(timestamp, assumeNotNull(toDateTime('2025-01-02 23:59:59'))),
                    equals(event, '$pageview')
                )
            GROUP BY day_start
        """

        # Run without precomputation modifier
        result_without = execute_hogql_query(
            parse_select(query),
            team=self.team,
        )

        # Run with precomputation modifier
        result_with = execute_hogql_query(
            parse_select(query),
            team=self.team,
            modifiers=HogQLQueryModifiers(usePreaggregatedIntermediateResults=True),
        )

        # Both should return the same results
        assert sorted(result_without.results) == sorted(result_with.results)

        # Verify expected data: 2 unique users on Jan 1, 2 unique users on Jan 2
        assert len(result_with.results) == 2
        sorted_results = sorted(result_with.results, key=lambda r: str(r[1]))  # Sort by day
        assert sorted_results[0][0] == 2  # 2 unique users on Jan 1
        assert sorted_results[1][0] == 2  # 2 unique users on Jan 2

        # Verify the precomputed table was used in the generated SQL
        assert result_with.clickhouse and ("preaggregation_results" in result_with.clickhouse), (
            "Expected preaggregation_results table in generated SQL"
        )

        # Verify precomputed rows were created in the table
        preagg_results = sync_execute(
            f"""
            SELECT count()
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.id},
        )
        assert preagg_results[0][0] > 0, "Expected precomputed data to be created"


class TestBuildManualInsertSQL(BaseTest):
    MANUAL_INSERT_QUERY = """
        SELECT
            toStartOfDay(timestamp) as time_window_start,
            [] as breakdown_value,
            uniqExactState(person_id) as uniq_exact_state
        FROM events
        WHERE event = '$pageview'
            AND timestamp >= {time_window_min}
            AND timestamp < {time_window_max}
        GROUP BY time_window_start
    """

    def test_adds_metadata_columns(self):
        job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        sql, values = _build_manual_insert_sql(
            team=self.team,
            job=job,
            insert_query=self.MANUAL_INSERT_QUERY,
            table=LazyComputationTable.PREAGGREGATION_RESULTS,
        )

        assert "INSERT INTO preaggregation_results" in sql
        # team_id and job_id are prepended, expires_at is appended
        assert sql.index("team_id") < sql.index("job_id")
        assert sql.index("job_id") < sql.index("time_window_start")
        assert sql.index("time_window_start") < sql.index("expires_at")

    def test_substitutes_time_placeholders(self):
        job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        sql, values = _build_manual_insert_sql(
            team=self.team,
            job=job,
            insert_query=self.MANUAL_INSERT_QUERY,
            table=LazyComputationTable.PREAGGREGATION_RESULTS,
        )

        assert "2024-01-01" in sql
        assert "2024-01-02" in sql

    def test_accepts_custom_placeholders(self):
        job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        query_with_custom = """
            SELECT
                toStartOfDay(timestamp) as time_window_start,
                [] as breakdown_value,
                uniqExactState(person_id) as uniq_exact_state
            FROM events
            WHERE event = {event_name}
                AND timestamp >= {time_window_min}
                AND timestamp < {time_window_max}
            GROUP BY time_window_start
        """

        sql, values = _build_manual_insert_sql(
            team=self.team,
            job=job,
            insert_query=query_with_custom,
            table=LazyComputationTable.PREAGGREGATION_RESULTS,
            base_placeholders={"event_name": ast.Constant(value="$pageleave")},
        )

        assert "$pageleave" in values.values()


class TestEnsurePrecomputed(ClickhouseTestMixin, BaseTest):
    MANUAL_INSERT_QUERY = """
        SELECT
            toStartOfDay(timestamp) as time_window_start,
            [] as breakdown_value,
            uniqExactState(person_id) as uniq_exact_state
        FROM events
        WHERE event = '$pageview'
            AND timestamp >= {time_window_min}
            AND timestamp < {time_window_max}
        GROUP BY time_window_start
    """

    def test_creates_job_and_returns_job_ids(self):
        result = ensure_precomputed(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.ready is True
        assert len(result.job_ids) == 1

        # Verify job was created in PostgreSQL
        job = PreaggregationJob.objects.get(id=result.job_ids[0])
        assert job.status == PreaggregationJob.Status.READY
        assert job.team == self.team

    def test_reuses_existing_jobs(self):
        # First call
        first_result = ensure_precomputed(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )
        first_job_id = first_result.job_ids[0]

        # Second call with same parameters
        second_result = ensure_precomputed(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        # Should reuse the existing job
        assert len(second_result.job_ids) == 1
        assert second_result.job_ids[0] == first_job_id

    def test_creates_jobs_for_missing_ranges(self):
        # Create job for Jan 1 only
        first_result = ensure_precomputed(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )
        jan1_job_id = first_result.job_ids[0]

        # Request Jan 1-3 (Jan 1 exists, Jan 2 missing)
        second_result = ensure_precomputed(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 3, tzinfo=UTC),
        )

        # Should have 2 job IDs (Jan 1 reused + Jan 2 created)
        assert len(second_result.job_ids) == 2
        assert jan1_job_id in second_result.job_ids

    def test_accepts_custom_placeholders(self):
        query_with_placeholder = """
            SELECT
                toStartOfDay(timestamp) as time_window_start,
                [] as breakdown_value,
                uniqExactState(person_id) as uniq_exact_state
            FROM events
            WHERE event = {event_name}
                AND timestamp >= {time_window_min}
                AND timestamp < {time_window_max}
            GROUP BY time_window_start
        """

        result = ensure_precomputed(
            team=self.team,
            insert_query=query_with_placeholder,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            placeholders={"event_name": ast.Constant(value="$pageleave")},
        )

        assert result.ready is True
        assert len(result.job_ids) == 1

    @parameterized.expand(
        [
            ("time_window_min",),
            ("time_window_max",),
        ]
    )
    def test_rejects_reserved_placeholder_names(self, reserved_name):
        with pytest.raises(ValueError, match="Cannot use reserved placeholder names"):
            ensure_precomputed(
                team=self.team,
                insert_query=self.MANUAL_INSERT_QUERY,
                time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
                time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
                placeholders={reserved_name: ast.Constant(value="should_fail")},
            )

    def test_dict_ttl_creates_jobs_with_varying_expiry(self):
        now = django_timezone.now()
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)

        result = ensure_precomputed(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=today_start - timedelta(days=3),
            time_range_end=today_start + timedelta(days=1),
            ttl_seconds={
                "0d": 15 * 60,  # today (0 days ago)
                "7d": 24 * 60 * 60,  # last 7 days
                "default": 7 * 24 * 60 * 60,
            },
        )

        assert result.ready is True
        jobs = list(PreaggregationJob.objects.filter(id__in=result.job_ids).order_by("time_range_start"))
        assert len(jobs) >= 2

        # Today's job should have a much shorter TTL than older jobs
        today_jobs = [j for j in jobs if j.time_range_start >= today_start]
        older_jobs = [j for j in jobs if j.time_range_start < today_start]

        for j in today_jobs:
            assert j.expires_at is not None
            ttl = (j.expires_at - j.created_at).total_seconds()
            assert ttl < 1000

        for j in older_jobs:
            assert j.expires_at is not None
            ttl = (j.expires_at - j.created_at).total_seconds()
            assert ttl > 80000

    def test_dict_ttl_with_non_utc_timezone(self):
        self.team.timezone = "Pacific/Tongatapu"
        self.team.save()

        now = django_timezone.now()
        today_utc = datetime(now.year, now.month, now.day, tzinfo=UTC)

        ttl_dict = {
            "0d": 15 * 60,
            "7d": 24 * 60 * 60,
            "default": 7 * 24 * 60 * 60,
        }

        result = ensure_precomputed(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=today_utc - timedelta(days=10),
            time_range_end=today_utc + timedelta(days=1),
            ttl_seconds=ttl_dict,
        )

        assert result.ready is True
        jobs = list(PreaggregationJob.objects.filter(id__in=result.job_ids))
        assert len(jobs) >= 2

        # Verify each job's TTL matches the timezone-aware schedule
        expected_schedule = parse_ttl_schedule(ttl_dict, team_timezone="Pacific/Tongatapu")
        for job in jobs:
            assert job.expires_at is not None
            expected_ttl = expected_schedule.get_ttl(job.time_range_start)
            actual_ttl = (job.expires_at - job.created_at).total_seconds()
            assert abs(actual_ttl - expected_ttl) < 10, (
                f"Job {job.time_range_start}: expected TTL ~{expected_ttl}, got {actual_ttl}"
            )


class TestParseTtlSchedule(BaseTest):
    def test_int_returns_schedule_with_no_rules(self):
        schedule = parse_ttl_schedule(3600)
        assert schedule.rules == []
        assert schedule.default_ttl_seconds == 3600

    def test_dict_with_default_key(self):
        schedule = parse_ttl_schedule({"default": 999})
        assert schedule.rules == []
        assert schedule.default_ttl_seconds == 999

    def test_dict_with_relative_day_keys(self):
        schedule = parse_ttl_schedule({"1d": 60, "7d": 3600, "default": 86400})
        assert schedule.default_ttl_seconds == 86400
        assert len(schedule.rules) == 2
        # Rules sorted by cutoff descending (most recent first)
        assert schedule.rules[0][1] == 60  # 1d rule
        assert schedule.rules[1][1] == 3600  # 7d rule
        assert schedule.rules[0][0] > schedule.rules[1][0]

    def test_dict_with_iso_date_key(self):
        schedule = parse_ttl_schedule({"2024-06-15": 120, "default": 86400})
        assert len(schedule.rules) == 1
        cutoff = schedule.rules[0][0]
        assert cutoff.year == 2024
        assert cutoff.month == 6
        assert cutoff.day == 15
        assert schedule.rules[0][1] == 120

    def test_get_ttl_returns_matching_rule(self):
        now = django_timezone.now()
        schedule = TtlSchedule(
            rules=[
                (now - timedelta(days=1), 60),
                (now - timedelta(days=7), 3600),
            ],
            default_ttl_seconds=86400,
        )
        # Recent window matches first rule
        assert schedule.get_ttl(now) == 60
        # Window from 3 days ago matches second rule
        assert schedule.get_ttl(now - timedelta(days=3)) == 3600
        # Window from 30 days ago matches default
        assert schedule.get_ttl(now - timedelta(days=30)) == 86400

    def test_non_utc_timezone_shifts_cutoffs(self):
        schedule_utc = parse_ttl_schedule({"1d": 60, "default": 86400}, team_timezone="UTC")
        schedule_tongatapu = parse_ttl_schedule({"1d": 60, "default": 86400}, team_timezone="Pacific/Tongatapu")
        # UTC+13: "today" starts at a different UTC time, shifting the cutoff.
        # The diff is ~11-13h depending on time of day (because "yesterday"
        # in UTC vs Tongatapu may be a different calendar day).
        utc_cutoff = schedule_utc.rules[0][0]
        tongatapu_cutoff = schedule_tongatapu.rules[0][0]
        diff_hours = abs((utc_cutoff - tongatapu_cutoff).total_seconds()) / 3600
        assert 10 < diff_hours < 15

    def test_dict_without_default_key_uses_builtin_default(self):
        schedule = parse_ttl_schedule({"7d": 3600})
        assert len(schedule.rules) == 1
        assert schedule.rules[0][1] == 3600
        # Falls back to DEFAULT_TTL_SECONDS (7 days = 604800)
        assert schedule.default_ttl_seconds == 7 * 24 * 60 * 60

    def test_get_ttl_with_cross_timezone_cutoffs(self):
        # Cutoff in Tongatapu (UTC+13): "0d" = start of today in local time
        schedule = parse_ttl_schedule({"0d": 60, "default": 86400}, team_timezone="Pacific/Tongatapu")
        tongatapu_today_start = schedule.rules[0][0]

        # A UTC-midnight window that falls BEFORE the Tongatapu cutoff should get default TTL.
        # In Tongatapu, UTC midnight is 1pm local time — so a UTC window starting at
        # yesterday-midnight is "yesterday" in Tongatapu → default TTL, not the "today" TTL.
        utc_yesterday = tongatapu_today_start - timedelta(hours=1)
        assert schedule.get_ttl(utc_yesterday) == 86400

        # A window at or after the cutoff gets the short TTL
        assert schedule.get_ttl(tongatapu_today_start) == 60
        assert schedule.get_ttl(tongatapu_today_start + timedelta(hours=5)) == 60

    @parameterized.expand(
        [
            ("empty_string", "", "Unrecognized TTL schedule key"),
            ("random_word", "invalid", "Unrecognized TTL schedule key"),
            ("number_only", "123", "Unrecognized TTL schedule key"),
            ("special_chars", "!@#", "Unrecognized TTL schedule key"),
        ]
    )
    def test_rejects_invalid_keys(self, name, key, expected_error):
        with pytest.raises(ValueError, match=expected_error):
            parse_ttl_schedule({key: 3600})

    @parameterized.expand(
        [
            ("zero_ttl", {"7d": 0}),
            ("negative_ttl", {"7d": -100}),
            ("zero_default", {"default": 0}),
            ("negative_default", {"default": -1}),
            ("negative_int", -60),
            ("zero_int", 0),
        ]
    )
    def test_rejects_non_positive_ttl_values(self, name, ttl):
        with pytest.raises(ValueError, match="must be positive"):
            parse_ttl_schedule(ttl)


class TestSplitRangesByTtl(BaseTest):
    def test_single_range_uniform_ttl(self):
        schedule = TtlSchedule.from_seconds(3600)
        ranges = [(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 4, tzinfo=UTC))]
        result = split_ranges_by_ttl(ranges, schedule)
        assert result == [(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 4, tzinfo=UTC), 3600)]

    def test_range_splits_at_ttl_boundary(self):
        now = django_timezone.now()
        # 2 days ago is the boundary: recent gets 60s TTL, older gets 3600s
        cutoff = datetime(now.year, now.month, now.day, tzinfo=UTC) - timedelta(days=1)
        schedule = TtlSchedule(rules=[(cutoff, 60)], default_ttl_seconds=3600)

        # Range spanning the boundary
        range_start = cutoff - timedelta(days=2)
        range_end = cutoff + timedelta(days=2)
        result = split_ranges_by_ttl([(range_start, range_end)], schedule)

        assert len(result) == 2
        # First chunk: older days with default TTL
        assert result[0][2] == 3600
        assert result[0][0] == range_start
        assert result[0][1] == cutoff
        # Second chunk: recent days with short TTL
        assert result[1][2] == 60
        assert result[1][0] == cutoff

    def test_empty_ranges(self):
        schedule = TtlSchedule.from_seconds(3600)
        assert split_ranges_by_ttl([], schedule) == []

    def test_multiple_ranges_split_independently(self):
        schedule = TtlSchedule.from_seconds(3600)
        ranges = [
            (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 3, tzinfo=UTC)),
            (datetime(2024, 1, 5, tzinfo=UTC), datetime(2024, 1, 7, tzinfo=UTC)),
        ]
        result = split_ranges_by_ttl(ranges, schedule)
        assert len(result) == 2
        assert result[0] == (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 3, tzinfo=UTC), 3600)
        assert result[1] == (datetime(2024, 1, 5, tzinfo=UTC), datetime(2024, 1, 7, tzinfo=UTC), 3600)


class TestComputationExecutor(BaseTest):
    def test_executor_with_custom_settings(self):
        default_executor = ComputationExecutor()
        assert default_executor.wait_timeout_seconds == DEFAULT_WAIT_TIMEOUT_SECONDS
        assert default_executor.poll_interval_seconds == DEFAULT_POLL_INTERVAL_SECONDS
        assert default_executor.max_retries == DEFAULT_RETRIES
        assert default_executor.ttl_schedule == DEFAULT_TTL_SCHEDULE

        custom_schedule = TtlSchedule.from_seconds(3600)
        custom_executor = ComputationExecutor(
            wait_timeout_seconds=60.0,
            poll_interval_seconds=0.5,
            max_retries=5,
            ttl_schedule=custom_schedule,
        )
        assert custom_executor.wait_timeout_seconds == 60.0
        assert custom_executor.poll_interval_seconds == 0.5
        assert custom_executor.max_retries == 5
        assert custom_executor.ttl_schedule.default_ttl_seconds == 3600


class TestRaceConditionHandling(BaseTest):
    def _make_computation_query(self) -> ast.SelectQuery:
        s = parse_select(
            """
            SELECT
                toStartOfDay(timestamp) as time_window_start,
                [] as breakdown_value,
                uniqExactState(person_id) as uniq_exact_state
            FROM events
            WHERE event = '$pageview'
            GROUP BY time_window_start
            """
        )
        assert isinstance(s, ast.SelectQuery)
        return s

    def test_integrity_error_on_create_loops_back_and_picks_up_pending_job(self):
        query = self._make_computation_query()
        query_info = QueryInfo(query=query, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone="UTC")
        query_hash = compute_query_hash(query_info)

        executor = ComputationExecutor(wait_timeout_seconds=2.0, poll_interval_seconds=0.05)

        # Another executor already created a PENDING job for this range
        existing_pending = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        def mock_wait(pubsub, duration):
            existing_pending.status = PreaggregationJob.Status.READY
            existing_pending.computed_at = django_timezone.now()
            existing_pending.save()
            return {"type": b"message", "channel": job_channel(existing_pending.id).encode(), "data": b"ready"}

        with (
            patch(
                "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.create_computation_job",
                side_effect=IntegrityError("duplicate key"),
            ),
            patch(
                "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.find_existing_jobs",
                side_effect=[
                    [],  # First call: miss the job (race window)
                    [existing_pending],  # Second call: find it as PENDING after IntegrityError loops back
                    [existing_pending],  # Third call (in loop): find it as READY, no pending → break
                    [existing_pending],  # Fourth call: final collection after loop
                ],
            ),
            patch.object(executor, "_wait_for_notification", side_effect=mock_wait),
        ):
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
                run_insert=lambda t, j: None,
            )

        assert result.ready is True
        assert existing_pending.id in result.job_ids

    def test_unique_constraint_prevents_duplicate_pending_jobs(self):
        query = self._make_computation_query()
        query_info = QueryInfo(query=query, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone="UTC")
        query_hash = compute_query_hash(query_info)

        # Create a PENDING job directly
        PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        # Attempting to create another should raise IntegrityError
        with pytest.raises(IntegrityError):
            PreaggregationJob.objects.create(
                team=self.team,
                query_hash=query_hash,
                time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
                time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
                status=PreaggregationJob.Status.PENDING,
                expires_at=django_timezone.now() + timedelta(days=7),
            )


class TestComputationExecutorExecute(BaseTest):
    def _make_query_info(self) -> tuple[QueryInfo, str]:
        s = parse_select(
            """
            SELECT
                toStartOfDay(timestamp) as time_window_start,
                [] as breakdown_value,
                uniqExactState(person_id) as uniq_exact_state
            FROM events
            WHERE event = '$pageview'
            GROUP BY time_window_start
            """
        )
        assert isinstance(s, ast.SelectQuery)
        qi = QueryInfo(query=s, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone="UTC")
        return qi, compute_query_hash(qi)

    # --- Happy path ---

    def test_returns_immediately_when_all_ranges_ready(self):
        query_info, query_hash = self._make_query_info()

        ready_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        executor = ComputationExecutor()
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )

        assert result.ready is True
        assert ready_job.id in result.job_ids

    def test_inserts_missing_ranges_and_returns_all_job_ids(self):
        query_info, query_hash = self._make_query_info()

        executor = ComputationExecutor()
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 3, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )

        assert result.ready is True
        # Contiguous daily windows [Jan 1, Jan 2) + [Jan 2, Jan 3) are merged into one job
        assert len(result.job_ids) == 1

    def test_respects_custom_ttl(self):
        query_info, _ = self._make_query_info()

        one_hour = 60 * 60
        executor = ComputationExecutor(ttl_schedule=TtlSchedule.from_seconds(one_hour))
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )

        assert result.ready is True
        job = PreaggregationJob.objects.get(id=result.job_ids[0])
        assert job.expires_at is not None
        time_diff = (job.expires_at - django_timezone.now()).total_seconds()
        assert one_hour - 100 < time_diff < one_hour + 100

    def test_short_ttl_does_not_infinite_loop(self):
        query_info, _ = self._make_query_info()

        executor = ComputationExecutor(ttl_schedule=TtlSchedule.from_seconds(60), wait_timeout_seconds=5.0)
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )

        assert result.ready is True
        job = PreaggregationJob.objects.get(id=result.job_ids[0])
        assert job.expires_at is not None
        time_diff = (job.expires_at - django_timezone.now()).total_seconds()
        assert 0 < time_diff < 120

    # --- Freshness filtering ---

    def test_stale_ready_job_is_recomputed(self):
        query_info, query_hash = self._make_query_info()

        # Create a READY job that was created 2 hours ago with a 1-hour schedule TTL
        stale_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
            expires_at=django_timezone.now() + timedelta(days=5),
        )
        PreaggregationJob.objects.filter(id=stale_job.id).update(
            created_at=django_timezone.now() - timedelta(hours=2),
        )

        one_hour = 60 * 60
        executor = ComputationExecutor(ttl_schedule=TtlSchedule.from_seconds(one_hour))
        insert_count = [0]

        def counting_insert(t, j):
            insert_count[0] += 1

        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=counting_insert,
        )

        assert result.ready is True
        # A new job was created (stale one was filtered out)
        assert insert_count[0] == 1
        assert stale_job.id not in result.job_ids

    def test_fresh_ready_job_is_reused(self):
        query_info, query_hash = self._make_query_info()

        fresh_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        one_hour = 60 * 60
        executor = ComputationExecutor(ttl_schedule=TtlSchedule.from_seconds(one_hour))
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )

        assert result.ready is True
        assert fresh_job.id in result.job_ids

    def test_variable_ttl_creates_jobs_with_different_expiry(self):
        query_info, _ = self._make_query_info()

        now = django_timezone.now()
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)

        schedule = TtlSchedule(
            rules=[(today_start, 900)],  # today: 15 min
            default_ttl_seconds=86400,  # else: 1 day
        )

        # Query spanning today and 2 days before
        range_start = today_start - timedelta(days=2)
        range_end = today_start + timedelta(days=1)

        executor = ComputationExecutor(ttl_schedule=schedule)
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=range_start,
            end=range_end,
            run_insert=lambda t, j: None,
        )

        assert result.ready is True
        jobs = list(PreaggregationJob.objects.filter(id__in=result.job_ids).order_by("time_range_start"))
        assert len(jobs) >= 2

        # Older jobs should have longer TTL, today's job should have shorter TTL
        today_jobs = [j for j in jobs if j.time_range_start >= today_start]
        older_jobs = [j for j in jobs if j.time_range_start < today_start]
        assert len(today_jobs) >= 1
        assert len(older_jobs) >= 1

        for j in today_jobs:
            assert j.expires_at is not None
            ttl = (j.expires_at - j.created_at).total_seconds()
            assert ttl < 1000  # ~15 min

        for j in older_jobs:
            assert j.expires_at is not None
            ttl = (j.expires_at - j.created_at).total_seconds()
            assert ttl > 80000  # ~1 day

    def test_timezone_aware_ttl_creates_jobs_with_correct_expiry(self):
        query_info, _ = self._make_query_info()

        self.team.timezone = "Pacific/Tongatapu"
        self.team.save()

        schedule = parse_ttl_schedule(
            {"0d": 60, "7d": 3600, "default": 86400},
            team_timezone="Pacific/Tongatapu",
        )

        now = django_timezone.now()
        today_utc = datetime(now.year, now.month, now.day, tzinfo=UTC)

        executor = ComputationExecutor(ttl_schedule=schedule)
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=today_utc - timedelta(days=10),
            end=today_utc + timedelta(days=1),
            run_insert=lambda t, j: None,
        )

        assert result.ready is True
        jobs = list(PreaggregationJob.objects.filter(id__in=result.job_ids))
        assert len(jobs) >= 2

        for job in jobs:
            assert job.expires_at is not None
            expected_ttl = schedule.get_ttl(job.time_range_start)
            actual_ttl = (job.expires_at - job.created_at).total_seconds()
            assert abs(actual_ttl - expected_ttl) < 10, (
                f"Job {job.time_range_start}: expected TTL ~{expected_ttl}, got {actual_ttl}"
            )

    # --- Stale + race condition ---

    def test_stale_per_schedule_with_concurrent_replacement(self):
        query_info, query_hash = self._make_query_info()

        # A READY job exists but is stale per a 1-hour schedule (created 2 hours ago).
        # Its PG expires_at is still valid — the staleness is schedule-level only.
        stale_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
            expires_at=django_timezone.now() + timedelta(days=5),
        )
        PreaggregationJob.objects.filter(id=stale_job.id).update(
            created_at=django_timezone.now() - timedelta(hours=2),
        )

        one_hour = 60 * 60
        executor = ComputationExecutor(
            ttl_schedule=TtlSchedule.from_seconds(one_hour),
            wait_timeout_seconds=5.0,
            poll_interval_seconds=0.05,
        )

        # Simulate: our create hits IntegrityError (another executor got there first),
        # then on the next loop we find their PENDING job, then it completes.
        other_pending = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(hours=1),
        )

        def mock_wait(pubsub, duration):
            other_pending.status = PreaggregationJob.Status.READY
            other_pending.computed_at = django_timezone.now()
            other_pending.save()
            return {"type": b"message", "data": b"ready"}

        with patch.object(executor, "_wait_for_notification", side_effect=mock_wait):
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
                run_insert=lambda t, j: None,
            )

        assert result.ready is True
        # The stale job was filtered out, the other executor's job was used
        assert stale_job.id not in result.job_ids
        assert other_pending.id in result.job_ids

    # --- Waiting for pending jobs ---

    def test_waits_for_pending_job_then_succeeds(self):
        query_info, query_hash = self._make_query_info()

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        def mock_wait(pubsub, duration):
            pending_job.status = PreaggregationJob.Status.READY
            pending_job.computed_at = django_timezone.now()
            pending_job.save()
            return {"type": b"message", "channel": job_channel(pending_job.id).encode(), "data": b"ready"}

        executor = ComputationExecutor(wait_timeout_seconds=5.0, poll_interval_seconds=0.1)
        with patch.object(executor, "_wait_for_notification", side_effect=mock_wait):
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
                run_insert=lambda t, j: None,
            )

        assert result.ready is True
        assert pending_job.id in result.job_ids

    def test_timeout_when_job_stays_pending(self):
        query_info, query_hash = self._make_query_info()

        PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        executor = ComputationExecutor(wait_timeout_seconds=0.3, poll_interval_seconds=0.1)
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )

        assert result.ready is False
        assert any("Timeout" in e for e in result.errors)

    def test_does_not_create_duplicate_for_pending_range(self):
        query_info, query_hash = self._make_query_info()

        PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        executor = ComputationExecutor(wait_timeout_seconds=0.3, poll_interval_seconds=0.1)
        with patch(
            "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.create_computation_job",
            wraps=create_lazy_computation_job,
        ) as mock_create:
            executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
                run_insert=lambda t, j: None,
            )

        mock_create.assert_not_called()

    # --- Insert-first ordering ---

    def test_inserts_missing_ranges_before_waiting_for_pending(self):
        query_info, query_hash = self._make_query_info()

        # Jan 1 is PENDING (another executor), Jan 2 is missing
        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        insert_times: list[float] = []
        wait_times: list[float] = []

        def mock_insert(team, job):
            insert_times.append(time_mod.monotonic())

        def mock_wait(pubsub, duration):
            wait_times.append(time_mod.monotonic())
            # Simulate the pending job completing
            pending_job.status = PreaggregationJob.Status.READY
            pending_job.computed_at = django_timezone.now()
            pending_job.save()
            return {"type": b"message", "data": b"ready"}

        executor = ComputationExecutor(wait_timeout_seconds=5.0, poll_interval_seconds=0.1)
        with patch.object(executor, "_wait_for_notification", side_effect=mock_wait):
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 3, tzinfo=UTC),
                run_insert=mock_insert,
            )

        assert result.ready is True
        assert len(result.job_ids) == 2
        # Insert happened before waiting
        assert len(insert_times) == 1
        assert len(wait_times) >= 1
        assert insert_times[0] < wait_times[0]

    # --- Retry behavior ---

    def test_retries_on_retryable_error_then_succeeds(self):
        query_info, query_hash = self._make_query_info()
        insert_count = [0]

        def mock_insert(team, job):
            insert_count[0] += 1
            if insert_count[0] == 1:
                raise ConnectionError("Connection refused")

        executor = ComputationExecutor(max_retries=2)
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=mock_insert,
        )

        assert result.ready is True
        assert insert_count[0] == 2

    def test_gives_up_after_max_retries(self):
        query_info, query_hash = self._make_query_info()
        insert_count = [0]

        def always_fail(team, job):
            insert_count[0] += 1
            raise ConnectionError("Connection refused")

        executor = ComputationExecutor(max_retries=2, wait_timeout_seconds=5.0)
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=always_fail,
        )

        assert result.ready is False
        # 1 initial attempt + 2 retries = 3
        assert insert_count[0] == 3
        assert any("Max retries" in e for e in result.errors)

    # --- Non-retryable errors ---

    def test_non_retryable_error_exits_immediately(self):
        query_info, query_hash = self._make_query_info()
        insert_count = [0]

        def syntax_error(team, job):
            insert_count[0] += 1
            raise ServerException(message="Syntax error", code=62)

        executor = ComputationExecutor(max_retries=3)
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 3, tzinfo=UTC),
            run_insert=syntax_error,
        )

        assert result.ready is False
        assert insert_count[0] == 1
        assert len(result.errors) == 1
        assert result.job_ids == []

    def test_non_retryable_error_does_not_block_future_queries(self):
        query_info, query_hash = self._make_query_info()

        executor = ComputationExecutor(max_retries=3)

        # First call fails with non-retryable error
        result1 = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: (_ for _ in ()).throw(ServerException(message="Syntax error", code=62)),
        )
        assert result1.ready is False

        # Second call succeeds — failed job is ignored, new job is created
        result2 = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )
        assert result2.ready is True
        assert len(result2.job_ids) == 1

    # --- Stale job recovery ---

    def test_stale_pending_job_gets_replaced(self):
        query_info, query_hash = self._make_query_info()

        stale_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )
        PreaggregationJob.objects.filter(id=stale_job.id).update(
            created_at=django_timezone.now() - timedelta(seconds=120),
        )

        executor = ComputationExecutor(
            stale_pending_threshold_seconds=0.1,
            ch_start_grace_period_seconds=0.1,
            wait_timeout_seconds=5.0,
            poll_interval_seconds=0.05,
        )
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )

        assert result.ready is True
        assert len(result.job_ids) == 1
        # Original stale job should be FAILED, a new job was created
        stale_job.refresh_from_db()
        assert stale_job.status == PreaggregationJob.Status.FAILED
        assert result.job_ids[0] != stale_job.id

    def test_non_stale_pending_job_is_not_marked_failed(self):
        query_info, query_hash = self._make_query_info()

        PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        executor = ComputationExecutor(
            stale_pending_threshold_seconds=300,
            ch_start_grace_period_seconds=300,
            wait_timeout_seconds=0.3,
            poll_interval_seconds=0.1,
        )
        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )

        # Times out, but job is NOT marked as stale/failed
        assert result.ready is False
        pending_jobs = PreaggregationJob.objects.filter(
            team=self.team, query_hash=query_hash, status=PreaggregationJob.Status.PENDING
        )
        assert pending_jobs.count() == 1

    # --- Exponential backoff ---

    def test_exponential_backoff_increases_poll_interval(self):
        query_info, query_hash = self._make_query_info()

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        wait_durations: list[float] = []

        def mock_wait(pubsub, duration):
            wait_durations.append(duration)
            if len(wait_durations) == 5:
                pending_job.status = PreaggregationJob.Status.READY
                pending_job.computed_at = django_timezone.now()
                pending_job.save()
                return {"type": b"message", "data": b"ready"}
            return None

        executor = ComputationExecutor(
            wait_timeout_seconds=100.0,
            poll_interval_seconds=0.5,
            max_poll_interval_seconds=4.0,
        )
        with patch.object(executor, "_wait_for_notification", side_effect=mock_wait):
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
                run_insert=lambda t, j: None,
            )

        assert result.ready is True
        assert len(wait_durations) == 5
        assert wait_durations[0] == pytest.approx(0.5, abs=0.01)
        assert wait_durations[1] == pytest.approx(1.0, abs=0.01)
        assert wait_durations[2] == pytest.approx(2.0, abs=0.01)
        assert wait_durations[3] == pytest.approx(4.0, abs=0.01)
        assert wait_durations[4] == pytest.approx(4.0, abs=0.01)

    def test_backoff_resets_after_successful_insert(self):
        query_info, query_hash = self._make_query_info()

        # Jan 1 is PENDING, Jan 2 is missing
        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        wait_durations: list[float] = []

        def mock_wait(pubsub, duration):
            wait_durations.append(duration)
            if len(wait_durations) == 2:
                pending_job.status = PreaggregationJob.Status.READY
                pending_job.computed_at = django_timezone.now()
                pending_job.save()
                return {"type": b"message", "data": b"ready"}
            return None

        executor = ComputationExecutor(
            wait_timeout_seconds=100.0,
            poll_interval_seconds=1.0,
            max_poll_interval_seconds=8.0,
        )
        with patch.object(executor, "_wait_for_notification", side_effect=mock_wait):
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 3, tzinfo=UTC),
                run_insert=lambda t, j: None,
            )

        assert result.ready is True
        # Sequence: insert Jan 2 (reset backoff) → loop back → find Jan 1 PENDING
        # → wait(1.0) → wait(2.0) → Jan 1 ready → done
        # The first wait is 1.0 (reset from insert), not a higher value
        assert len(wait_durations) == 2
        assert wait_durations[0] == pytest.approx(1.0, abs=0.01)
        assert wait_durations[1] == pytest.approx(2.0, abs=0.01)


class TestPubsubAndStaleDetection(BaseTest):
    # --- Stale detection with CH liveness ---

    def test_stale_detection_ch_not_started_within_grace(self):
        executor = ComputationExecutor(
            stale_pending_threshold_seconds=0.1,
            ch_start_grace_period_seconds=300,
        )

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )
        pending_job.refresh_from_db()

        assert executor._is_job_stale(pending_job) is False

    def test_stale_detection_ch_not_started_past_grace(self):
        executor = ComputationExecutor(
            stale_pending_threshold_seconds=0.1,
            ch_start_grace_period_seconds=1,
        )

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )
        PreaggregationJob.objects.filter(id=pending_job.id).update(
            created_at=django_timezone.now() - timedelta(seconds=10),
        )
        pending_job.refresh_from_db()

        assert executor._is_job_stale(pending_job) is True

    def test_stale_detection_ch_started_still_running(self):
        executor = ComputationExecutor(stale_pending_threshold_seconds=0.1)

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )
        pending_job.refresh_from_db()

        set_ch_query_started(pending_job.id)

        with patch(
            "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.is_ch_query_alive",
            return_value=True,
        ):
            assert executor._is_job_stale(pending_job) is False

    def test_stale_detection_ch_started_not_running(self):
        executor = ComputationExecutor(stale_pending_threshold_seconds=0.1)

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )
        PreaggregationJob.objects.filter(id=pending_job.id).update(
            created_at=django_timezone.now() - timedelta(seconds=10),
        )
        pending_job.refresh_from_db()

        set_ch_query_started(pending_job.id)

        with patch(
            "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.is_ch_query_alive",
            return_value=False,
        ):
            assert executor._is_job_stale(pending_job) is True

    def test_marks_stale_pending_job_as_failed(self):
        executor = ComputationExecutor(stale_pending_threshold_seconds=0.1)

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        result = executor._try_mark_stale_job_as_failed(pending_job)

        assert result is True
        pending_job.refresh_from_db()
        assert pending_job.status == PreaggregationJob.Status.FAILED
        assert pending_job.error is not None and "stale" in pending_job.error.lower()

    def test_only_one_waiter_marks_stale_job(self):
        executor = ComputationExecutor(stale_pending_threshold_seconds=0.1)

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        result1 = executor._try_mark_stale_job_as_failed(pending_job)
        assert result1 is True

        result2 = executor._try_mark_stale_job_as_failed(pending_job)
        assert result2 is False

    # --- Publish on terminal transitions ---

    def test_publish_on_successful_insert(self):
        with patch(
            "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.publish_job_completion"
        ) as mock_publish:
            query = parse_select(
                "SELECT toStartOfDay(timestamp) as a, [] as b, uniqExactState(person_id) as c FROM events GROUP BY a"
            )
            assert isinstance(query, ast.SelectQuery)
            query_info = QueryInfo(query=query, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone="UTC")

            executor = ComputationExecutor()
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
                run_insert=lambda t, j: None,
            )
            assert result.ready is True
            assert mock_publish.call_count == 1
            assert mock_publish.call_args[0][1] == "ready"

    def test_publish_on_failed_insert(self):
        with patch(
            "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.publish_job_completion"
        ) as mock_publish:
            query = parse_select(
                "SELECT toStartOfDay(timestamp) as a, [] as b, uniqExactState(person_id) as c FROM events GROUP BY a"
            )
            assert isinstance(query, ast.SelectQuery)
            query_info = QueryInfo(query=query, table=LazyComputationTable.PREAGGREGATION_RESULTS, timezone="UTC")

            executor = ComputationExecutor(max_retries=0)
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 2, 1, tzinfo=UTC),
                end=datetime(2024, 2, 2, tzinfo=UTC),
                run_insert=lambda t, j: (_ for _ in ()).throw(Exception("boom")),
            )
            assert result.ready is False
            assert mock_publish.call_count == 1
            assert mock_publish.call_args[0][1] == "failed"

    def test_publish_on_stale_mark(self):
        with patch(
            "products.analytics_platform.backend.lazy_computation.lazy_computation_executor.publish_job_completion"
        ) as mock_publish:
            executor = ComputationExecutor()
            stale_job = PreaggregationJob.objects.create(
                team=self.team,
                query_hash="stale_hash",
                time_range_start=datetime(2024, 3, 1, tzinfo=UTC),
                time_range_end=datetime(2024, 3, 2, tzinfo=UTC),
                status=PreaggregationJob.Status.PENDING,
                expires_at=django_timezone.now() + timedelta(days=7),
            )
            executor._try_mark_stale_job_as_failed(stale_job)
            assert mock_publish.call_count == 1
            assert mock_publish.call_args[0][1] == "failed"


class TestIsNonRetryableError(BaseTest):
    @parameterized.expand(
        [
            ("connection_error", ConnectionError("Connection refused")),
            ("os_error", OSError("Network is unreachable")),
            ("timeout_error", TimeoutError("Connection timed out")),
        ]
    )
    def test_network_errors_are_retryable(self, name, error):
        assert is_non_retryable_error(error) is False

    @parameterized.expand(
        [
            ("syntax_error", 62, "Syntax error in SQL"),
            ("illegal_type_of_argument", 43, "Illegal type of argument"),
            ("type_mismatch", 53, "Type mismatch"),
            ("unknown_function", 46, "Unknown function"),
            ("unknown_identifier", 47, "Unknown identifier"),
            ("unknown_table", 60, "Unknown table"),
            ("no_such_column", 16, "No such column"),
            ("timeout", 159, "Timeout exceeded"),
            ("too_many_queries", 202, "Too many simultaneous queries"),
        ]
    )
    def test_clickhouse_non_retryable_error_codes(self, name, code, message):
        error = ServerException(message=message, code=code)
        assert is_non_retryable_error(error) is True
        assert code in NON_RETRYABLE_CLICKHOUSE_ERROR_CODES

    @parameterized.expand(
        [
            ("memory_limit", 241, "Memory limit exceeded"),
        ]
    )
    def test_clickhouse_retryable_error_codes(self, name, code, message):
        error = ServerException(message=message, code=code)
        assert is_non_retryable_error(error) is False

    def test_wrapped_non_retryable_error_detected(self):
        inner_error = ServerException(message="Syntax error", code=62)
        outer_error = RuntimeError("Query failed")
        outer_error.__cause__ = inner_error

        assert is_non_retryable_error(outer_error) is True

    def test_generic_exception_is_retryable(self):
        error = Exception("Something went wrong")
        assert is_non_retryable_error(error) is False
