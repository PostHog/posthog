from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

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

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.sql import DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE
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
        flush_persons_and_events()

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
        query_info = QueryInfo(query=query, timezone="UTC")

        # First: run for Jan 1-2
        first_result = execute_preaggregation_jobs(
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
        second_result = execute_preaggregation_jobs(
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
        query_info = QueryInfo(query=query, timezone="UTC")

        # First: Create job for Jan 2 only
        jan2_result = execute_preaggregation_jobs(
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
        result = execute_preaggregation_jobs(
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
