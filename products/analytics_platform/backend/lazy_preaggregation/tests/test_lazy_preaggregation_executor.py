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

from products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_TTL_SECONDS,
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    NON_RETRYABLE_CLICKHOUSE_ERROR_CODES,
    PreaggregationExecutor,
    PreaggregationResult,
    PreaggregationTable,
    QueryInfo,
    _build_manual_insert_sql,
    build_preaggregation_insert_sql,
    compute_query_hash,
    create_preaggregation_job,
    ensure_preaggregated,
    filter_overlapping_jobs,
    find_missing_contiguous_windows,
    is_non_retryable_error,
)
from products.analytics_platform.backend.models import PreaggregationJob


class TestPreaggregationJob(BaseTest):
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
        query_info1 = QueryInfo(query=s1, table=PreaggregationTable.PREAGGREGATION_RESULTS, timezone=t1)
        query_info2 = QueryInfo(query=s2, table=PreaggregationTable.PREAGGREGATION_RESULTS, timezone=t2)

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


class TestBuildPreaggregationInsertSQL(BaseTest):
    def _make_select_query(self, where_clause: str = "") -> ast.SelectQuery:
        """Create a valid preaggregation select query with 3 expressions."""
        where = f"WHERE {where_clause}" if where_clause else ""
        s = parse_select(f"SELECT 1 as col1, 2 as col2, 3 as col3 FROM events {where}")
        assert isinstance(s, ast.SelectQuery)
        return s

    def test_query_without_where(self):
        job_id = "11111111-1111-1111-1111-111111111111"
        select_query = self._make_select_query()
        expires_at = datetime(2024, 1, 8, tzinfo=UTC)

        sql, values = build_preaggregation_insert_sql(
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

        sql, values = build_preaggregation_insert_sql(
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

        sql, values = build_preaggregation_insert_sql(
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

        build_preaggregation_insert_sql(
            team=self.team,
            job_id=job_id,
            select_query=select_query,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            expires_at=expires_at,
        )

        assert select_query.where == original_where
        assert len(select_query.select) == original_select_len


class TestExecutePreaggregationJobs(ClickhouseTestMixin, BaseTest):
    def _make_preaggregation_query(self) -> ast.SelectQuery:
        """Create a query that produces columns matching the preaggregation table schema."""
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

    def _query_preaggregation_results(self, job_ids: list) -> list:
        """Query the preaggregation results table for specific job IDs."""
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

        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, table=PreaggregationTable.PREAGGREGATION_RESULTS, timezone="UTC")

        result = PreaggregationExecutor().execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 4, tzinfo=UTC),
        )

        assert isinstance(result, PreaggregationResult)
        assert result.ready is True
        assert len(result.errors) == 0
        assert len(result.job_ids) == 1

        # Verify job exists in PostgreSQL with correct range
        job = PreaggregationJob.objects.get(id=result.job_ids[0])
        assert job.status == PreaggregationJob.Status.READY
        assert job.time_range_start == datetime(2024, 1, 1, tzinfo=UTC)
        assert job.time_range_end == datetime(2024, 1, 4, tzinfo=UTC)

        # Verify actual data in ClickHouse
        ch_results = self._query_preaggregation_results(result.job_ids)
        assert len(ch_results) == 3  # 3 days with events
        # Each day has 1 unique user
        assert ch_results[0][4] == 1  # Jan 1: user1
        assert ch_results[1][4] == 1  # Jan 2: user2
        assert ch_results[2][4] == 1  # Jan 3: user3

    def test_reuses_existing_job(self):
        self._create_pageview_events()

        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, table=PreaggregationTable.PREAGGREGATION_RESULTS, timezone="UTC")

        # First: run for Jan 1-2
        first_result = PreaggregationExecutor().execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert first_result.ready is True
        assert len(first_result.job_ids) == 1
        first_job_id = first_result.job_ids[0]

        # Verify data was inserted
        ch_results_1 = self._query_preaggregation_results([first_job_id])
        assert len(ch_results_1) == 1  # Jan 1

        # Second: run again for same range
        second_result = PreaggregationExecutor().execute(
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

        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, table=PreaggregationTable.PREAGGREGATION_RESULTS, timezone="UTC")

        # First: Create job for Jan 2 only
        jan2_result = PreaggregationExecutor().execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 3, tzinfo=UTC),
        )
        assert jan2_result.ready is True
        assert len(jan2_result.job_ids) == 1
        jan2_job_id = jan2_result.job_ids[0]

        # Verify Jan 2 data
        ch_results_jan2 = self._query_preaggregation_results([jan2_job_id])
        assert len(ch_results_jan2) == 1
        assert ch_results_jan2[0][4] == 1  # user2

        # Second: Run for Jan 1-4 (Jan 2 is covered)
        # Missing: Jan 1, Jan 3 -> 2 contiguous ranges
        result = PreaggregationExecutor().execute(
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
        ch_results = self._query_preaggregation_results(result.job_ids)
        assert len(ch_results) == 3  # 3 days total
        assert ch_results[0][4] == 1  # Jan 1: user1
        assert ch_results[1][4] == 1  # Jan 2: user2
        assert ch_results[2][4] == 1  # Jan 3: user3


class TestHogQLQueryWithPreaggregation(ClickhouseTestMixin, BaseTest):
    """Test execute_hogql_query with usePreaggregatedIntermediateResults modifier."""

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

    def test_preaggregation_modifier_returns_same_results(self):
        """Test that queries with and without preaggregation modifier return the same results."""
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

        # Run without preaggregation modifier
        result_without = execute_hogql_query(
            parse_select(query),
            team=self.team,
        )

        # Run with preaggregation modifier
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

        # Verify data exists in preaggregation table
        preagg_results = sync_execute(
            f"""
            SELECT count()
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.id},
        )
        assert preagg_results[0][0] > 0

    def test_trends_query_dau_with_preaggregation_modifier(self):
        """Test that TrendsQuery with DAU returns same results with and without preaggregation modifier.

        TrendsQuery generates a nested query with count(DISTINCT person_id) which our
        preaggregation pattern supports. The inner query should be transformed to use
        the preaggregation_results table.
        """
        self._create_pageview_events()

        # Run TrendsQuery without preaggregation modifier
        query_without = TrendsQuery(
            series=[EventsNode(name="$pageview", event="$pageview", math=BaseMathType.DAU)],
            dateRange=DateRange(date_from="2025-01-01", date_to="2025-01-02"),
        )
        runner_without = TrendsQueryRunner(team=self.team, query=query_without)
        response_without = runner_without.calculate()

        # Run TrendsQuery with preaggregation modifier
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
        # preaggregation rows were created in the table.
        preagg_results = sync_execute(
            f"""
            SELECT count()
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.id},
        )
        assert preagg_results[0][0] > 0, "Expected preaggregation data to be created"

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

        # Run without preaggregation modifier
        result_without = execute_hogql_query(
            parse_select(query),
            team=self.team,
        )

        # Run with preaggregation modifier
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

        # Verify the preaggregation table was used in the generated SQL
        assert result_with.clickhouse and ("preaggregation_results" in result_with.clickhouse), (
            "Expected preaggregation_results table in generated SQL"
        )

        # Verify preaggregation rows were created in the table
        preagg_results = sync_execute(
            f"""
            SELECT count()
            FROM {DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE()}
            WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.id},
        )
        assert preagg_results[0][0] > 0, "Expected preaggregation data to be created"


class TestBuildManualInsertSQL(BaseTest):
    MANUAL_INSERT_QUERY = """
        SELECT
            toStartOfDay(timestamp) as time_window_start,
            now() as expires_at,
            [] as breakdown_value,
            uniqExactState(person_id) as uniq_exact_state
        FROM events
        WHERE event = '$pageview'
            AND timestamp >= {time_window_min}
            AND timestamp < {time_window_max}
        GROUP BY time_window_start
    """

    def test_adds_job_id_column(self):
        """Test that _build_manual_insert_sql adds job_id as second column."""
        job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
        )

        sql, values = _build_manual_insert_sql(
            team=self.team,
            job=job,
            insert_query=self.MANUAL_INSERT_QUERY,
            table=PreaggregationTable.PREAGGREGATION_RESULTS,
        )

        # Check SQL structure
        assert "INSERT INTO preaggregation_results" in sql
        assert "job_id" in sql
        # job_id should be second in the column list (after team_id)
        assert sql.index("team_id") < sql.index("job_id")
        assert sql.index("job_id") < sql.index("time_window_start")

    def test_substitutes_time_placeholders(self):
        """Test that _build_manual_insert_sql substitutes time placeholders."""
        job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
        )

        sql, values = _build_manual_insert_sql(
            team=self.team,
            job=job,
            insert_query=self.MANUAL_INSERT_QUERY,
            table=PreaggregationTable.PREAGGREGATION_RESULTS,
        )

        # Should contain the job's time range values
        assert "2024-01-01" in sql
        assert "2024-01-02" in sql

    def test_accepts_custom_placeholders(self):
        """Test that _build_manual_insert_sql accepts custom placeholders."""
        job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
        )

        query_with_custom = """
            SELECT
                toStartOfDay(timestamp) as time_window_start,
                now() as expires_at,
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
            table=PreaggregationTable.PREAGGREGATION_RESULTS,
            base_placeholders={"event_name": ast.Constant(value="$pageleave")},
        )

        # The placeholder value should be in the parameterized values
        assert "$pageleave" in values.values()


class TestEnsurePreaggregated(ClickhouseTestMixin, BaseTest):
    MANUAL_INSERT_QUERY = """
        SELECT
            toStartOfDay(timestamp) as time_window_start,
            now() as expires_at,
            [] as breakdown_value,
            uniqExactState(person_id) as uniq_exact_state
        FROM events
        WHERE event = '$pageview'
            AND timestamp >= {time_window_min}
            AND timestamp < {time_window_max}
        GROUP BY time_window_start
    """

    def test_creates_job_and_returns_job_ids(self):
        """Test that ensure_preaggregated creates jobs and returns job IDs."""
        result = ensure_preaggregated(
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
        """Test that ensure_preaggregated reuses existing READY jobs."""
        # First call
        first_result = ensure_preaggregated(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )
        first_job_id = first_result.job_ids[0]

        # Second call with same parameters
        second_result = ensure_preaggregated(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        # Should reuse the existing job
        assert len(second_result.job_ids) == 1
        assert second_result.job_ids[0] == first_job_id

    def test_creates_jobs_for_missing_ranges(self):
        """Test that ensure_preaggregated creates jobs only for missing time ranges."""
        # Create job for Jan 1 only
        first_result = ensure_preaggregated(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )
        jan1_job_id = first_result.job_ids[0]

        # Request Jan 1-3 (Jan 1 exists, Jan 2 missing)
        second_result = ensure_preaggregated(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 3, tzinfo=UTC),
        )

        # Should have 2 job IDs (Jan 1 reused + Jan 2 created)
        assert len(second_result.job_ids) == 2
        assert jan1_job_id in second_result.job_ids

    def test_respects_custom_ttl(self):
        """Test that ensure_preaggregated respects the ttl_seconds parameter."""
        result = ensure_preaggregated(
            team=self.team,
            insert_query=self.MANUAL_INSERT_QUERY,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            ttl_seconds=60 * 60,  # 1 hour
        )

        job = PreaggregationJob.objects.get(id=result.job_ids[0])
        # expires_at should be about 1 hour from now
        assert job.expires_at is not None
        expected_expiry = django_timezone.now()
        time_diff = (job.expires_at - expected_expiry).total_seconds()
        assert 3500 < time_diff < 3700  # 1 hour +/- 100 seconds

    def test_accepts_custom_placeholders(self):
        """Test that ensure_preaggregated accepts custom placeholders."""
        query_with_placeholder = """
            SELECT
                toStartOfDay(timestamp) as time_window_start,
                now() as expires_at,
                [] as breakdown_value,
                uniqExactState(person_id) as uniq_exact_state
            FROM events
            WHERE event = {event_name}
                AND timestamp >= {time_window_min}
                AND timestamp < {time_window_max}
            GROUP BY time_window_start
        """

        result = ensure_preaggregated(
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
            ensure_preaggregated(
                team=self.team,
                insert_query=self.MANUAL_INSERT_QUERY,
                time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
                time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
                placeholders={reserved_name: ast.Constant(value="should_fail")},
            )


class TestPreaggregationExecutor(BaseTest):
    """Tests for the PreaggregationExecutor class."""

    def test_executor_with_custom_settings(self):
        # Test default settings
        default_executor = PreaggregationExecutor()
        assert default_executor.wait_timeout_seconds == DEFAULT_WAIT_TIMEOUT_SECONDS
        assert default_executor.poll_interval_seconds == DEFAULT_POLL_INTERVAL_SECONDS
        assert default_executor.max_retries == DEFAULT_RETRIES
        assert default_executor.ttl_seconds == DEFAULT_TTL_SECONDS

        # Test custom settings
        custom_executor = PreaggregationExecutor(
            wait_timeout_seconds=60.0,
            poll_interval_seconds=0.5,
            max_retries=5,
            ttl_seconds=3600,
        )
        assert custom_executor.wait_timeout_seconds == 60.0
        assert custom_executor.poll_interval_seconds == 0.5
        assert custom_executor.max_retries == 5
        assert custom_executor.ttl_seconds == 3600


class TestTryCreateReplacementJob(BaseTest):
    """Tests for _try_create_replacement_job method."""

    def test_creates_replacement_when_no_pending_exists(self):
        """Test that replacement job is created when no pending job exists for the range."""
        executor = PreaggregationExecutor(max_retries=3)

        failed_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.FAILED,
            expires_at=django_timezone.now(),
        )

        replacement = executor._try_create_replacement_job(failed_job)

        assert replacement is not None
        assert replacement.id != failed_job.id
        assert replacement.team == failed_job.team
        assert replacement.query_hash == failed_job.query_hash
        assert replacement.time_range_start == failed_job.time_range_start
        assert replacement.time_range_end == failed_job.time_range_end
        assert replacement.status == PreaggregationJob.Status.PENDING

    def test_returns_none_when_pending_already_exists(self):
        """Test that returns None when another pending job already exists for the range."""
        executor = PreaggregationExecutor(max_retries=3)

        # Create a failed job
        failed_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.FAILED,
            expires_at=django_timezone.now(),
        )

        # Create an existing pending job for the same range (simulating another waiter won)
        PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now(),
        )

        replacement = executor._try_create_replacement_job(failed_job)

        # Should return None due to unique constraint violation
        assert replacement is None


class TestRaceConditionHandling(BaseTest):
    """Tests for race condition handling when multiple waiters try to create replacement jobs."""

    def test_second_replacement_attempt_fails_due_to_unique_constraint(self):
        """Verify that a second replacement attempt fails when one already exists."""
        executor = PreaggregationExecutor(max_retries=3)

        # Create a failed job
        failed_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_race_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 5, tzinfo=UTC),
            status=PreaggregationJob.Status.FAILED,
            expires_at=django_timezone.now(),
        )

        # First replacement attempt should succeed
        replacement1 = executor._try_create_replacement_job(failed_job)
        assert replacement1 is not None
        assert replacement1.status == PreaggregationJob.Status.PENDING

        # Second replacement attempt should fail (returns None due to unique constraint)
        replacement2 = executor._try_create_replacement_job(failed_job)
        assert replacement2 is None

        # Only one pending job should exist
        pending_count = PreaggregationJob.objects.filter(
            team=self.team,
            query_hash="test_race_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 5, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
        ).count()
        assert pending_count == 1

    def test_replacement_allowed_after_previous_replacement_completes(self):
        executor = PreaggregationExecutor(max_retries=5)

        # Create a failed job
        failed_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_race_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 5, tzinfo=UTC),
            status=PreaggregationJob.Status.FAILED,
            expires_at=django_timezone.now(),
        )

        # First replacement succeeds
        replacement1 = executor._try_create_replacement_job(failed_job)
        assert replacement1 is not None

        # Mark replacement1 as FAILED
        replacement1.status = PreaggregationJob.Status.FAILED
        replacement1.error = "Test error"
        replacement1.save()

        # Now another replacement can be created
        replacement2 = executor._try_create_replacement_job(replacement1)
        assert replacement2 is not None


class TestPreaggregationExecutorWaiting(BaseTest):
    """Tests for PreaggregationExecutor waiting, retry, stale detection, and error handling."""

    def _make_preaggregation_query(self) -> ast.SelectQuery:
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

    # --- Waiting for pending jobs ---

    def test_returns_immediately_when_job_already_ready(self):
        executor = PreaggregationExecutor(wait_timeout_seconds=5.0, poll_interval_seconds=0.1)

        ready_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
            expires_at=django_timezone.now(),
        )

        result = executor._wait_for_pending_jobs(self.team, [ready_job], lambda t, j: None)

        assert result.success is True
        assert ready_job.id in [j.id for j in result.ready_jobs]
        assert len(result.failed_jobs) == 0
        assert result.timed_out is False

    def test_timeout_when_job_stays_pending(self):
        executor = PreaggregationExecutor(wait_timeout_seconds=0.3, poll_interval_seconds=0.1)

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now(),
        )

        result = executor._wait_for_pending_jobs(self.team, [pending_job], lambda t, j: None)

        assert result.success is False
        assert result.timed_out is True
        assert len(result.ready_jobs) == 0

    def test_waits_for_pending_job_to_complete(self):
        executor = PreaggregationExecutor(wait_timeout_seconds=5.0, poll_interval_seconds=0.1)

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now(),
        )

        poll_count = [0]
        original_filter = PreaggregationJob.objects.filter

        def mock_filter(*args, **kwargs):
            result = original_filter(*args, **kwargs)
            if "id__in" in kwargs and poll_count[0] == 0:
                poll_count[0] += 1
                pending_job.status = PreaggregationJob.Status.READY
                pending_job.computed_at = django_timezone.now()
                pending_job.save()
            return result

        with patch.object(PreaggregationJob.objects, "filter", side_effect=mock_filter):
            result = executor._wait_for_pending_jobs(self.team, [pending_job], lambda t, j: None)

        assert result.success is True
        assert pending_job.id in [j.id for j in result.ready_jobs]
        assert result.timed_out is False

    def test_gives_up_at_max_retries(self):
        executor = PreaggregationExecutor(wait_timeout_seconds=2.0, poll_interval_seconds=0.05, max_retries=2)

        failed_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.FAILED,
            error="Previous error",
            expires_at=django_timezone.now(),
        )

        insert_call_count = [0]

        def failing_insert(team, job):
            insert_call_count[0] += 1
            raise Exception("ClickHouse error")

        result = executor._wait_for_pending_jobs(self.team, [failed_job], failing_insert)

        # max_retries=2 means 2 retries before giving up
        assert insert_call_count[0] == 2
        assert result.success is False
        assert len(result.ready_jobs) == 0
        assert len(result.failed_jobs) == 1
        assert result.failed_jobs[0].error is not None and "ClickHouse error" in result.failed_jobs[0].error

    def test_multiple_pending_jobs_with_mixed_outcomes(self):
        executor = PreaggregationExecutor(
            wait_timeout_seconds=5.0,
            poll_interval_seconds=0.05,
            max_retries=2,
        )

        # Three pending jobs for different ranges
        job_a = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash_a",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )
        job_b = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash_b",
            time_range_start=datetime(2024, 1, 2, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 3, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )
        job_c = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash_c",
            time_range_start=datetime(2024, 1, 3, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 4, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        poll_count = [0]
        original_filter = PreaggregationJob.objects.filter

        def mock_filter(*args, **kwargs):
            result = original_filter(*args, **kwargs)
            if "id__in" in kwargs and poll_count[0] == 0:
                poll_count[0] += 1
                # Job A becomes READY
                job_a.status = PreaggregationJob.Status.READY
                job_a.computed_at = django_timezone.now()
                job_a.save()
                # Job B fails
                job_b.status = PreaggregationJob.Status.FAILED
                job_b.error = "Memory limit exceeded"
                job_b.save()
                # Job C becomes READY
                job_c.status = PreaggregationJob.Status.READY
                job_c.computed_at = django_timezone.now()
                job_c.save()
            return result

        def failing_insert(team, job):
            raise ServerException(message="Syntax error", code=62)

        with patch.object(PreaggregationJob.objects, "filter", side_effect=mock_filter):
            result = executor._wait_for_pending_jobs(self.team, [job_a, job_b, job_c], failing_insert)

        assert result.success is False
        ready_ids = {j.id for j in result.ready_jobs}
        assert job_a.id in ready_ids
        assert job_c.id in ready_ids
        assert len(result.failed_jobs) == 1

    # --- Execute with waiting ---

    def test_uses_existing_ready_job_without_clickhouse(self):
        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, table=PreaggregationTable.PREAGGREGATION_RESULTS, timezone="UTC")
        query_hash = compute_query_hash(query_info)

        ready_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        executor = PreaggregationExecutor()

        result = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )

        assert ready_job.id in result.job_ids
        assert result.ready is True

        total_jobs = PreaggregationJob.objects.filter(
            team=self.team,
            query_hash=query_hash,
        ).count()
        assert total_jobs == 1

    def test_does_not_create_duplicate_job_for_pending_range_after_timeout(self):
        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, table=PreaggregationTable.PREAGGREGATION_RESULTS, timezone="UTC")
        query_hash = compute_query_hash(query_info)

        executor = PreaggregationExecutor(
            wait_timeout_seconds=0.3,
            poll_interval_seconds=0.1,
        )

        PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        with patch(
            "products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor.create_preaggregation_job",
            wraps=create_preaggregation_job,
        ) as mock_create:
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
                run_insert=lambda t, j: None,
            )

        # Should not attempt to create a job for the still-PENDING range
        # (doing so would hit IntegrityError and trigger a second wait)
        mock_create.assert_not_called()
        assert result.ready is False
        assert any("Timeout" in e for e in result.errors)

    # --- IntegrityError race handling ---

    def test_execute_waits_for_existing_pending_job_on_integrity_error(self):
        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, table=PreaggregationTable.PREAGGREGATION_RESULTS, timezone="UTC")
        query_hash = compute_query_hash(query_info)

        executor = PreaggregationExecutor(
            wait_timeout_seconds=2.0,
            poll_interval_seconds=0.05,
        )

        # Executor A already created a PENDING job for this range.
        # Our find_existing_jobs missed it (race window), then our
        # create_preaggregation_job hits the unique constraint.
        existing_pending = PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        poll_count = [0]
        original_filter = PreaggregationJob.objects.filter

        def mock_filter(*args, **kwargs):
            result = original_filter(*args, **kwargs)
            if "id__in" in kwargs and poll_count[0] == 0:
                poll_count[0] += 1
                existing_pending.status = PreaggregationJob.Status.READY
                existing_pending.computed_at = django_timezone.now()
                existing_pending.save()
            return result

        with (
            patch(
                "products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor.find_existing_jobs",
                return_value=[],
            ),
            patch(
                "products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor.create_preaggregation_job",
                side_effect=IntegrityError("duplicate key value violates unique constraint"),
            ),
            patch.object(PreaggregationJob.objects, "filter", side_effect=mock_filter),
        ):
            result = executor.execute(
                team=self.team,
                query_info=query_info,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 2, tzinfo=UTC),
                run_insert=lambda t, j: None,
            )

        # Should succeed by waiting for the existing job, not error
        assert result.ready is True
        assert existing_pending.id in result.job_ids
        assert len(result.errors) == 0

    # --- Missing job handling ---

    def test_wait_treats_deleted_job_as_failed(self):
        executor = PreaggregationExecutor(
            wait_timeout_seconds=0.5,
            poll_interval_seconds=0.05,
            max_retries=2,
        )

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        poll_count = [0]
        original_filter = PreaggregationJob.objects.filter

        def mock_filter(*args, **kwargs):
            result = original_filter(*args, **kwargs)
            if "id__in" in kwargs and poll_count[0] == 0:
                poll_count[0] += 1
                PreaggregationJob.objects.filter(id=pending_job.id).delete()
            return result

        with patch.object(PreaggregationJob.objects, "filter", side_effect=mock_filter):
            result = executor._wait_for_pending_jobs(self.team, [pending_job], lambda t, j: None)

        assert result.success is False
        assert len(result.failed_jobs) == 1
        assert result.timed_out is False

    # --- Stale job handling ---

    def test_marks_stale_pending_job_as_failed(self):
        executor = PreaggregationExecutor(
            stale_pending_threshold_seconds=0.1,
            wait_timeout_seconds=1.0,
            poll_interval_seconds=0.05,
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
            updated_at=django_timezone.now() - timedelta(seconds=10)
        )

        result = executor._try_mark_stale_job_as_failed(pending_job)

        assert result is True
        pending_job.refresh_from_db()
        assert pending_job.status == PreaggregationJob.Status.FAILED
        assert pending_job.error is not None and "stale" in pending_job.error.lower()

    def test_stale_job_triggers_replacement_flow(self):
        executor = PreaggregationExecutor(
            stale_pending_threshold_seconds=0.1,
            wait_timeout_seconds=2.0,
            poll_interval_seconds=0.05,
            max_retries=3,
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
            updated_at=django_timezone.now() - timedelta(seconds=10)
        )

        result = executor._wait_for_pending_jobs(self.team, [pending_job], lambda t, j: None)

        assert result.success is True
        assert len(result.ready_jobs) == 1
        assert result.timed_out is False

        pending_job.refresh_from_db()
        assert pending_job.status == PreaggregationJob.Status.FAILED

        replacement = result.ready_jobs[0]
        assert replacement.status == PreaggregationJob.Status.READY
        assert replacement.id != pending_job.id

    def test_only_one_waiter_marks_stale_job(self):
        executor = PreaggregationExecutor(stale_pending_threshold_seconds=0.1)

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )
        PreaggregationJob.objects.filter(id=pending_job.id).update(
            updated_at=django_timezone.now() - timedelta(seconds=10)
        )

        result1 = executor._try_mark_stale_job_as_failed(pending_job)
        assert result1 is True

        result2 = executor._try_mark_stale_job_as_failed(pending_job)
        assert result2 is False

    def test_non_stale_pending_job_not_marked(self):
        executor = PreaggregationExecutor(
            stale_pending_threshold_seconds=300,
            wait_timeout_seconds=0.5,
            poll_interval_seconds=0.1,
        )

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        result = executor._wait_for_pending_jobs(self.team, [pending_job], lambda t, j: None)

        assert result.timed_out is True
        pending_job.refresh_from_db()
        assert pending_job.status == PreaggregationJob.Status.PENDING

    # --- Non-retryable error handling ---

    def test_syntax_error_not_retried(self):
        executor = PreaggregationExecutor(
            wait_timeout_seconds=5.0,
            poll_interval_seconds=0.1,
            max_retries=3,
        )

        failed_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.FAILED,
            error="Previous error",
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        insert_attempt_count = [0]

        def mock_insert(team, job):
            insert_attempt_count[0] += 1
            raise ServerException(message="Syntax error near SELECT", code=62)

        result = executor._wait_for_pending_jobs(self.team, [failed_job], mock_insert)

        assert insert_attempt_count[0] == 1
        assert result.success is False
        assert len(result.failed_jobs) == 1
        assert result.timed_out is False

    def test_non_retryable_error_does_not_block_future_queries(self):
        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, table=PreaggregationTable.PREAGGREGATION_RESULTS, timezone="UTC")
        query_hash = compute_query_hash(query_info)

        executor = PreaggregationExecutor(
            wait_timeout_seconds=5.0,
            poll_interval_seconds=0.1,
            max_retries=3,
        )

        # First call: INSERT always fails with a syntax error (non-retryable)
        result1 = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: (_ for _ in ()).throw(ServerException(message="Syntax error", code=62)),
        )
        assert result1.ready is False
        assert len(result1.errors) > 0

        # The FAILED job should exist in the DB
        failed_jobs = list(
            PreaggregationJob.objects.filter(
                team=self.team, query_hash=query_hash, status=PreaggregationJob.Status.FAILED
            )
        )
        assert len(failed_jobs) >= 1

        # Second call: same range, INSERT succeeds — should create a fresh job
        result2 = executor.execute(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
            run_insert=lambda t, j: None,
        )
        assert result2.ready is True
        assert len(result2.job_ids) == 1
        # The new job should be different from the failed one
        assert result2.job_ids[0] not in {j.id for j in failed_jobs}

    def test_network_error_is_retried(self):
        executor = PreaggregationExecutor(
            wait_timeout_seconds=5.0,
            poll_interval_seconds=0.05,
            max_retries=3,
        )

        failed_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.FAILED,
            error="Previous error",
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        insert_attempt_count = [0]

        def mock_insert(team, job):
            insert_attempt_count[0] += 1
            if insert_attempt_count[0] < 2:
                raise ConnectionError("Connection refused")

        result = executor._wait_for_pending_jobs(self.team, [failed_job], mock_insert)

        assert insert_attempt_count[0] == 2
        assert result.success is True
        assert len(result.ready_jobs) == 1

    def test_retryable_error_triggers_replacement(self):
        executor = PreaggregationExecutor(
            wait_timeout_seconds=2.0,
            poll_interval_seconds=0.05,
            max_retries=4,
        )

        failed_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.FAILED,
            error="Previous memory error",
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        insert_attempt_count = [0]

        def mock_insert(team, job):
            insert_attempt_count[0] += 1
            if insert_attempt_count[0] < 3:
                raise ServerException(message="Memory limit exceeded", code=241)

        result = executor._wait_for_pending_jobs(self.team, [failed_job], mock_insert)

        assert insert_attempt_count[0] == 3
        assert result.success is True
        assert len(result.ready_jobs) == 1
        assert len(result.failed_jobs) == 0

    # --- Exponential backoff ---

    def test_exponential_backoff_increases_poll_interval(self):
        executor = PreaggregationExecutor(
            wait_timeout_seconds=10.0,
            poll_interval_seconds=0.5,
            max_poll_interval_seconds=4.0,
        )

        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        poll_count = [0]
        original_filter = PreaggregationJob.objects.filter

        def mock_filter(*args, **kwargs):
            result = original_filter(*args, **kwargs)
            if "id__in" in kwargs:
                poll_count[0] += 1
                if poll_count[0] >= 5:
                    pending_job.status = PreaggregationJob.Status.READY
                    pending_job.computed_at = django_timezone.now()
                    pending_job.save()
            return result

        sleep_durations: list[float] = []

        def mock_sleep(duration):
            sleep_durations.append(duration)

        with (
            patch.object(PreaggregationJob.objects, "filter", side_effect=mock_filter),
            patch(
                "products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor.time.sleep",
                side_effect=mock_sleep,
            ),
        ):
            result = executor._wait_for_pending_jobs(self.team, [pending_job], lambda t, j: None)

        assert result.success is True
        assert len(sleep_durations) >= 4
        assert sleep_durations[0] == pytest.approx(0.5, abs=0.01)
        assert sleep_durations[1] == pytest.approx(1.0, abs=0.01)
        assert sleep_durations[2] == pytest.approx(2.0, abs=0.01)
        assert sleep_durations[3] == pytest.approx(4.0, abs=0.01)

    def test_backoff_resets_on_replacement_job(self):
        executor = PreaggregationExecutor(
            wait_timeout_seconds=10.0,
            poll_interval_seconds=0.5,
            max_poll_interval_seconds=8.0,
            max_retries=4,
        )

        # Start PENDING so we build up backoff, then fail, then replacement also
        # fails (retryable) forcing another poll — which should use reset interval.
        pending_job = PreaggregationJob.objects.create(
            team=self.team,
            query_hash="test_hash",
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
            status=PreaggregationJob.Status.PENDING,
            expires_at=django_timezone.now() + timedelta(days=7),
        )

        poll_count = [0]
        original_filter = PreaggregationJob.objects.filter

        def mock_filter(*args, **kwargs):
            result = original_filter(*args, **kwargs)
            if "id__in" in kwargs:
                poll_count[0] += 1
                if poll_count[0] == 4:
                    # After 4 polls (backoff: 0.5→1.0→2.0→4.0), job fails
                    pending_job.status = PreaggregationJob.Status.FAILED
                    pending_job.error = "Some error"
                    pending_job.save()
            return result

        insert_attempt_count = [0]

        def mock_insert(team, job):
            insert_attempt_count[0] += 1
            if insert_attempt_count[0] == 1:
                raise ConnectionError("Connection refused")

        sleep_durations: list[float] = []

        def mock_sleep(duration):
            sleep_durations.append(duration)

        with (
            patch.object(PreaggregationJob.objects, "filter", side_effect=mock_filter),
            patch(
                "products.analytics_platform.backend.lazy_preaggregation.lazy_preaggregation_executor.time.sleep",
                side_effect=mock_sleep,
            ),
        ):
            result = executor._wait_for_pending_jobs(self.team, [pending_job], mock_insert)

        assert result.success is True
        # Sequence:
        #   Poll 1: PENDING → sleep(0.5)
        #   Poll 2: PENDING → sleep(1.0)
        #   Poll 3: PENDING → sleep(2.0)
        #   Poll 4: FAILED → reset backoff → create replacement → insert fails
        #            (retryable) → sleep(0.5) ← reset, NOT 4.0
        #   Poll 5: replacement FAILED → create replacement2 → insert succeeds → done
        assert len(sleep_durations) == 4, f"Expected 4 sleeps, got {sleep_durations}"
        assert sleep_durations[0] == pytest.approx(0.5, abs=0.01)
        assert sleep_durations[1] == pytest.approx(1.0, abs=0.01)
        assert sleep_durations[2] == pytest.approx(2.0, abs=0.01)
        # Without reset this would be 4.0 — the reset to 0.5 proves it works
        assert sleep_durations[3] == pytest.approx(0.5, abs=0.01)


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
