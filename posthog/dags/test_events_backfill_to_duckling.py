import os
from datetime import date, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

import duckdb
import psycopg
from parameterized import parameterized

from posthog.dags.events_backfill_to_duckling import (
    DUCKLING_BACKFILL_CONCURRENCY_TAG,
    EARLIEST_BACKFILL_DATE,
    EVENTS_COLUMNS,
    EVENTS_CONCURRENCY_TAG,
    EVENTS_TABLE_DDL,
    EXPECTED_DUCKLAKE_COLUMNS,
    EXPECTED_DUCKLAKE_PERSONS_COLUMNS,
    ICEBERG_BACKFILL_TEAM_IDS,
    ICEBERG_EVENTS_PARTITION_EXPR,
    ICEBERG_PERSONS_PARTITION_EXPR,
    ICEBERG_PERSONS_TABLE_DDL,
    PERSONS_COLUMNS,
    PERSONS_CONCURRENCY_TAG,
    PERSONS_TABLE_DDL,
    _get_cluster,
    _set_iceberg_table_partitioning,
    _set_table_partitioning,
    _validate_identifier,
    drop_iceberg_table,
    duckling_events_full_backfill_sensor,
    ensure_iceberg_table_exists,
    get_months_in_range,
    get_s3_url_for_clickhouse,
    iceberg_enabled_for_team,
    is_full_export_partition,
    parse_partition_key,
    parse_partition_key_dates,
    table_exists,
    write_partition_to_iceberg,
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


class TestIcebergDualWrite:
    @parameterized.expand([(2, True), (1, False), (12345, False), (0, False)])
    def test_iceberg_enabled_for_team(self, team_id, expected):
        assert iceberg_enabled_for_team(team_id) is expected

    def test_iceberg_backfill_team_ids_is_dogfood_only(self):
        assert ICEBERG_BACKFILL_TEAM_IDS == {2}

    def test_iceberg_persons_ddl_is_valid_sql_with_signed_version(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        conn.execute(ICEBERG_PERSONS_TABLE_DDL.format(catalog="memory"))

        result = conn.execute("DESCRIBE memory.posthog.persons").fetchall()
        column_names = {row[0] for row in result}
        types_by_name = {row[0]: row[1] for row in result}

        assert column_names == EXPECTED_DUCKLAKE_PERSONS_COLUMNS
        # Iceberg has no unsigned types — person_version must be signed BIGINT, not UBIGINT.
        assert types_by_name["person_version"] == "BIGINT"
        conn.close()

    def test_iceberg_persons_ddl_is_idempotent(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        ddl = ICEBERG_PERSONS_TABLE_DDL.format(catalog="memory")
        conn.execute(ddl)
        conn.execute(ddl)
        conn.close()

    def test_ensure_iceberg_table_returns_false_when_catalog_unavailable(self):
        # When the iceberg catalog isn't attached, CREATE SCHEMA raises — the
        # helper must swallow it and disable Iceberg for the run, not fail.
        conn = MagicMock()
        conn.execute.side_effect = Exception("Catalog with name iceberg does not exist")
        assert ensure_iceberg_table_exists(MagicMock(), conn, "events", EVENTS_TABLE_DDL) is False

    def test_ensure_iceberg_table_returns_true_on_success(self):
        conn = MagicMock()
        assert ensure_iceberg_table_exists(MagicMock(), conn, "events", EVENTS_TABLE_DDL) is True

    def test_ensure_iceberg_table_unpartitioned_without_expr(self):
        conn = MagicMock()
        ensure_iceberg_table_exists(MagicMock(), conn, "events", EVENTS_TABLE_DDL)
        executed = " ".join(str(c.args[0]) for c in conn.execute.call_args_list)
        assert "PARTITIONED BY" not in executed

    def test_ensure_iceberg_table_appends_partition_clause(self):
        conn = MagicMock()
        assert (
            ensure_iceberg_table_exists(
                MagicMock(), conn, "events", EVENTS_TABLE_DDL, partition_expr=ICEBERG_EVENTS_PARTITION_EXPR
            )
            is True
        )
        executed = " ".join(str(c.args[0]) for c in conn.execute.call_args_list)
        # Fresh tables are partitioned in the CREATE; existing tables are evolved via ALTER.
        assert f"PARTITIONED BY ({ICEBERG_EVENTS_PARTITION_EXPR})" in executed
        assert "ALTER TABLE" in executed and "SET PARTITIONED BY" in executed

    def test_iceberg_partition_exprs_are_single_temporal_transform(self):
        # Lakekeeper rejects multiple temporal transforms on one source column as
        # redundant, so each spec must be a single day()/month() transform — not
        # the multi-level year/month/day spec DuckLake uses.
        assert ICEBERG_EVENTS_PARTITION_EXPR == "day(timestamp)"
        assert ICEBERG_PERSONS_PARTITION_EXPR == "month(_timestamp)"
        for expr in (ICEBERG_EVENTS_PARTITION_EXPR, ICEBERG_PERSONS_PARTITION_EXPR):
            assert "," not in expr

    def test_set_iceberg_partitioning_treats_redundant_as_success(self):
        # Lakekeeper reports re-declaring an identical spec as "redundant"; that
        # means the table is already partitioned the way we want — not an error.
        conn = MagicMock()
        conn.execute.side_effect = Exception("Cannot add redundant partition with source id 2 and transform `time`")
        _set_iceberg_table_partitioning(MagicMock(), conn, "events", "day(timestamp)")  # must not raise

    def test_set_iceberg_partitioning_is_non_fatal(self):
        conn = MagicMock()
        conn.execute.side_effect = Exception("some other partitioning failure")
        _set_iceberg_table_partitioning(MagicMock(), conn, "events", "day(timestamp)")  # must not raise

    def test_set_iceberg_partitioning_rejects_invalid_table(self):
        with pytest.raises(ValueError) as exc_info:
            _set_iceberg_table_partitioning(MagicMock(), MagicMock(), "events; DROP", "day(timestamp)")
        assert "Invalid SQL identifier" in str(exc_info.value)

    def test_write_partition_rejects_invalid_table(self):
        with pytest.raises(ValueError) as exc_info:
            write_partition_to_iceberg(
                MagicMock(), MagicMock(), "events; DROP TABLE", "s3://b/f.parquet", 2, "timestamp", None
            )
        assert "Invalid SQL identifier" in str(exc_info.value)

    @parameterized.expand(
        [
            ("daily_partition", datetime(2024, 1, 15)),
            ("full_export_no_date", None),
        ]
    )
    def test_write_partition_is_non_fatal_on_insert_failure(self, _name, partition_date):
        # A failed Iceberg INSERT must never bubble up — DuckLake is the source
        # of truth and its backfill must complete regardless. Covers both the
        # daily partition-scoped DELETE and the full-export delete-by-team path.
        conn = MagicMock()
        conn.execute.side_effect = Exception("iceberg insert blew up")
        result = write_partition_to_iceberg(
            MagicMock(), conn, "events", "s3://b/f.parquet", 2, "timestamp", partition_date
        )
        assert result is False

    def test_drop_iceberg_table_rejects_invalid_table(self):
        with pytest.raises(ValueError) as exc_info:
            drop_iceberg_table(MagicMock(), MagicMock(), "events; DROP")
        assert "Invalid SQL identifier" in str(exc_info.value)

    def test_drop_iceberg_table_is_non_fatal(self):
        # delete_tables wipes DuckLake; the Iceberg drop is best-effort and must
        # not raise even when the catalog isn't attached for this org.
        conn = MagicMock()
        conn.execute.side_effect = Exception("Catalog with name iceberg does not exist")
        drop_iceberg_table(MagicMock(), conn, "events")  # must not raise


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


class TestIcebergInsertByNameHivePartitioning:
    """Regression tests for the Iceberg dual-write INSERT ... BY NAME.

    read_parquet() auto-detects the Hive year=/month=/day= keys in the S3 path
    and synthesizes year/month/day columns. INSERT ... BY NAME then tries to map
    those into the events table, which has no such columns, producing a binder
    error. Disabling hive_partitioning keeps read_parquet to the real data
    columns. These reuse TestDuckLakeAddDataFilesPartitioning's catalog fixture.
    """

    ducklake_env = TestDuckLakeAddDataFilesPartitioning.ducklake_env

    def _hive_partitioned_parquet(self, parquet_dir):
        dest = os.path.join(parquet_dir, "2", "year=2026", "month=03", "day=30")
        os.makedirs(dest, exist_ok=True)
        path = os.path.join(dest, "run.parquet")
        os.link(os.path.join(parquet_dir, "events.parquet"), path)
        return path

    def test_insert_by_name_default_hive_partitioning_fails(self, ducklake_env):
        # Reproduces the production error: BY NAME can't map the inferred day column.
        conn, parquet_dir = ducklake_env
        path = self._hive_partitioned_parquet(parquet_dir)
        with pytest.raises(duckdb.BinderException, match='column with name "day"'):
            conn.execute(f"INSERT INTO test_lake.posthog.events BY NAME SELECT * FROM read_parquet('{path}')")

    def test_insert_by_name_hive_partitioning_false_succeeds(self, ducklake_env):
        conn, parquet_dir = ducklake_env
        path = self._hive_partitioned_parquet(parquet_dir)
        conn.execute(
            f"INSERT INTO test_lake.posthog.events BY NAME "
            f"SELECT * FROM read_parquet('{path}', hive_partitioning=false)"
        )
        result = conn.execute("SELECT count(*) FROM test_lake.posthog.events").fetchone()
        assert result[0] == 1

    def test_write_partition_emits_hive_partitioning_false(self):
        # Guards the production code path itself (the tests above only exercise
        # hand-written SQL): write_partition_to_iceberg must emit a read_parquet
        # that disables Hive inference, or BY NAME breaks on the path's
        # year/month/day keys again.
        executed: list[str] = []
        conn = MagicMock()
        conn.execute.side_effect = lambda stmt, *a, **k: executed.append(
            stmt.as_string(None) if hasattr(stmt, "as_string") else str(stmt)
        )

        result = write_partition_to_iceberg(
            MagicMock(),
            conn,
            "events",
            "s3://bucket/backfill/events/2/year=2026/month=05/day=31/run.parquet",
            2,
            "timestamp",
            datetime(2026, 5, 31),
        )

        assert result is True
        insert_sql = next(s for s in executed if "read_parquet" in s)
        assert "BY NAME" in insert_sql
        assert "hive_partitioning=false" in insert_sql


class TestDucklingConcurrencyTags:
    # The combined events+persons cap is enforced on the shared key in the charts
    # Dagster deployment settings. If either backfill drops the shared tag, the
    # cap silently stops applying to it — guard against that here.
    def test_events_and_persons_share_the_combined_concurrency_key(self):
        ((shared_key, shared_value),) = DUCKLING_BACKFILL_CONCURRENCY_TAG.items()
        assert EVENTS_CONCURRENCY_TAG[shared_key] == shared_value
        assert PERSONS_CONCURRENCY_TAG[shared_key] == shared_value
