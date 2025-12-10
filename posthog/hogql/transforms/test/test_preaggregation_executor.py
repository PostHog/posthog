from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.preaggregation_executor import (
    PreaggregationResult,
    QueryInfo,
    build_preaggregation_insert_sql,
    compute_query_hash,
    execute_preaggregation_jobs,
    find_missing_contiguous_windows,
)

from posthog.models.preaggregation_job import PreaggregationJob


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
                "SELECT uniqExact(person_id) FROM events WHERE event = '$pageview'",
                "SELECT uniqExact(person_id) FROM events WHERE event = '$pageleave'",
            ),
            (
                "different_aggregation",
                "SELECT uniqExact(person_id) FROM events WHERE event = '$pageview'",
                "SELECT count() FROM events WHERE event = '$pageview'",
            ),
            (
                "different_timezone",
                ("SELECT uniqExact(person_id) FROM events", "UTC"),
                ("SELECT uniqExact(person_id) FROM events", "America/New_York"),
            ),
        ]
    )
    def test_similar_queries_hash_differently(self, name, query1, query2):
        if isinstance(query1, tuple):
            query_info1 = QueryInfo(query=parse_select(query1[0]), timezone=query1[1])
            query_info2 = QueryInfo(query=parse_select(query2[0]), timezone=query2[1])
        else:
            query_info1 = QueryInfo(query=parse_select(query1))
            query_info2 = QueryInfo(query=parse_select(query2))

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


class TestBuildPreaggregationInsertSQL(BaseTest):
    def _make_select_query(self, where_clause: str = "") -> ast.SelectQuery:
        """Create a valid preaggregation select query with 3 expressions."""
        where = f"WHERE {where_clause}" if where_clause else ""
        return parse_select(f"SELECT 1 as col1, 2 as col2, 3 as col3 FROM events {where}")

    def test_query_without_where(self):
        job_id = "11111111-1111-1111-1111-111111111111"
        select_query = self._make_select_query()

        sql, values = build_preaggregation_insert_sql(
            team=self.team,
            job_id=job_id,
            select_query=select_query,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        # Substitute the parameterized values back into the SQL for testing
        sql_with_values = sql % values

        assert (
            sql_with_values
            == f"""INSERT INTO writable_preaggregation_results (
    team_id,
    time_window_start,
    breakdown_value,
    uniq_exact_state,
    job_id
)
SELECT {self.team.id} AS team_id, 1 AS col1, 2 AS col2, 3 AS col3, accurateCastOrNull({job_id}, UUID) AS job_id FROM events WHERE and(equals(events.team_id, {self.team.id}), greaterOrEquals(toTimeZone(events.timestamp, UTC), toDateTime64('2024-01-01 00:00:00.000000', 6, 'UTC')), less(toTimeZone(events.timestamp, UTC), toDateTime64('2024-01-02 00:00:00.000000', 6, 'UTC'))) LIMIT 50000"""
        )

    def test_query_with_existing_where(self):
        job_id = "11111111-1111-1111-1111-111111111111"
        select_query = self._make_select_query("event = 'test'")

        sql, values = build_preaggregation_insert_sql(
            team=self.team,
            job_id=job_id,
            select_query=select_query,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        sql_with_values = sql % values

        assert (
            sql_with_values
            == f"""INSERT INTO writable_preaggregation_results (
    team_id,
    time_window_start,
    breakdown_value,
    uniq_exact_state,
    job_id
)
SELECT {self.team.id} AS team_id, 1 AS col1, 2 AS col2, 3 AS col3, accurateCastOrNull({job_id}, UUID) AS job_id FROM events WHERE and(equals(events.team_id, {self.team.id}), equals(events.event, test), and(greaterOrEquals(toTimeZone(events.timestamp, UTC), toDateTime64('2024-01-01 00:00:00.000000', 6, 'UTC')), less(toTimeZone(events.timestamp, UTC), toDateTime64('2024-01-02 00:00:00.000000', 6, 'UTC')))) LIMIT 50000"""
        )

    @parameterized.expand(
        [
            ("job_id_1", "11111111-1111-1111-1111-111111111111"),
            ("job_id_2", "22222222-2222-2222-2222-222222222222"),
        ]
    )
    def test_different_job_ids(self, name, job_id):
        select_query = self._make_select_query()

        sql, values = build_preaggregation_insert_sql(
            team=self.team,
            job_id=job_id,
            select_query=select_query,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        sql_with_values = sql % values

        assert (
            sql_with_values
            == f"""INSERT INTO writable_preaggregation_results (
    team_id,
    time_window_start,
    breakdown_value,
    uniq_exact_state,
    job_id
)
SELECT {self.team.id} AS team_id, 1 AS col1, 2 AS col2, 3 AS col3, accurateCastOrNull({job_id}, UUID) AS job_id FROM events WHERE and(equals(events.team_id, {self.team.id}), greaterOrEquals(toTimeZone(events.timestamp, UTC), toDateTime64('2024-01-01 00:00:00.000000', 6, 'UTC')), less(toTimeZone(events.timestamp, UTC), toDateTime64('2024-01-02 00:00:00.000000', 6, 'UTC'))) LIMIT 50000"""
        )

    def test_does_not_mutate_original_query(self):
        job_id = "11111111-1111-1111-1111-111111111111"
        select_query = self._make_select_query()
        original_where = select_query.where
        original_select_len = len(select_query.select)

        build_preaggregation_insert_sql(
            team=self.team,
            job_id=job_id,
            select_query=select_query,
            time_range_start=datetime(2024, 1, 1, tzinfo=UTC),
            time_range_end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert select_query.where == original_where
        assert len(select_query.select) == original_select_len


class TestExecutePreaggregationJobs(ClickhouseTestMixin, BaseTest):
    def _make_preaggregation_query(self) -> ast.SelectQuery:
        """Create a simple query with 3 columns for testing job orchestration."""
        s = parse_select(
            """
            SELECT
                toStartOfDay(timestamp) as time_window_start,
                [] as breakdown_value,
                count() as cnt
            FROM events
            WHERE event = '$pageview'
            GROUP BY time_window_start
            """
        )
        assert isinstance(s, ast.SelectQuery)
        return s

    def _create_pageview_events(self):
        """Create pageview events across Jan, Feb, and March 2024."""
        # Jan events
        _create_event(
            team=self.team, event="$pageview", distinct_id="user1", timestamp=datetime(2024, 1, 1, 12, tzinfo=UTC)
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="user2", timestamp=datetime(2024, 1, 2, 12, tzinfo=UTC)
        )
        _create_event(
            team=self.team, event="$pageview", distinct_id="user3", timestamp=datetime(2024, 1, 3, 12, tzinfo=UTC)
        )

        # Feb events
        _create_event(
            team=self.team, event="$pageview", distinct_id="user4", timestamp=datetime(2024, 2, 1, 12, tzinfo=UTC)
        )

        # March events
        _create_event(
            team=self.team, event="$pageview", distinct_id="user5", timestamp=datetime(2024, 3, 1, 12, tzinfo=UTC)
        )

        flush_persons_and_events()

    @patch("posthog.hogql.transforms.preaggregation_executor.sync_execute")
    def test_creates_single_job_for_contiguous_date_range(self, mock_sync_execute):
        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, timezone="UTC")

        result = execute_preaggregation_jobs(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 4, tzinfo=UTC),
        )

        assert isinstance(result, PreaggregationResult)
        assert result.ready is True
        assert len(result.errors) == 0
        # Should create 1 job for the contiguous range Jan 1-4
        assert len(result.job_ids) == 1

        # Verify sync_execute was called once for the contiguous range
        assert mock_sync_execute.call_count == 1

        # Verify job exists in PostgreSQL with correct range
        job = PreaggregationJob.objects.get(id=result.job_ids[0])
        assert job.status == PreaggregationJob.Status.READY
        assert job.time_range_start == datetime(2024, 1, 1, tzinfo=UTC)
        assert job.time_range_end == datetime(2024, 1, 4, tzinfo=UTC)

    @patch("posthog.hogql.transforms.preaggregation_executor.sync_execute")
    def test_reuses_existing_job(self, mock_sync_execute):
        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, timezone="UTC")

        # First: run for Feb 1 only
        feb_result = execute_preaggregation_jobs(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 2, 1, tzinfo=UTC),
            end=datetime(2024, 2, 2, tzinfo=UTC),
        )

        assert feb_result.ready is True
        assert len(feb_result.job_ids) == 1
        feb_job_id = feb_result.job_ids[0]

        # Verify Feb job exists in PostgreSQL
        feb_job = PreaggregationJob.objects.get(id=feb_job_id)
        assert feb_job.status == PreaggregationJob.Status.READY
        assert feb_job.time_range_start == datetime(2024, 2, 1, tzinfo=UTC)

        # sync_execute called once for Feb
        assert mock_sync_execute.call_count == 1

        # Second: run again for Feb 1
        feb_result_2 = execute_preaggregation_jobs(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 2, 1, tzinfo=UTC),
            end=datetime(2024, 2, 2, tzinfo=UTC),
        )

        # Should reuse the existing job, so sync_execute should not be called again
        assert mock_sync_execute.call_count == 1

        # Should reuse the existing job
        assert feb_result_2.ready is True
        assert len(feb_result_2.job_ids) == 1
        assert feb_result_2.job_ids[0] == feb_job_id

        # Verify only 1 job exists in PostgreSQL
        query_hash = feb_job.query_hash
        total_jobs = PreaggregationJob.objects.filter(
            team=self.team,
            query_hash=query_hash,
            status=PreaggregationJob.Status.READY,
        ).count()
        assert total_jobs == 1

    @patch("posthog.hogql.transforms.preaggregation_executor.sync_execute")
    def test_creates_two_contiguous_ranges_when_feb_exists(self, mock_sync_execute):
        """Test that contiguous missing ranges are created when some jobs already exist."""
        query = self._make_preaggregation_query()
        query_info = QueryInfo(query=query, timezone="UTC")

        # First: Create Feb job (covers Feb 1 only)
        feb_result = execute_preaggregation_jobs(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 2, 1, tzinfo=UTC),
            end=datetime(2024, 2, 2, tzinfo=UTC),
        )
        assert feb_result.ready is True
        assert len(feb_result.job_ids) == 1
        feb_job_id = feb_result.job_ids[0]
        assert mock_sync_execute.call_count == 1

        # Second: Run for Jan 31 - Feb 3 (4 days: Jan 31, Feb 1, Feb 2, Feb 3)
        # Feb 1 is covered, so missing = Jan 31, Feb 2-3
        # This should create 2 contiguous ranges:
        # - Jan 31 (single day before Feb 1)
        # - Feb 2-3 (after Feb 1)
        result = execute_preaggregation_jobs(
            team=self.team,
            query_info=query_info,
            start=datetime(2024, 1, 31, tzinfo=UTC),
            end=datetime(2024, 2, 4, tzinfo=UTC),
        )

        assert result.ready is True
        # 3 jobs: existing Feb 1 + 2 new contiguous ranges (Jan 31, Feb 2-4)
        assert len(result.job_ids) == 3

        # Verify sync_execute was called twice (once for Jan 31, once for Feb 2-4)
        assert mock_sync_execute.call_count == 1 + 2  # 1 for original Feb, 2 new

        # Verify Feb 1 job was reused
        assert feb_job_id in result.job_ids

        # Verify jobs in PostgreSQL
        postgres_jobs = list(
            PreaggregationJob.objects.filter(
                team=self.team,
                id__in=result.job_ids,
                status=PreaggregationJob.Status.READY,
            ).order_by("time_range_start")
        )
        assert len(postgres_jobs) == 3
        # Jan 31
        assert postgres_jobs[0].time_range_start == datetime(2024, 1, 31, tzinfo=UTC)
        assert postgres_jobs[0].time_range_end == datetime(2024, 2, 1, tzinfo=UTC)
        # Feb 1 (original)
        assert postgres_jobs[1].time_range_start == datetime(2024, 2, 1, tzinfo=UTC)
        assert postgres_jobs[1].time_range_end == datetime(2024, 2, 2, tzinfo=UTC)
        # Feb 2-4
        assert postgres_jobs[2].time_range_start == datetime(2024, 2, 2, tzinfo=UTC)
        assert postgres_jobs[2].time_range_end == datetime(2024, 2, 4, tzinfo=UTC)
