import os
from datetime import date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import duckdb
import psycopg
from parameterized import parameterized

from posthog.dags.events_backfill_to_duckling import (
    DUCKLAKE_ALIAS,
    DUCKLING_BACKFILL_CONCURRENCY_TAG,
    EARLIEST_BACKFILL_DATE,
    EVENTS_COLUMNS,
    EVENTS_CONCURRENCY_TAG,
    EVENTS_TABLE_DDL,
    EXPECTED_DUCKLAKE_EVENTS_COLUMNS,
    EXPECTED_DUCKLAKE_PERSONS_COLUMNS,
    MAX_S3_FILE_FANOUT,
    PERSONS_COLUMNS,
    PERSONS_CONCURRENCY_TAG,
    PERSONS_TABLE_DDL,
    TARGET_ROWS_PER_FILE,
    DucklingBackfillConfig,
    DucklingTarget,
    _compute_fanout,
    _connect_duckgres,
    _connection_dropped,
    _duckgres_backfill_options,
    _DuckgresSession,
    _estimate_export_row_count,
    _execute_export_with_retry,
    _get_cluster,
    _glob_run_files,
    _resolve_duckling_target,
    _set_table_partitioning,
    _validate_identifier,
    delete_events_partition_data,
    duckling_events_full_backfill_sensor,
    export_events_to_duckling_s3,
    export_persons_full_to_duckling_s3,
    export_persons_to_duckling_s3,
    get_months_in_range,
    get_s3_url_for_clickhouse,
    is_full_export_partition,
    parse_partition_key,
    parse_partition_key_dates,
    register_files_with_duckling,
    register_persons_files_with_duckling,
    table_exists,
)


class TestResolveDucklingTarget:
    @patch("posthog.dags.events_backfill_to_duckling.derive_duckling_bucket", return_value=("bkt", "us-west-2"))
    @patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1")
    def test_builds_target_from_org_and_derived_bucket(self, mock_org: MagicMock, mock_derive: MagicMock):
        target = _resolve_duckling_target(7)

        assert target == DucklingTarget(team_id=7, organization_id="org-1", bucket="bkt", bucket_region="us-west-2")
        mock_org.assert_called_once_with(7)
        mock_derive.assert_called_once_with("org-1")


class TestParsePartitionKey:
    @parameterized.expand(
        [
            ("12345_2024-01-15", (12345, "2024-01-15")),
            ("1_2020-12-31", (1, "2020-12-31")),
            ("999999_2025-06-01", (999999, "2025-06-01")),
            ("12345_2024-01", (12345, "2024-01")),
            ("1_2020-12", (1, "2020-12")),
        ]
    )
    def test_valid_partition_keys(self, input_key, expected):
        assert parse_partition_key(input_key) == expected

    @parameterized.expand(
        [
            ("invalid", "Invalid partition key format"),
            ("abc_2024-01-15", "Invalid team_id"),
            ("12345_invalid-date", "Invalid date"),
            ("12345_2024/01/15", "Invalid date"),
            ("12345", "Invalid partition key format"),
            ("", "Invalid partition key format"),
        ]
    )
    def test_invalid_partition_keys(self, input_key, expected_error_substr):
        with pytest.raises(ValueError) as exc_info:
            parse_partition_key(input_key)
        assert expected_error_substr in str(exc_info.value)


class TestGetS3UrlForClickhouse:
    @parameterized.expand(
        [
            (
                "bucket",
                "us-east-1",
                "path/file.parquet",
                "https://bucket.s3.us-east-1.amazonaws.com/path/file.parquet",
            ),
            (
                "my-bucket",
                "eu-west-1",
                "a/b/c.parquet",
                "https://my-bucket.s3.eu-west-1.amazonaws.com/a/b/c.parquet",
            ),
            (
                "duckling-bucket",
                "us-west-2",
                "backfill/events/123/2024/01/15/abc.parquet",
                "https://duckling-bucket.s3.us-west-2.amazonaws.com/backfill/events/123/2024/01/15/abc.parquet",
            ),
        ]
    )
    def test_url_format(self, bucket, region, path, expected):
        assert get_s3_url_for_clickhouse(bucket, region, path) == expected


class TestValidateIdentifier:
    @parameterized.expand(
        [
            ("valid",),
            ("valid_with_underscore",),
            ("Valid123",),
            ("_leading_underscore",),
            ("main",),
            ("duckling",),
        ]
    )
    def test_valid_identifiers(self, identifier):
        # Should not raise
        _validate_identifier(identifier)

    @parameterized.expand(
        [
            ("invalid-hyphen", "Invalid SQL identifier"),
            ("invalid.dot", "Invalid SQL identifier"),
            ("invalid;semicolon", "Invalid SQL identifier"),
            ("invalid'quote", "Invalid SQL identifier"),
            ('invalid"doublequote', "Invalid SQL identifier"),
            ("invalid space", "Invalid SQL identifier"),
            ("DROP TABLE users;--", "Invalid SQL identifier"),
        ]
    )
    def test_invalid_identifiers(self, identifier, expected_error_substr):
        with pytest.raises(ValueError) as exc_info:
            _validate_identifier(identifier)
        assert expected_error_substr in str(exc_info.value)


class TestTableExists:
    """Identifier-validation tests for `table_exists`.

    The actual existence check now runs against a duckgres pgwire server, so
    the round-trip behavior is covered by integration tests rather than this
    unit suite. The validation here still runs before any SQL executes,
    so a `MagicMock()` connection is sufficient.
    """

    def test_rejects_invalid_catalog_alias(self):
        with pytest.raises(ValueError) as exc_info:
            table_exists(MagicMock(), "invalid;injection", "main", "test")
        assert "Invalid SQL identifier" in str(exc_info.value)

    def test_rejects_invalid_schema(self):
        with pytest.raises(ValueError) as exc_info:
            table_exists(MagicMock(), "memory", "DROP TABLE", "test")
        assert "Invalid SQL identifier" in str(exc_info.value)

    def test_rejects_invalid_table(self):
        with pytest.raises(ValueError) as exc_info:
            table_exists(MagicMock(), "memory", "main", "test'; DROP TABLE users;--")
        assert "Invalid SQL identifier" in str(exc_info.value)


class TestEventsDDL:
    def test_events_ddl_is_valid_sql(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        ddl = EVENTS_TABLE_DDL.format(catalog="memory")
        conn.execute(ddl)

        # Verify table was created with expected columns
        result = conn.execute("DESCRIBE memory.posthog.events").fetchall()
        column_names = {row[0] for row in result}

        assert column_names == EXPECTED_DUCKLAKE_EVENTS_COLUMNS
        conn.close()

    def test_events_ddl_is_idempotent(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        ddl = EVENTS_TABLE_DDL.format(catalog="memory")
        # Should not raise on second execution
        conn.execute(ddl)
        conn.execute(ddl)
        conn.close()


class TestPersonsDDL:
    def test_persons_ddl_is_valid_sql(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        ddl = PERSONS_TABLE_DDL.format(catalog="memory")
        conn.execute(ddl)

        # Verify table was created with expected columns
        result = conn.execute("DESCRIBE memory.posthog.persons").fetchall()
        column_names = {row[0] for row in result}

        assert column_names == EXPECTED_DUCKLAKE_PERSONS_COLUMNS
        conn.close()

    def test_persons_ddl_is_idempotent(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        ddl = PERSONS_TABLE_DDL.format(catalog="memory")
        # Should not raise on second execution
        conn.execute(ddl)
        conn.execute(ddl)
        conn.close()


class TestParsePartitionKeyDates:
    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_daily_format_returns_single_date(self, mock_timezone):
        mock_timezone.now.return_value = datetime(2024, 6, 15, 12, 0, 0)
        team_id, dates = parse_partition_key_dates("12345_2024-01-15")
        assert team_id == 12345
        assert dates == [datetime(2024, 1, 15)]

    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_daily_format_future_date_returns_empty(self, mock_timezone):
        mock_timezone.now.return_value = datetime(2024, 6, 15, 12, 0, 0)
        team_id, dates = parse_partition_key_dates("12345_2024-06-20")
        assert team_id == 12345
        assert dates == []

    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_monthly_format_past_month_returns_all_days(self, mock_timezone):
        mock_timezone.now.return_value = datetime(2024, 6, 15, 12, 0, 0)
        team_id, dates = parse_partition_key_dates("12345_2024-01")
        assert team_id == 12345
        assert len(dates) == 31
        assert dates[0] == datetime(2024, 1, 1)
        assert dates[-1] == datetime(2024, 1, 31)

    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_monthly_format_current_month_returns_up_to_yesterday(self, mock_timezone):
        mock_timezone.now.return_value = datetime(2024, 6, 15, 12, 0, 0)
        team_id, dates = parse_partition_key_dates("12345_2024-06")
        assert team_id == 12345
        assert len(dates) == 14
        assert dates[0] == datetime(2024, 6, 1)
        assert dates[-1] == datetime(2024, 6, 14)

    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_monthly_format_future_month_returns_empty(self, mock_timezone):
        mock_timezone.now.return_value = datetime(2024, 6, 15, 12, 0, 0)
        team_id, dates = parse_partition_key_dates("12345_2024-07")
        assert team_id == 12345
        assert dates == []

    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_monthly_format_leap_year_february(self, mock_timezone):
        mock_timezone.now.return_value = datetime(2024, 6, 15, 12, 0, 0)
        team_id, dates = parse_partition_key_dates("12345_2024-02")
        assert team_id == 12345
        assert len(dates) == 29
        assert dates[-1] == datetime(2024, 2, 29)

    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_monthly_format_non_leap_year_february(self, mock_timezone):
        mock_timezone.now.return_value = datetime(2024, 6, 15, 12, 0, 0)
        team_id, dates = parse_partition_key_dates("12345_2023-02")
        assert team_id == 12345
        assert len(dates) == 28
        assert dates[-1] == datetime(2023, 2, 28)


class TestGetMonthsInRange:
    @parameterized.expand(
        [
            (date(2024, 1, 15), date(2024, 1, 20), ["2024-01"]),
            (date(2024, 1, 1), date(2024, 3, 15), ["2024-01", "2024-02", "2024-03"]),
            (
                date(2023, 11, 1),
                date(2024, 2, 15),
                ["2023-11", "2023-12", "2024-01", "2024-02"],
            ),
            (
                date(2022, 6, 1),
                date(2024, 2, 15),
                [
                    "2022-06",
                    "2022-07",
                    "2022-08",
                    "2022-09",
                    "2022-10",
                    "2022-11",
                    "2022-12",
                    "2023-01",
                    "2023-02",
                    "2023-03",
                    "2023-04",
                    "2023-05",
                    "2023-06",
                    "2023-07",
                    "2023-08",
                    "2023-09",
                    "2023-10",
                    "2023-11",
                    "2023-12",
                    "2024-01",
                    "2024-02",
                ],
            ),
        ]
    )
    def test_returns_correct_months(self, start_date, end_date, expected):
        assert get_months_in_range(start_date, end_date) == expected


class TestSetTablePartitioning:
    """Identifier-validation only — the SET PARTITIONED BY behavior itself is a
    DuckLake property and is exercised via duckgres integration tests rather
    than this unit suite.
    """

    def test_partitioning_rejects_invalid_identifiers(self):
        mock_context = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            _set_table_partitioning(
                MagicMock(),
                "test; DROP TABLE",
                "events",
                "year(timestamp)",
                mock_context,
                team_id=123,
            )
        assert "Invalid SQL identifier" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            _set_table_partitioning(
                MagicMock(),
                "test_catalog",
                "events'; --",
                "year(timestamp)",
                mock_context,
                team_id=123,
            )
        assert "Invalid SQL identifier" in str(exc_info.value)


class TestExportSQLOrderBy:
    def test_events_columns_can_be_used_in_order_by(self):
        """Verify that the columns used in ORDER BY exist in EVENTS_COLUMNS."""
        # The ORDER BY clause uses: event, distinct_id, timestamp
        # These should all be present in EVENTS_COLUMNS
        events_columns_lower = EVENTS_COLUMNS.lower()
        assert "event" in events_columns_lower
        assert "distinct_id" in events_columns_lower
        assert "timestamp" in events_columns_lower

    def test_persons_columns_can_be_used_in_order_by(self):
        """Verify that the columns used in ORDER BY exist in PERSONS_COLUMNS."""
        # The ORDER BY clause uses: distinct_id, _timestamp
        # These should all be present in PERSONS_COLUMNS
        persons_columns_lower = PERSONS_COLUMNS.lower()
        assert "distinct_id" in persons_columns_lower
        assert "_timestamp" in persons_columns_lower


class TestIsFullExportPartition:
    @parameterized.expand(
        [
            ("12345", True),
            ("1", True),
            ("999999", True),
            ("12345_2024-01-15", False),
            ("12345_2024-01", False),
            ("1_2020-12-31", False),
            (
                "12345-2024-01",
                False,
            ),  # Invalid format with hyphen instead of underscore
            ("abc", False),  # Non-numeric
            ("", False),  # Empty string
        ]
    )
    def test_detects_partition_format(self, key, expected):
        assert is_full_export_partition(key) == expected


class TestDeleteErrorHandling:
    """Verify the exception contract for delete_*_partition_data.

    Missing-table errors must be swallowed (return 0) so first-run partitions
    don't fail. Operational/connection errors must propagate so caller-level
    retry/handling can deal with transient failures.
    """

    @parameterized.expand(
        [
            ("events", "delete_events_partition_data", datetime(2024, 1, 1)),
            ("persons_daily", "delete_persons_partition_data", datetime(2024, 1, 1)),
            ("persons_full", "delete_persons_partition_data", None),
        ]
    )
    @patch("posthog.dags.events_backfill_to_duckling.logger")
    def test_handles_missing_table(self, _label, fn_name, partition_date, mock_logger):
        from posthog.dags import events_backfill_to_duckling as mod

        delete_fn = getattr(mod, fn_name)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value.execute.side_effect = psycopg.errors.UndefinedTable()

        count = delete_fn(MagicMock(), MagicMock(), 12345, partition_date, conn=mock_conn)

        assert count == 0
        assert mock_logger.exception.call_count == 0

    @parameterized.expand(
        [
            ("events", "delete_events_partition_data"),
            ("persons", "delete_persons_partition_data"),
        ]
    )
    def test_bubbles_operational_error(self, _label, fn_name):
        from posthog.dags import events_backfill_to_duckling as mod

        delete_fn = getattr(mod, fn_name)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value.execute.side_effect = psycopg.OperationalError("timeout")

        with pytest.raises(psycopg.OperationalError):
            delete_fn(MagicMock(), MagicMock(), 12345, datetime(2024, 1, 1), conn=mock_conn)


class TestDeleteRangePredicate:
    """Validate the half-open range predicate used by delete_*_partition_data.

    These tests use in-process DuckDB ($N parameter binding) to verify the SQL
    logic independently of the psycopg→duckgres connection path. The production
    code uses psycopg %s bindings; the date-range predicate itself is binding-
    agnostic and should behave identically through either binding layer.
    """

    @parameterized.expand(
        [
            # (timestamps_to_insert, target_date, expected_deleted, expected_remaining)
            (
                [
                    "2024-01-15 00:00:00",
                    "2024-01-15 12:30:00",
                    "2024-01-15 23:59:59.999999",
                ],
                "2024-01-15",
                3,
                0,
            ),
            (
                [
                    "2024-01-14 23:59:59.999999",
                    "2024-01-15 00:00:00",
                    "2024-01-16 00:00:00",
                ],
                "2024-01-15",
                1,
                2,
            ),
            (
                [
                    "2024-02-29 00:00:00",
                    "2024-02-29 23:59:59.999999",
                    "2024-03-01 00:00:00",
                ],
                "2024-02-29",
                2,
                1,
            ),
        ]
    )
    def test_range_predicate_deletes_correct_rows(self, timestamps, target_date, expected_deleted, expected_remaining):
        conn = duckdb.connect()
        try:
            conn.execute("CREATE TABLE events (team_id INTEGER, timestamp TIMESTAMPTZ)")
            for ts in timestamps:
                conn.execute("INSERT INTO events VALUES (1, ?)", [ts])

            date_str = target_date
            next_date_str = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

            result = conn.execute(
                "DELETE FROM events WHERE team_id = $1 AND timestamp >= $2 AND timestamp < $3",
                [1, date_str, next_date_str],
            ).fetchone()

            deleted = result[0] if result else 0
            assert deleted == expected_deleted

            row = conn.execute("SELECT count(*) FROM events").fetchone()
            remaining = row[0] if row else 0
            assert remaining == expected_remaining
        finally:
            conn.close()


class TestFullBackfillSensorEarliestDate:
    @parameterized.expand(
        [
            # (earliest_dt_from_clickhouse, expected_first_month)
            ("pre-2015 clamped to 2015-01", datetime(2010, 3, 1), "2015-01"),
            ("exactly 2015-01-01 unchanged", datetime(2015, 1, 1), "2015-01"),
            ("post-2015 unchanged", datetime(2020, 6, 15), "2020-06"),
        ]
    )
    @patch("posthog.dags.events_backfill_to_duckling.get_earliest_event_date_for_team")
    @patch("posthog.dags.events_backfill_to_duckling.DuckLakeBackfill")
    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_earliest_date_clamped(
        self,
        _name,
        earliest_dt,
        expected_first_month,
        mock_tz,
        mock_backfill_cls,
        mock_get_earliest,
    ):
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        mock_tz.now.return_value = datetime(2025, 2, 10, 12, 0, 0)
        mock_get_earliest.return_value = earliest_dt

        backfill = MagicMock()
        backfill.team_id = 1
        mock_backfill_cls.objects.filter.return_value.order_by.return_value = [backfill]

        instance = DagsterInstance.ephemeral()
        context = build_sensor_context(instance=instance)
        result = duckling_events_full_backfill_sensor(context)
        assert isinstance(result, SensorResult)
        assert result.run_requests is not None

        assert len(result.run_requests) > 0
        first_key = result.run_requests[0].partition_key
        assert first_key == f"1_{expected_first_month}"

    @patch("posthog.dags.events_backfill_to_duckling.get_earliest_event_date_for_team")
    @patch("posthog.dags.events_backfill_to_duckling.DuckLakeBackfill")
    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_no_events_returns_empty(self, mock_tz, mock_backfill_cls, mock_get_earliest):
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        mock_tz.now.return_value = datetime(2025, 2, 10, 12, 0, 0)
        mock_get_earliest.return_value = None

        backfill = MagicMock()
        backfill.team_id = 1
        mock_backfill_cls.objects.filter.return_value.order_by.return_value = [backfill]

        instance = DagsterInstance.ephemeral()
        context = build_sensor_context(instance=instance)
        result = duckling_events_full_backfill_sensor(context)
        assert isinstance(result, SensorResult)
        assert result.run_requests is not None

        assert len(result.run_requests) == 0

    def test_earliest_backfill_date_is_2015(self):
        assert EARLIEST_BACKFILL_DATE == datetime(2015, 1, 1)


class TestGetClusterRetry:
    @patch("tenacity.nap.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling.get_cluster")
    def test_retries_on_timeout_then_succeeds(self, mock_get_cluster, mock_sleep):
        mock_cluster = MagicMock()
        mock_get_cluster.side_effect = [
            TimeoutError("timed out"),
            TimeoutError("timed out"),
            mock_cluster,
        ]

        result = _get_cluster()

        assert result is mock_cluster
        assert mock_get_cluster.call_count == 3

    @patch("tenacity.nap.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling.get_cluster")
    def test_raises_non_retryable_exception_immediately(self, mock_get_cluster, mock_sleep):
        mock_get_cluster.side_effect = ValueError("bad config")

        with pytest.raises(ValueError, match="bad config"):
            _get_cluster()

        assert mock_get_cluster.call_count == 1

    @patch("tenacity.nap.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling.get_cluster")
    def test_raises_after_max_retries_exhausted(self, mock_get_cluster, mock_sleep):
        mock_get_cluster.side_effect = TimeoutError("timed out")

        with pytest.raises(TimeoutError):
            _get_cluster()

        assert mock_get_cluster.call_count == 3


class TestDuckLakeAddDataFilesPartitioning:
    """Integration tests proving that ducklake_add_data_files succeeds/fails
    based on whether the S3 path Hive keys match the table's partition fields.

    These tests use a real DuckLake catalog (local DuckDB file) to exercise
    the exact code path that produces the "invalid partition value" error.
    """

    @pytest.fixture
    def ducklake_env(self, tmp_path):
        """Create a DuckLake catalog with a partitioned events table and a sample parquet file."""
        catalog_path = str(tmp_path / "test.ducklake")
        data_path = str(tmp_path / "data")
        os.makedirs(data_path)

        conn = duckdb.connect()
        conn.execute("INSTALL ducklake")
        conn.execute("LOAD ducklake")
        conn.execute(f"ATTACH 'ducklake:{catalog_path}' AS test_lake (DATA_PATH '{data_path}')")
        conn.execute("CREATE SCHEMA IF NOT EXISTS test_lake.posthog")
        conn.execute(EVENTS_TABLE_DDL.format(catalog="test_lake"))
        conn.execute(
            "ALTER TABLE test_lake.posthog.events "
            "SET PARTITIONED BY (year(timestamp), month(timestamp), day(timestamp))"
        )

        # Write a minimal parquet file with the same columns as the events table
        parquet_dir = str(tmp_path / "parquet")
        os.makedirs(parquet_dir)
        conn.execute(f"""
            COPY (
                SELECT
                    'abc-123'::VARCHAR AS uuid,
                    '$pageview'::VARCHAR AS event,
                    '{{}}'::VARCHAR AS properties,
                    '2026-03-30 12:00:00+00'::TIMESTAMPTZ AS timestamp,
                    2::BIGINT AS team_id,
                    2::BIGINT AS project_id,
                    'user1'::VARCHAR AS distinct_id,
                    ''::VARCHAR AS elements_chain,
                    '2026-03-30 12:00:00+00'::TIMESTAMPTZ AS created_at,
                    'person-1'::VARCHAR AS person_id,
                    '2026-03-30 12:00:00+00'::TIMESTAMPTZ AS person_created_at,
                    '{{}}'::VARCHAR AS person_properties,
                    '{{}}'::VARCHAR AS group0_properties,
                    '{{}}'::VARCHAR AS group1_properties,
                    '{{}}'::VARCHAR AS group2_properties,
                    '{{}}'::VARCHAR AS group3_properties,
                    '{{}}'::VARCHAR AS group4_properties,
                    '2026-03-30 12:00:00+00'::TIMESTAMPTZ AS group0_created_at,
                    '2026-03-30 12:00:00+00'::TIMESTAMPTZ AS group1_created_at,
                    '2026-03-30 12:00:00+00'::TIMESTAMPTZ AS group2_created_at,
                    '2026-03-30 12:00:00+00'::TIMESTAMPTZ AS group3_created_at,
                    '2026-03-30 12:00:00+00'::TIMESTAMPTZ AS group4_created_at,
                    'full'::VARCHAR AS person_mode,
                    false::BOOLEAN AS historical_migration,
                    '2026-03-30 12:00:00+00'::TIMESTAMPTZ AS _inserted_at
            ) TO '{parquet_dir}/events.parquet' (FORMAT PARQUET)
        """)

        yield conn, parquet_dir

        conn.close()

    def test_new_path_format_succeeds(self, ducklake_env):
        """Path with plain team_id + Hive year/month/day keys: 3 partition values = 3 fields."""
        conn, parquet_dir = ducklake_env

        # Simulate the new path format: {team_id}/year={year}/month={month}/day={day}/
        dest = os.path.join(parquet_dir, "2", "year=2026", "month=03", "day=30")
        os.makedirs(dest)
        os.link(
            os.path.join(parquet_dir, "events.parquet"),
            os.path.join(dest, "run1.parquet"),
        )

        path = os.path.join(dest, "run1.parquet")
        conn.execute(f"CALL ducklake_add_data_files('test_lake', 'events', '{path}', schema => 'posthog')")

        # Verify the data is queryable
        result = conn.execute("SELECT count(*) FROM test_lake.posthog.events").fetchone()
        assert result[0] == 1

    def test_old_path_format_with_hive_team_id_fails(self, ducklake_env):
        """Path with Hive team_id=X: 4 partition values vs 3 fields -> error."""
        conn, parquet_dir = ducklake_env

        # Simulate the old path format: team_id={team_id}/year={year}/month={month}/day={day}/
        dest = os.path.join(parquet_dir, "team_id=2", "year=2026", "month=03", "day=30")
        os.makedirs(dest)
        os.link(
            os.path.join(parquet_dir, "events.parquet"),
            os.path.join(dest, "run1.parquet"),
        )

        path = os.path.join(dest, "run1.parquet")
        with pytest.raises(duckdb.InvalidInputException, match="invalid partition value"):
            conn.execute(f"CALL ducklake_add_data_files('test_lake', 'events', '{path}', schema => 'posthog')")

    def test_plain_path_no_hive_keys_fails(self, ducklake_env):
        """Path with no Hive keys at all: 0 partition values vs 3 fields -> error."""
        conn, parquet_dir = ducklake_env

        # Simulate the intermediate "fix" path format: {team_id}/{year}/{month}/{day}/
        dest = os.path.join(parquet_dir, "2", "2026", "03", "30")
        os.makedirs(dest)
        os.link(
            os.path.join(parquet_dir, "events.parquet"),
            os.path.join(dest, "run1.parquet"),
        )

        path = os.path.join(dest, "run1.parquet")
        with pytest.raises(duckdb.InvalidInputException, match="invalid partition value"):
            conn.execute(f"CALL ducklake_add_data_files('test_lake', 'events', '{path}', schema => 'posthog')")

    def test_hive_partitioning_false_with_plain_path_still_fails(self, ducklake_env):
        """hive_partitioning => false skips parsing entirely: 0 partition values vs 3 fields -> error."""
        conn, parquet_dir = ducklake_env

        dest = os.path.join(parquet_dir, "2", "2026", "03", "30")
        os.makedirs(dest, exist_ok=True)
        os.link(
            os.path.join(parquet_dir, "events.parquet"),
            os.path.join(dest, "run2.parquet"),
        )

        path = os.path.join(dest, "run2.parquet")
        with pytest.raises(duckdb.InvalidInputException, match="invalid partition value"):
            conn.execute(
                f"CALL ducklake_add_data_files('test_lake', 'events', '{path}',"
                f" schema => 'posthog', hive_partitioning => false)"
            )


class TestDucklingConcurrencyTags:
    # The combined events+persons cap is enforced on the shared key in the charts
    # Dagster deployment settings. If either backfill drops the shared tag, the
    # cap silently stops applying to it — guard against that here.
    @parameterized.expand(
        [
            ("events", EVENTS_CONCURRENCY_TAG),
            ("persons", PERSONS_CONCURRENCY_TAG),
        ]
    )
    def test_backfill_carries_shared_concurrency_key(self, _name, tag_dict):
        ((shared_key, shared_value),) = DUCKLING_BACKFILL_CONCURRENCY_TAG.items()
        assert tag_dict[shared_key] == shared_value


class TestConnectionDropped:
    """_connection_dropped decides which errors mean "the worker/connection went
    away, reconnect to a fresh worker" vs. a real SQL error that must propagate.
    """

    @parameterized.expand(
        [
            ("connection_exception", psycopg.errors.ConnectionException()),
            ("server_closed", psycopg.OperationalError("server closed the connection unexpectedly")),
            ("connection_lost", psycopg.OperationalError("connection to server was lost")),
        ]
    )
    def test_operational_error_connection_loss_is_dropped(self, _label, exc):
        assert _connection_dropped(exc) is True

    @parameterized.expand(
        [
            # The exact shape the control plane surfaced when the backfill worker
            # pod died mid-DELETE (gRPC Unavailable wrapping a reset socket).
            ("reset", "flight execute update: rpc error: code = Unavailable desc = ...: connection reset by peer"),
            ("refused", "transport: Error while dialing: dial tcp 10.0.0.1:8816: connect: connection refused"),
            ("unavailable", "rpc error: code = Unavailable"),
            ("reading", "error reading from server"),
        ]
    )
    def test_internal_error_worker_gone_is_dropped(self, _label, msg):
        assert _connection_dropped(psycopg.InternalError(msg)) is True

    @parameterized.expand(
        [
            ("constraint", "Constraint Error: duplicate key value"),
            ("generic_unavailable", "Catalog Error: schema unavailable for team"),
            # duckgres prefixes EVERY worker-side SQL error with "flight execute",
            # so these are flight-wrapped genuine engine errors. They must NOT be
            # classified as transport drops (else they'd be retried 4x). This pins
            # that we match on transport phrases, not the "flight execute" prefix.
            (
                "flight_wrapped_oom",
                "flight execute update: rpc error: code = Internal desc = Out of Memory Error: "
                "failed to allocate 4.0 GiB (limit 16.0 GiB)",
            ),
            (
                "flight_wrapped_binder",
                "flight execute: rpc error: code = InvalidArgument desc = Binder Error: "
                'Referenced column "nope" not found',
            ),
        ]
    )
    def test_internal_error_real_sql_error_is_not_dropped(self, _label, msg):
        # A genuine engine error (not a transport failure) must propagate, not retry.
        assert _connection_dropped(psycopg.InternalError(msg)) is False

    def test_internal_error_non_unavailable_transport_drop_is_dropped(self):
        # A torn stream can carry a gRPC code other than Unavailable; the
        # transport-phrase markers (here "transport:") still catch it.
        msg = "flight execute: rpc error: code = Internal desc = transport: error while reading: EOF"
        assert _connection_dropped(psycopg.InternalError(msg)) is True

    @parameterized.expand(
        [
            ("disk_full", psycopg.errors.DiskFull()),
            ("undefined_table", psycopg.errors.UndefinedTable()),
            ("value_error", ValueError("nope")),
            # Classification-gap pins (current intended behavior): a server-side
            # statement cancel and a bare InterfaceError with no transport marker
            # are NOT treated as worker-drops — they propagate rather than retry.
            ("query_canceled", psycopg.errors.QueryCanceled("canceling statement due to user request")),
            ("bare_interface_error", psycopg.InterfaceError("the connection is closed")),
        ]
    )
    def test_non_connection_errors_are_not_dropped(self, _label, exc):
        assert _connection_dropped(exc) is False


class TestConnectDuckgres:
    """_connect_duckgres pins the session to UTC so ranged DELETEs align with the UTC day
    the export wrote, but never fails a connection if the server can't set it."""

    @patch("posthog.dags.events_backfill_to_duckling.make_duckgres_conninfo", return_value="conninfo")
    @patch("posthog.dags.events_backfill_to_duckling.psycopg.connect")
    def test_sets_utc_timezone_on_connect(self, mock_connect, _conninfo):
        conn = MagicMock()
        mock_connect.return_value = conn

        result = _connect_duckgres(DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="r"))

        assert result is conn
        conn.execute.assert_called_once_with("SET TimeZone='UTC'")

    @patch("posthog.dags.events_backfill_to_duckling.make_duckgres_conninfo", return_value="conninfo")
    @patch("posthog.dags.events_backfill_to_duckling.psycopg.connect")
    def test_timezone_set_failure_does_not_break_connection(self, mock_connect, _conninfo):
        conn = MagicMock()
        conn.execute.side_effect = Exception("unknown setting TimeZone")
        mock_connect.return_value = conn

        # Swallowed: the connection is still returned, not dropped.
        result = _connect_duckgres(DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="r"))
        assert result is conn


class TestDuckgresSessionRetry:
    """_DuckgresSession reconnects to a fresh worker on a mid-statement connection
    drop and replays the (idempotent) op, giving up only after MAX_ATTEMPTS.
    """

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckgres")
    def test_success_runs_once_without_reconnect(self, mock_connect, _sleep):
        mock_connect.return_value = MagicMock()
        session = _DuckgresSession(MagicMock(), MagicMock())
        op = MagicMock(return_value="ok")

        assert session.run("op", op) == "ok"
        assert op.call_count == 1
        assert mock_connect.call_count == 1  # only the initial connect

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckgres")
    def test_reconnects_then_succeeds(self, mock_connect, _sleep):
        mock_connect.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        session = _DuckgresSession(MagicMock(), MagicMock())
        op = MagicMock(
            side_effect=[
                psycopg.OperationalError("server closed the connection unexpectedly"),
                psycopg.InternalError("connection reset by peer"),
                "ok",
            ]
        )

        assert session.run("op", op) == "ok"
        assert op.call_count == 3
        assert mock_connect.call_count == 3  # 1 initial + 2 reconnects

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckgres")
    def test_gives_up_and_reraises_after_max_attempts(self, mock_connect, _sleep):
        mock_connect.return_value = MagicMock()
        session = _DuckgresSession(MagicMock(), MagicMock())
        op = MagicMock(side_effect=psycopg.OperationalError("connection to server was lost"))

        with pytest.raises(psycopg.OperationalError):
            session.run("op", op)
        assert op.call_count == _DuckgresSession.MAX_ATTEMPTS
        # initial connect + (MAX_ATTEMPTS - 1) reconnects; the last attempt does not reconnect
        assert mock_connect.call_count == _DuckgresSession.MAX_ATTEMPTS

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckgres")
    def test_non_connection_error_propagates_immediately(self, mock_connect, _sleep):
        mock_connect.return_value = MagicMock()
        session = _DuckgresSession(MagicMock(), MagicMock())
        op = MagicMock(side_effect=psycopg.InternalError("Constraint Error: duplicate key value"))

        with pytest.raises(psycopg.InternalError):
            session.run("op", op)
        assert op.call_count == 1
        assert mock_connect.call_count == 1  # no reconnect on a real SQL error

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckgres")
    def test_replay_runs_against_fresh_connection(self, mock_connect, _sleep):
        # The whole point of the fix: each replay must execute against the NEW
        # worker connection, not the dead one, and the prior connection must be
        # closed on reconnect.
        conn0, conn1, conn2 = MagicMock(name="conn0"), MagicMock(name="conn1"), MagicMock(name="conn2")
        mock_connect.side_effect = [conn0, conn1, conn2]
        session = _DuckgresSession(MagicMock(), MagicMock())

        seen_conns = []

        def op(conn):
            seen_conns.append(conn)
            if len(seen_conns) < 3:
                raise psycopg.InternalError("connection reset by peer")
            return "ok"

        assert session.run("op", op) == "ok"
        # attempt 1 → conn0 (initial), attempt 2 → conn1 (reconnect), attempt 3 → conn2
        assert seen_conns == [conn0, conn1, conn2]
        # _reconnect closes the prior (dead) connection before acquiring a fresh one
        conn0.close.assert_called_once()
        conn1.close.assert_called_once()


class TestDuckgresBackfillOptions:
    """_duckgres_backfill_options() builds the libpq startup `options` string that
    sizes/schedules the duckgres worker; it must request a small colocated worker
    when enabled and never emit a statement_timeout (removed on purpose).
    """

    def test_enabled_requests_small_colocated_worker(self):
        with patch("posthog.dags.events_backfill_to_duckling.DUCKGRES_WORKER_PROFILE_ENABLED", True):
            assert (
                _duckgres_backfill_options()
                == "-c duckgres.colocate=true -c duckgres.worker_cpu=4 -c duckgres.worker_memory=16Gi"
            )

    def test_disabled_returns_empty_string(self):
        # Disabled → no startup options → falls back to the default exclusive worker.
        with patch("posthog.dags.events_backfill_to_duckling.DUCKGRES_WORKER_PROFILE_ENABLED", False):
            assert _duckgres_backfill_options() == ""

    @parameterized.expand([("enabled", True), ("disabled", False)])
    def test_never_sets_statement_timeout(self, _label, enabled):
        # The 5-minute statement_timeout was removed deliberately; it must never
        # reappear in the options on either path (long OLAP backfills are the point).
        with patch("posthog.dags.events_backfill_to_duckling.DUCKGRES_WORKER_PROFILE_ENABLED", enabled):
            assert "statement_timeout" not in _duckgres_backfill_options()


def _mock_glob_conn(glob_files):
    """A psycopg-shaped mock whose glob() returns the given files."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = [(f,) for f in glob_files]
    conn.cursor.return_value.__enter__.return_value = cur
    conn.cursor.return_value.__exit__.return_value = False
    return conn, cur


def _registered_call_strings(conn):
    """Render each ducklake_add_data_files CALL to its final SQL string."""
    return [call.args[0].as_string() for call in conn.execute.call_args_list]


class TestComputeFanout:
    """Fan-out is sized to each export's actual volume, not fixed."""

    @parameterized.expand(
        [
            ("empty", 0, 1_000_000, 256, 1),
            ("tiny", 5, 1_000_000, 256, 1),
            ("exactly_target", 1_000_000, 1_000_000, 256, 1),
            ("just_over_target", 1_000_001, 1_000_000, 256, 2),
            ("big_team_day", 72_000_000, 1_000_000, 256, 72),
            ("clamped_to_max", 10_000_000_000, 1_000_000, 256, 256),
            ("smaller_target_more_files", 10_000_000, 500_000, 256, 20),
            # Fail closed on non-positive (user-tunable) config — must not divide-by-zero.
            ("zero_target", 10_000_000, 0, 256, 1),
            ("negative_target", 10_000_000, -1, 256, 1),
            ("zero_max_fanout", 10_000_000, 1_000_000, 0, 1),
            ("negative_max_fanout", 10_000_000, 1_000_000, -5, 1),
        ]
    )
    def test_fanout(self, _label, row_count, target_rows, max_fanout, expected):
        assert _compute_fanout(row_count, target_rows, max_fanout) == expected

    def test_negative_row_count_is_single_file(self):
        assert _compute_fanout(-1, TARGET_ROWS_PER_FILE, MAX_S3_FILE_FANOUT) == 1


class TestExportClickhouseRetries:
    """Both ClickHouse calls on the export path — the row-count estimate and the export
    itself — must retry transient failures. (Guards against the @retry decorator drifting
    onto the pure _compute_fanout arithmetic, which can never raise.)"""

    @patch("tenacity.nap.time.sleep")
    def test_row_count_estimate_retries_then_succeeds(self, _sleep):
        client = MagicMock()
        client.execute.side_effect = [TimeoutError("transient"), [(123,)]]

        assert _estimate_export_row_count(client, "SELECT count() FROM events", {}) == 123
        assert client.execute.call_count == 2

    @patch("tenacity.nap.time.sleep")
    def test_export_retries_then_succeeds(self, _sleep):
        client = MagicMock()
        client.execute.side_effect = [TimeoutError("transient"), None]

        _execute_export_with_retry(client, "INSERT INTO FUNCTION s3(...)", {}, "info")
        assert client.execute.call_count == 2

    def test_compute_fanout_is_pure(self):
        # No client, no I/O — proves the decorator isn't (re)attached to the arithmetic.
        assert _compute_fanout(10_000_000, 1_000_000, 256) == 10


class TestExportFanOut:
    """The exports must size the fan-out to the team-day's row count, partition via
    PARTITION BY, and return a run-scoped glob that registration can enumerate."""

    @pytest.fixture
    def target(self):
        return DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")

    def _run_export(self, export_fn, target, row_count, config=None, **kwargs):
        """Run an export with a stubbed count() result; return (insert_sql, glob, client)."""
        client = MagicMock()
        # First execute is the count() estimate, second is the INSERT.
        client.execute.side_effect = [[(row_count,)], None]
        config = config or DucklingBackfillConfig(dry_run=False, skip_ducklake_registration=True)
        s3_glob = export_fn(
            context=MagicMock(),
            client=client,
            config=config,
            target=target,
            settings={},
            run_id="run1",
            **kwargs,
        )
        calls = [c.args[0] for c in client.execute.call_args_list]
        insert_sql = next(sql for sql in calls if "INSERT INTO FUNCTION" in sql)
        count_sql = next(sql for sql in calls if "count()" in sql)
        return insert_sql, count_sql, s3_glob, client

    def test_events_export_sizes_fanout_to_row_count(self, target):
        # 10M rows at the 1M-row default target → 10 files.
        insert_sql, count_sql, s3_glob, _ = self._run_export(
            export_events_to_duckling_s3, target, row_count=10_000_000, team_id=2, date=datetime(2026, 6, 17)
        )
        assert "PARTITION BY toString(cityHash64(distinct_id) % 10)" in insert_sql
        # Count is filtered to exactly the team-day being exported.
        assert "count()" in count_sql and "team_id = 2 AND toDate(timestamp) = '2026-06-17'" in count_sql
        # The S3 destination carries the {_partition_id} placeholder ClickHouse substitutes per bucket.
        assert "year=2026/month=06/day=17/run1_{_partition_id}.parquet" in insert_sql
        assert s3_glob == "s3://bkt/backfill/events/2/year=2026/month=06/day=17/run1_*.parquet"

    def test_tiny_events_day_is_single_file(self, target):
        insert_sql, _count_sql, _glob, _ = self._run_export(
            export_events_to_duckling_s3, target, row_count=42, team_id=2, date=datetime(2026, 6, 17)
        )
        # A handful of rows collapses to one bucket → one file.
        assert "PARTITION BY toString(cityHash64(distinct_id) % 1)" in insert_sql

    def test_huge_events_day_clamps_to_max_fanout(self, target):
        insert_sql, _count_sql, _glob, _ = self._run_export(
            export_events_to_duckling_s3, target, row_count=10_000_000_000, team_id=2, date=datetime(2026, 6, 17)
        )
        assert f"PARTITION BY toString(cityHash64(distinct_id) % {MAX_S3_FILE_FANOUT})" in insert_sql

    def test_config_can_tune_target_and_max(self, target):
        config = DucklingBackfillConfig(
            dry_run=False, skip_ducklake_registration=True, target_rows_per_file=2_000_000, max_s3_file_fanout=8
        )
        insert_sql, _count_sql, _glob, _ = self._run_export(
            export_events_to_duckling_s3,
            target,
            row_count=10_000_000,
            config=config,
            team_id=2,
            date=datetime(2026, 6, 17),
        )
        # 10M / 2M = 5 files (under the lowered cap of 8).
        assert "PARTITION BY toString(cityHash64(distinct_id) % 5)" in insert_sql

    def test_persons_daily_export_sizes_fanout_and_returns_glob(self, target):
        insert_sql, count_sql, s3_glob, _ = self._run_export(
            export_persons_to_duckling_s3, target, row_count=3_000_000, team_id=2, date=datetime(2026, 6, 17)
        )
        assert "PARTITION BY toString(cityHash64(pd.distinct_id) % 3)" in insert_sql
        # Pin the full predicate: dropping is_deleted/date would silently over-size the fan-out.
        assert "FROM person WHERE team_id = 2 AND toDate(_timestamp) = '2026-06-17' AND is_deleted = 0" in count_sql
        assert s3_glob == "s3://bkt/backfill/persons/2/year=2026/month=06/run1_*.parquet"

    def test_persons_full_export_sizes_fanout_and_returns_glob(self, target):
        insert_sql, count_sql, s3_glob, _ = self._run_export(
            export_persons_full_to_duckling_s3, target, row_count=5_000_000, team_id=2
        )
        assert "PARTITION BY toString(cityHash64(pd.distinct_id) % 5)" in insert_sql
        assert "FROM person_distinct_id2 WHERE team_id = 2 AND is_deleted = 0" in count_sql
        assert s3_glob == "s3://bkt/backfill/persons/2/year=0/month=0/run1_*.parquet"

    @parameterized.expand(
        [
            ("events", export_events_to_duckling_s3, {"team_id": 2, "date": datetime(2026, 6, 17)}),
            ("persons", export_persons_to_duckling_s3, {"team_id": 2, "date": datetime(2026, 6, 17)}),
            ("persons_full", export_persons_full_to_duckling_s3, {"team_id": 2}),
        ]
    )
    def test_dry_run_does_not_touch_clickhouse(self, _label, export_fn, kwargs):
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        client = MagicMock()
        config = DucklingBackfillConfig(dry_run=True)
        result = export_fn(
            context=MagicMock(), client=client, config=config, target=target, settings={}, run_id="run1", **kwargs
        )
        assert result is None
        # No count, no insert — dry run must not hit the cluster at all.
        client.execute.assert_not_called()


class TestRegisterFilesWithDuckling:
    """Registration must enumerate every file a run produced and register each
    exactly once, while tolerating an empty fan-out."""

    @pytest.fixture
    def target(self):
        return DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")

    @parameterized.expand(
        [
            ("events", register_files_with_duckling, "events"),
            ("persons", register_persons_files_with_duckling, "persons"),
        ]
    )
    def test_registers_every_globbed_file_once(self, _label, register_fn, table, target=None):
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        files = [f"s3://bkt/backfill/{table}/2/year=2026/month=06/day=17/run1_{i}.parquet" for i in range(3)]
        conn, _cur = _mock_glob_conn(files)
        config = DucklingBackfillConfig()

        count = register_fn(MagicMock(), target, "s3://bkt/.../run1_*.parquet", config, conn)

        assert count == 3
        # One ducklake_add_data_files CALL per file, exactly once, for exactly these files.
        assert conn.execute.call_count == 3
        calls = _registered_call_strings(conn)
        assert all("ducklake_add_data_files" in c for c in calls)
        # allow_missing => true must be on every CALL — it's what lets the backfill
        # tolerate columns the live ingestion path added to the duckling table via
        # schema evolution but the backfill export doesn't carry.
        assert all("allow_missing => true" in c for c in calls)
        assert all(f"'{path}'" in calls[i] for i, path in enumerate(files))

    @parameterized.expand(
        [
            ("events", register_files_with_duckling),
            ("persons", register_persons_files_with_duckling),
        ]
    )
    def test_empty_glob_registers_nothing(self, _label, register_fn):
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        conn, _cur = _mock_glob_conn([])
        config = DucklingBackfillConfig()

        count = register_fn(MagicMock(), target, "s3://bkt/.../run1_*.parquet", config, conn)

        assert count == 0
        conn.execute.assert_not_called()

    @parameterized.expand(
        [
            ("skip_registration", {"skip_ducklake_registration": True}),
            ("dry_run", {"dry_run": True}),
        ]
    )
    def test_disabled_paths_register_nothing(self, _label, config_kwargs):
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        conn, _cur = _mock_glob_conn(["s3://bkt/a/run1_0.parquet"])
        config = DucklingBackfillConfig(**config_kwargs)

        count = register_files_with_duckling(MagicMock(), target, "s3://bkt/.../run1_*.parquet", config, conn)

        assert count == 0
        conn.execute.assert_not_called()  # never even globs

    def test_glob_run_files_uses_parameterized_glob(self, target):
        conn, cur = _mock_glob_conn(["s3://bkt/x/run1_0.parquet", "s3://bkt/x/run1_1.parquet"])

        files = _glob_run_files(conn, "s3://bkt/x/run1_*.parquet")

        assert files == ["s3://bkt/x/run1_0.parquet", "s3://bkt/x/run1_1.parquet"]
        sql, params = cur.execute.call_args.args
        assert "glob(%s)" in sql
        assert params == ("s3://bkt/x/run1_*.parquet",)


# Column SELECT used to synthesize events Parquet files for the round-trip test.
def _events_rows_select(n_rows, uuid_prefix, ts):
    return f"""
        SELECT
            ('{uuid_prefix}-' || i)::VARCHAR AS uuid,
            '$pageview'::VARCHAR AS event,
            '{{}}'::VARCHAR AS properties,
            '{ts}'::TIMESTAMPTZ AS timestamp,
            2::BIGINT AS team_id,
            2::BIGINT AS project_id,
            ('user-' || i)::VARCHAR AS distinct_id,
            ''::VARCHAR AS elements_chain,
            '{ts}'::TIMESTAMPTZ AS created_at,
            ('person-' || i)::VARCHAR AS person_id,
            '{ts}'::TIMESTAMPTZ AS person_created_at,
            '{{}}'::VARCHAR AS person_properties,
            '{{}}'::VARCHAR AS group0_properties,
            '{{}}'::VARCHAR AS group1_properties,
            '{{}}'::VARCHAR AS group2_properties,
            '{{}}'::VARCHAR AS group3_properties,
            '{{}}'::VARCHAR AS group4_properties,
            '{ts}'::TIMESTAMPTZ AS group0_created_at,
            '{ts}'::TIMESTAMPTZ AS group1_created_at,
            '{ts}'::TIMESTAMPTZ AS group2_created_at,
            '{ts}'::TIMESTAMPTZ AS group3_created_at,
            '{ts}'::TIMESTAMPTZ AS group4_created_at,
            'full'::VARCHAR AS person_mode,
            false::BOOLEAN AS historical_migration,
            '{ts}'::TIMESTAMPTZ AS _inserted_at
        FROM range({n_rows}) AS t(i)
    """


class _DuckdbPsycopgAdapter:
    """Adapts a raw duckdb connection to the slice of the psycopg API the production
    duckgres helpers use (`conn.cursor()` context manager, `cur.execute(sql, params)`,
    `cur.fetchall()`, `cur.rowcount`, and `conn.execute(psql.Composed)`), so the REAL
    register_files_with_duckling / _glob_run_files / delete_events_partition_data run
    against a local DuckLake catalog instead of being re-implemented in the test."""

    def __init__(self, duck: Any):
        self._duck = duck
        self._result: Any = None

    # The production code uses one connection as both connection and cursor; in this
    # single-threaded test we can be both.
    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        # register_*_files passes a psql.Composed (render it); _glob_run_files /
        # delete_* pass a %s-parameterized string (translate to duckdb's ? binding).
        sql = query.as_string() if hasattr(query, "as_string") else query.replace("%s", "?")
        self._result = self._duck.execute(sql, list(params)) if params else self._duck.execute(sql)
        return self

    def fetchall(self):
        return self._result.fetchall()

    @property
    def rowcount(self):
        return -1  # production treats -1 as unknown → 0; the test asserts via SELECT count(*)


class TestFannedOutLayoutRoundTrip:
    """End-to-end against a real DuckLake catalog, driving the PRODUCTION registration and
    delete helpers (via _DuckdbPsycopgAdapter): a fanned-out team-day registers as many
    files whose rows all become queryable, and a re-run with a different fan-out re-registers
    cleanly via DELETE-before-register without duplicating or counting orphans."""

    @pytest.fixture
    def lake(self, tmp_path):
        catalog_path = str(tmp_path / "test.ducklake")
        data_path = str(tmp_path / "data")
        os.makedirs(data_path)

        conn = duckdb.connect()
        conn.execute("INSTALL ducklake")
        conn.execute("LOAD ducklake")
        # Attach under the production alias so register_files_with_duckling (which uses
        # DUCKLAKE_ALIAS internally) targets this catalog.
        conn.execute(f"ATTACH 'ducklake:{catalog_path}' AS {DUCKLAKE_ALIAS} (DATA_PATH '{data_path}')")
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {DUCKLAKE_ALIAS}.posthog")
        conn.execute(EVENTS_TABLE_DDL.format(catalog=DUCKLAKE_ALIAS))
        conn.execute(
            f"ALTER TABLE {DUCKLAKE_ALIAS}.posthog.events "
            "SET PARTITIONED BY (year(timestamp), month(timestamp), day(timestamp))"
        )
        yield conn, str(tmp_path)
        conn.close()

    def _write_fanned_out_day(self, conn, root, run_id, n_files, rows_per_file):
        """Write n_files Parquet files into the day= dir, mirroring PARTITION BY output."""
        day_dir = os.path.join(root, "events", "2", "year=2026", "month=06", "day=17")
        os.makedirs(day_dir, exist_ok=True)
        for bucket in range(n_files):
            path = os.path.join(day_dir, f"{run_id}_{bucket}.parquet")
            conn.execute(
                f"COPY ({_events_rows_select(rows_per_file, f'{run_id}-{bucket}', '2026-06-17 12:00:00+00')}) "
                f"TO '{path}' (FORMAT PARQUET)"
            )
        return os.path.join(day_dir, f"{run_id}_*.parquet")

    def _count(self, conn):
        return conn.execute(f"SELECT count(*) FROM {DUCKLAKE_ALIAS}.posthog.events").fetchone()[0]

    def _register(self, conn, file_glob):
        """Drive the PRODUCTION register_files_with_duckling against the real catalog."""
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        config = DucklingBackfillConfig()
        # The adapter duck-types the psycopg.Connection slice these helpers use.
        adapter = cast("psycopg.Connection[Any]", _DuckdbPsycopgAdapter(conn))
        return register_files_with_duckling(MagicMock(), target, file_glob, config, adapter)

    def _delete_day(self, conn):
        """Drive the PRODUCTION ranged DELETE against the real catalog."""
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        adapter = cast("psycopg.Connection[Any]", _DuckdbPsycopgAdapter(conn))
        delete_events_partition_data(MagicMock(), target, 2, datetime(2026, 6, 17), conn=adapter)

    def test_many_files_register_and_all_rows_queryable(self, lake):
        conn, root = lake
        file_glob = self._write_fanned_out_day(conn, root, "run1", n_files=4, rows_per_file=10)

        registered = self._register(conn, file_glob)

        assert registered == 4  # one INSERT produced many files, all registered exactly once
        assert self._count(conn) == 40

    def test_rerun_does_not_duplicate_or_count_orphans(self, lake):
        conn, root = lake

        # First run: 4 files, 40 rows.
        glob1 = self._write_fanned_out_day(conn, root, "run1", n_files=4, rows_per_file=10)
        self._delete_day(conn)
        assert self._register(conn, glob1) == 4
        assert self._count(conn) == 40

        # Re-run with a NEW run_id AND a different fan-out (3 vs 4) writes a fresh file set.
        # The prior run's files stay on disk as orphans (different run_id prefix).
        glob2 = self._write_fanned_out_day(conn, root, "run2", n_files=3, rows_per_file=10)

        # DELETE-before-register clears the day's catalog rows, then we register only
        # this run's files (run-scoped glob never sees run1's orphans).
        self._delete_day(conn)
        assert self._register(conn, glob2) == 3

        # Exactly the re-run's rows — no duplication, orphaned run1 files not counted.
        assert self._count(conn) == 30

    def test_allow_missing_handles_schema_evolution(self, lake):
        """When the duckling table has a column the backfill export doesn't (schema
        evolution from the live ingestion path), allow_missing => true lets
        registration succeed with NULL fill. Without the flag, the same file is
        rejected — proving the flag is load-bearing, not decorative."""
        conn, root = lake

        # Simulate the live ingestion path adding a column the backfill doesn't export.
        conn.execute(f"ALTER TABLE {DUCKLAKE_ALIAS}.posthog.events ADD COLUMN captured_at TIMESTAMPTZ")

        # Write a fanned-out day WITHOUT captured_at — exactly what the backfill exports.
        file_glob = self._write_fanned_out_day(conn, root, "run1", n_files=1, rows_per_file=5)
        single_file = file_glob.replace("_*.parquet", "_0.parquet")

        # Negative control: without allow_missing, the same file is rejected with the
        # same class of error that broke the prod backfill.
        with pytest.raises(duckdb.Error, match="captured_at"):
            conn.execute(
                f"CALL ducklake_add_data_files('{DUCKLAKE_ALIAS}', 'events', '{single_file}', schema => 'posthog')"
            )

        # The fix: register_files_with_duckling passes allow_missing => true.
        self._delete_day(conn)
        assert self._register(conn, file_glob) == 1
        assert self._count(conn) == 5

        # The missing column is NULL-filled for every backfilled row.
        cap_vals = [r[0] for r in conn.execute(f"SELECT captured_at FROM {DUCKLAKE_ALIAS}.posthog.events").fetchall()]
        assert cap_vals == [None] * 5
