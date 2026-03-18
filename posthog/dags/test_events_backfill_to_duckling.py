from datetime import date, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

import duckdb
from parameterized import parameterized

from posthog.dags.events_backfill_to_duckling import (
    EARLIEST_BACKFILL_DATE,
    EVENTS_COLUMNS,
    EVENTS_TABLE_DDL,
    EXPECTED_DUCKLAKE_COLUMNS,
    EXPECTED_DUCKLAKE_PERSONS_COLUMNS,
    MAX_RETRY_ATTEMPTS,
    PERSONS_COLUMNS,
    PERSONS_TABLE_DDL,
    _connect_duckdb,
    _get_cluster,
    _is_transaction_conflict,
    _set_table_partitioning,
    _validate_identifier,
    delete_events_partition_data,
    delete_persons_partition_data,
    duckling_events_full_backfill_sensor,
    get_months_in_range,
    get_s3_url_for_clickhouse,
    is_full_export_partition,
    parse_partition_key,
    parse_partition_key_dates,
    table_exists,
)


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
            ("bucket", "us-east-1", "path/file.parquet", "https://bucket.s3.us-east-1.amazonaws.com/path/file.parquet"),
            (
                "my-bucket",
                "eu-west-1",
                "a/b/c.parquet",
                "https://my-bucket.s3.eu-west-1.amazonaws.com/a/b/c.parquet",
            ),
            (
                "duckling-bucket",
                "us-west-2",
                "backfill/events/team_id=123/year=2024/month=01/day=15/abc.parquet",
                "https://duckling-bucket.s3.us-west-2.amazonaws.com/backfill/events/team_id=123/year=2024/month=01/day=15/abc.parquet",
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
    def test_returns_true_when_table_exists(self):
        conn = duckdb.connect()
        conn.execute("CREATE TABLE test_table (id INTEGER)")
        assert table_exists(conn, "memory", "main", "test_table") is True
        conn.close()

    def test_returns_false_when_table_does_not_exist(self):
        conn = duckdb.connect()
        assert table_exists(conn, "memory", "main", "nonexistent_table") is False
        conn.close()

    def test_rejects_invalid_catalog_alias(self):
        conn = duckdb.connect()
        with pytest.raises(ValueError) as exc_info:
            table_exists(conn, "invalid;injection", "main", "test")
        assert "Invalid SQL identifier" in str(exc_info.value)
        conn.close()

    def test_rejects_invalid_schema(self):
        conn = duckdb.connect()
        with pytest.raises(ValueError) as exc_info:
            table_exists(conn, "memory", "DROP TABLE", "test")
        assert "Invalid SQL identifier" in str(exc_info.value)
        conn.close()

    def test_rejects_invalid_table(self):
        conn = duckdb.connect()
        with pytest.raises(ValueError) as exc_info:
            table_exists(conn, "memory", "main", "test'; DROP TABLE users;--")
        assert "Invalid SQL identifier" in str(exc_info.value)
        conn.close()


class TestEventsDDL:
    def test_events_ddl_is_valid_sql(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        ddl = EVENTS_TABLE_DDL.format(catalog="memory")
        conn.execute(ddl)

        # Verify table was created with expected columns
        result = conn.execute("DESCRIBE memory.posthog.events").fetchall()
        column_names = {row[0] for row in result}

        assert column_names == EXPECTED_DUCKLAKE_COLUMNS
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
            (date(2023, 11, 1), date(2024, 2, 15), ["2023-11", "2023-12", "2024-01", "2024-02"]),
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
    def test_partitioning_is_idempotent_in_ducklake(self):
        """Verify that SET PARTITIONED BY can be called multiple times safely."""
        conn = duckdb.connect()
        conn.execute("INSTALL ducklake; LOAD ducklake;")
        conn.execute("ATTACH ':memory:' AS test_catalog (TYPE DUCKLAKE, DATA_PATH ':memory:')")
        conn.execute("CREATE SCHEMA test_catalog.posthog")
        conn.execute("CREATE TABLE test_catalog.posthog.events (timestamp TIMESTAMP, event VARCHAR)")

        mock_context = MagicMock()

        # First call should succeed
        result1 = _set_table_partitioning(
            conn, "test_catalog", "events", "year(timestamp), month(timestamp)", mock_context, team_id=123
        )
        assert result1 is True

        # Second call with same keys should also succeed (idempotent)
        result2 = _set_table_partitioning(
            conn, "test_catalog", "events", "year(timestamp), month(timestamp)", mock_context, team_id=123
        )
        assert result2 is True

        # Third call should also succeed
        result3 = _set_table_partitioning(
            conn, "test_catalog", "events", "year(timestamp), month(timestamp)", mock_context, team_id=123
        )
        assert result3 is True

        conn.close()

    def test_partitioning_logs_success(self):
        """Verify that successful partitioning logs appropriately."""
        conn = duckdb.connect()
        conn.execute("INSTALL ducklake; LOAD ducklake;")
        conn.execute("ATTACH ':memory:' AS test_catalog (TYPE DUCKLAKE, DATA_PATH ':memory:')")
        conn.execute("CREATE SCHEMA test_catalog.posthog")
        conn.execute("CREATE TABLE test_catalog.posthog.events (timestamp TIMESTAMP, event VARCHAR)")

        mock_context = MagicMock()

        result = _set_table_partitioning(
            conn, "test_catalog", "events", "year(timestamp), month(timestamp)", mock_context, team_id=123
        )

        assert result is True
        mock_context.log.info.assert_any_call("Setting partitioning on events table...")
        mock_context.log.info.assert_any_call("Successfully set partitioning on events table")
        conn.close()

    def test_partitioning_handles_failure_gracefully(self):
        """Verify that partitioning failures return False and log warning."""
        conn = duckdb.connect()
        # Don't load ducklake - table won't support SET PARTITIONED BY
        conn.execute("CREATE SCHEMA posthog")
        conn.execute("CREATE TABLE posthog.events (timestamp TIMESTAMP, event VARCHAR)")

        mock_context = MagicMock()

        # This should fail because regular DuckDB tables don't support SET PARTITIONED BY
        result = _set_table_partitioning(
            conn, "memory", "events", "year(timestamp), month(timestamp)", mock_context, team_id=123
        )

        assert result is False
        mock_context.log.warning.assert_called()
        conn.close()

    def test_partitioning_rejects_invalid_identifiers(self):
        """Verify that SQL injection attempts are blocked."""
        conn = duckdb.connect()
        mock_context = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            _set_table_partitioning(conn, "test; DROP TABLE", "events", "year(timestamp)", mock_context, team_id=123)
        assert "Invalid SQL identifier" in str(exc_info.value)

        with pytest.raises(ValueError) as exc_info:
            _set_table_partitioning(conn, "test_catalog", "events'; --", "year(timestamp)", mock_context, team_id=123)
        assert "Invalid SQL identifier" in str(exc_info.value)

        conn.close()


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
            ("12345-2024-01", False),  # Invalid format with hyphen instead of underscore
            ("abc", False),  # Non-numeric
            ("", False),  # Empty string
        ]
    )
    def test_detects_partition_format(self, key, expected):
        assert is_full_export_partition(key) == expected


class TestConnectDuckdb:
    def test_sets_memory_limit(self):
        conn = _connect_duckdb()
        try:
            result = conn.execute("SELECT current_setting('memory_limit')").fetchone()
            assert result is not None
            # DuckDB reports memory in its own format; verify it's not the default (~80% of RAM)
            # 4GB is reported as "3.7 GiB" by DuckDB
            assert "GiB" in result[0] or "GB" in result[0]
            # Parse the numeric value and verify it's approximately 4GB
            numeric = float(result[0].split()[0])
            assert 3.5 <= numeric <= 4.5
        finally:
            conn.close()

    def test_sets_temp_directory(self):
        conn = _connect_duckdb()
        try:
            result = conn.execute("SELECT current_setting('temp_directory')").fetchone()
            assert result is not None
            assert result[0] == "/tmp/duckdb_temp"
        finally:
            conn.close()


class TestDeleteRangePredicate:
    @parameterized.expand(
        [
            # (timestamps_to_insert, target_date, expected_deleted, expected_remaining)
            (
                ["2024-01-15 00:00:00", "2024-01-15 12:30:00", "2024-01-15 23:59:59.999999"],
                "2024-01-15",
                3,
                0,
            ),
            (
                ["2024-01-14 23:59:59.999999", "2024-01-15 00:00:00", "2024-01-16 00:00:00"],
                "2024-01-15",
                1,
                2,
            ),
            (
                ["2024-02-29 00:00:00", "2024-02-29 23:59:59.999999", "2024-03-01 00:00:00"],
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


class TestIsTransactionConflict:
    @parameterized.expand(
        [
            (duckdb.TransactionException("Transaction conflict: write-write"), True),
            (duckdb.TransactionException("Transaction conflict on table"), True),
            (duckdb.TransactionException("Some other transaction error"), False),
            (duckdb.CatalogException("Table not found"), False),
            (RuntimeError("Transaction conflict"), False),
        ]
    )
    def test_identifies_conflicts(self, exc, expected):
        assert _is_transaction_conflict(exc) == expected


class TestDeleteEventsRetry:
    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling.attach_catalog")
    @patch("posthog.dags.events_backfill_to_duckling.configure_cross_account_connection")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckdb")
    @patch("posthog.dags.events_backfill_to_duckling.get_team_config")
    def test_retries_on_transaction_conflict(self, mock_config, mock_connect, mock_cross, mock_attach, mock_sleep):
        mock_config.return_value = {}
        mock_catalog = MagicMock()
        mock_catalog.team_id = 1
        mock_catalog.to_cross_account_destination.return_value = MagicMock()
        mock_context = MagicMock()

        conflict_conn = MagicMock()
        conflict_conn.execute.side_effect = duckdb.TransactionException("Transaction conflict: write-write")
        success_conn = MagicMock()
        success_conn.execute.return_value.fetchone.return_value = (5,)
        mock_connect.side_effect = [conflict_conn, success_conn]

        result = delete_events_partition_data(mock_context, mock_catalog, 1, datetime(2024, 1, 15))

        assert result == 5
        assert mock_connect.call_count == 2
        mock_sleep.assert_called_once_with(4)
        conflict_conn.close.assert_called_once()
        success_conn.close.assert_called_once()

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling.attach_catalog")
    @patch("posthog.dags.events_backfill_to_duckling.configure_cross_account_connection")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckdb")
    @patch("posthog.dags.events_backfill_to_duckling.get_team_config")
    def test_raises_non_conflict_exception(self, mock_config, mock_connect, mock_cross, mock_attach, mock_sleep):
        mock_config.return_value = {}
        mock_catalog = MagicMock()
        mock_catalog.team_id = 1
        mock_catalog.to_cross_account_destination.return_value = MagicMock()
        mock_context = MagicMock()

        conn = MagicMock()
        conn.execute.side_effect = RuntimeError("Connection failed")
        mock_connect.return_value = conn

        with pytest.raises(RuntimeError, match="Connection failed"):
            delete_events_partition_data(mock_context, mock_catalog, 1, datetime(2024, 1, 15))

        assert mock_connect.call_count == 1
        mock_sleep.assert_not_called()

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling.attach_catalog")
    @patch("posthog.dags.events_backfill_to_duckling.configure_cross_account_connection")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckdb")
    @patch("posthog.dags.events_backfill_to_duckling.get_team_config")
    def test_raises_after_max_retries(self, mock_config, mock_connect, mock_cross, mock_attach, mock_sleep):
        mock_config.return_value = {}
        mock_catalog = MagicMock()
        mock_catalog.team_id = 1
        mock_catalog.to_cross_account_destination.return_value = MagicMock()
        mock_context = MagicMock()

        conn = MagicMock()
        conn.execute.side_effect = duckdb.TransactionException("Transaction conflict: write-write")
        mock_connect.return_value = conn

        with pytest.raises(duckdb.TransactionException, match="Transaction conflict"):
            delete_events_partition_data(mock_context, mock_catalog, 1, datetime(2024, 1, 15))

        assert mock_connect.call_count == MAX_RETRY_ATTEMPTS
        assert mock_sleep.call_count == MAX_RETRY_ATTEMPTS - 1

    @patch("posthog.dags.events_backfill_to_duckling.attach_catalog")
    @patch("posthog.dags.events_backfill_to_duckling.configure_cross_account_connection")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckdb")
    @patch("posthog.dags.events_backfill_to_duckling.get_team_config")
    def test_returns_zero_on_catalog_exception(self, mock_config, mock_connect, mock_cross, mock_attach):
        mock_config.return_value = {}
        mock_catalog = MagicMock()
        mock_catalog.team_id = 1
        mock_catalog.to_cross_account_destination.return_value = MagicMock()
        mock_context = MagicMock()

        conn = MagicMock()
        conn.execute.side_effect = duckdb.CatalogException("Table does not exist")
        mock_connect.return_value = conn

        result = delete_events_partition_data(mock_context, mock_catalog, 1, datetime(2024, 1, 15))
        assert result == 0


class TestDeletePersonsRetry:
    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling.attach_catalog")
    @patch("posthog.dags.events_backfill_to_duckling.configure_cross_account_connection")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckdb")
    @patch("posthog.dags.events_backfill_to_duckling.get_team_config")
    def test_retries_on_transaction_conflict(self, mock_config, mock_connect, mock_cross, mock_attach, mock_sleep):
        mock_config.return_value = {}
        mock_catalog = MagicMock()
        mock_catalog.team_id = 1
        mock_catalog.to_cross_account_destination.return_value = MagicMock()
        mock_context = MagicMock()

        conflict_conn = MagicMock()
        conflict_conn.execute.side_effect = duckdb.TransactionException("Transaction conflict: write-write")
        success_conn = MagicMock()
        success_conn.execute.return_value.fetchone.return_value = (3,)
        mock_connect.side_effect = [conflict_conn, success_conn]

        result = delete_persons_partition_data(mock_context, mock_catalog, 1, datetime(2024, 1, 15))

        assert result == 3
        assert mock_connect.call_count == 2
        mock_sleep.assert_called_once_with(4)

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling.attach_catalog")
    @patch("posthog.dags.events_backfill_to_duckling.configure_cross_account_connection")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckdb")
    @patch("posthog.dags.events_backfill_to_duckling.get_team_config")
    def test_retries_on_full_export_conflict(self, mock_config, mock_connect, mock_cross, mock_attach, mock_sleep):
        mock_config.return_value = {}
        mock_catalog = MagicMock()
        mock_catalog.team_id = 1
        mock_catalog.to_cross_account_destination.return_value = MagicMock()
        mock_context = MagicMock()

        conflict_conn = MagicMock()
        conflict_conn.execute.side_effect = duckdb.TransactionException("Transaction conflict: write-write")
        success_conn = MagicMock()
        success_conn.execute.return_value.fetchone.return_value = (10,)
        mock_connect.side_effect = [conflict_conn, success_conn]

        result = delete_persons_partition_data(mock_context, mock_catalog, 1, partition_date=None)

        assert result == 10
        assert mock_connect.call_count == 2
        mock_sleep.assert_called_once_with(4)

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling.attach_catalog")
    @patch("posthog.dags.events_backfill_to_duckling.configure_cross_account_connection")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckdb")
    @patch("posthog.dags.events_backfill_to_duckling.get_team_config")
    def test_exponential_backoff(self, mock_config, mock_connect, mock_cross, mock_attach, mock_sleep):
        mock_config.return_value = {}
        mock_catalog = MagicMock()
        mock_catalog.team_id = 1
        mock_catalog.to_cross_account_destination.return_value = MagicMock()
        mock_context = MagicMock()

        conflict_conn = MagicMock()
        conflict_conn.execute.side_effect = duckdb.TransactionException("Transaction conflict: write-write")
        success_conn = MagicMock()
        success_conn.execute.return_value.fetchone.return_value = (0,)
        # MAX_RETRY_ATTEMPTS=3: attempts 0,1 conflict and retry, attempt 2 succeeds
        mock_connect.side_effect = [conflict_conn, conflict_conn, success_conn]

        delete_persons_partition_data(mock_context, mock_catalog, 1, datetime(2024, 1, 15))

        # Backoff: min(4 * 2^attempt, 60) -> 4, 8
        assert mock_sleep.call_args_list == [
            ((4,),),
            ((8,),),
        ]


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
    @patch("posthog.dags.events_backfill_to_duckling.DuckLakeCatalog")
    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_earliest_date_clamped(
        self, _name, earliest_dt, expected_first_month, mock_tz, mock_catalog_cls, mock_get_earliest
    ):
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        mock_tz.now.return_value = datetime(2025, 2, 10, 12, 0, 0)
        mock_get_earliest.return_value = earliest_dt

        catalog = MagicMock()
        catalog.team_id = 1
        mock_catalog_cls.objects.all.return_value.order_by.return_value = [catalog]

        instance = DagsterInstance.ephemeral()
        context = build_sensor_context(instance=instance)
        result = duckling_events_full_backfill_sensor(context)
        assert isinstance(result, SensorResult)
        assert result.run_requests is not None

        assert len(result.run_requests) > 0
        first_key = result.run_requests[0].partition_key
        assert first_key == f"1_{expected_first_month}"

    @patch("posthog.dags.events_backfill_to_duckling.get_earliest_event_date_for_team")
    @patch("posthog.dags.events_backfill_to_duckling.DuckLakeCatalog")
    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_no_events_returns_empty(self, mock_tz, mock_catalog_cls, mock_get_earliest):
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        mock_tz.now.return_value = datetime(2025, 2, 10, 12, 0, 0)
        mock_get_earliest.return_value = None

        catalog = MagicMock()
        catalog.team_id = 1
        mock_catalog_cls.objects.all.return_value.order_by.return_value = [catalog]

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
        mock_get_cluster.side_effect = [TimeoutError("timed out"), TimeoutError("timed out"), mock_cluster]

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
