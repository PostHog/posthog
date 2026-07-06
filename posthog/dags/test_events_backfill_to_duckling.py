import os
from datetime import date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import duckdb
import psycopg
from parameterized import parameterized

from posthog.dags.common import JobOwners
from posthog.dags.events_backfill_to_duckling import (
    _DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENV_VAR,
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
    _ducklake_file_partition_value_fixup_enabled,
    _estimate_export_row_count,
    _execute_export_with_retry,
    _fixup_partition_values_for_added_files,
    _get_cluster,
    _glob_run_files,
    _is_transient_s3_error,
    _resolve_duckling_target,
    _resolve_table_names,
    _set_table_partitioning,
    _validate_identifier,
    delete_events_partition_data,
    duckling_events_backfill_job,
    duckling_events_daily_backfill_sensor,
    duckling_events_full_backfill_sensor,
    duckling_persons_backfill_job,
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


@pytest.fixture(autouse=True)
def _disable_ducklake_file_partition_value_fixup_by_default():
    # The ducklake_file_partition_value fix-up is gated by DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENABLED, which defaults on
    # in production. Most tests in this file use mock connections that can't
    # actually run the fix-up; default to off here and let the ducklake_file_partition_value-specific
    # tests override with their own @patch(..., return_value=True).
    with patch(
        "posthog.dags.events_backfill_to_duckling._ducklake_file_partition_value_fixup_enabled", return_value=False
    ):
        yield


class TestDucklingBackfillAlertRouting:
    @parameterized.expand(
        [
            ("events", duckling_events_backfill_job),
            ("persons", duckling_persons_backfill_job),
        ]
    )
    def test_backfill_jobs_alert_managed_warehouse(self, _name, job):
        assert job.tags["owner"] == JobOwners.TEAM_MANAGED_WAREHOUSE.value
        assert "disable_slack_notifications" not in job.tags


class TestResolveDucklingTarget:
    @patch("posthog.dags.events_backfill_to_duckling._resolve_table_names", return_value=("events", "persons"))
    @patch("posthog.dags.events_backfill_to_duckling.get_duckgres_server_for_organization", return_value=None)
    @patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1")
    def test_resolves_bucket_from_control_plane(
        self, mock_org: MagicMock, _mock_server: MagicMock, _mock_tables: MagicMock
    ):
        # The control plane is the authoritative owner of the bucket name.
        with patch(
            "products.data_warehouse.backend.presentation.views.managed_warehouse.cp_bucket_for",
            return_value="posthog-duckling-org-1-mw-prod-us",
        ) as mock_cp:
            target = _resolve_duckling_target(7)

        assert target == DucklingTarget(
            team_id=7,
            organization_id="org-1",
            bucket="posthog-duckling-org-1-mw-prod-us",
            bucket_region="us-east-1",
        )
        mock_org.assert_called_once_with(7)
        mock_cp.assert_called_once_with("org-1")

    @patch("posthog.dags.events_backfill_to_duckling._resolve_table_names", return_value=("events", "persons"))
    @patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1")
    def test_control_plane_wins_over_stale_stored_server_bucket(self, _mock_org: MagicMock, _mock_tables: MagicMock):
        # A row provisioned before the naming fix carries a stale bucket; the CP value
        # must win so the backfill never exports to a bucket that doesn't exist.
        server = MagicMock(bucket="posthog-duckling-stale-prod-us", bucket_region="us-east-1")
        with (
            patch(
                "posthog.dags.events_backfill_to_duckling.get_duckgres_server_for_organization",
                return_value=server,
            ),
            patch(
                "products.data_warehouse.backend.presentation.views.managed_warehouse.cp_bucket_for",
                return_value="posthog-duckling-org-1-mw-prod-us",
            ),
        ):
            target = _resolve_duckling_target(7)

        assert target.bucket == "posthog-duckling-org-1-mw-prod-us"

    @patch("posthog.dags.events_backfill_to_duckling._resolve_table_names", return_value=("events", "persons"))
    @patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1")
    def test_falls_back_to_stored_server_when_control_plane_unavailable(
        self, _mock_org: MagicMock, _mock_tables: MagicMock
    ):
        # CP can't answer → use the known-good stored row rather than failing the run.
        server = MagicMock(bucket="posthog-duckling-org-1-mw-prod-us", bucket_region="us-east-1")
        with (
            patch(
                "posthog.dags.events_backfill_to_duckling.get_duckgres_server_for_organization",
                return_value=server,
            ),
            patch(
                "products.data_warehouse.backend.presentation.views.managed_warehouse.cp_bucket_for",
                return_value=None,
            ),
        ):
            target = _resolve_duckling_target(7)

        assert target.bucket == "posthog-duckling-org-1-mw-prod-us"

    @patch("posthog.dags.events_backfill_to_duckling._resolve_table_names", return_value=("events", "persons"))
    @patch("posthog.dags.events_backfill_to_duckling.get_duckgres_server_for_organization", return_value=None)
    @patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1")
    def test_raises_when_nothing_can_name_the_bucket(
        self, _mock_org: MagicMock, _mock_server: MagicMock, _mock_tables: MagicMock
    ):
        with patch(
            "products.data_warehouse.backend.presentation.views.managed_warehouse.cp_bucket_for",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="No S3 bucket resolvable"):
                _resolve_duckling_target(7)


class TestResolveTableNames:
    """Resolution of per-environment table names from a team's stored table_suffix.

    Kept DB-free (the rest of this file is): the stored suffix is mocked at the ORM boundary.
    """

    def _patch_suffix(self, suffix: str | None) -> MagicMock:
        model = MagicMock()
        model.objects.filter.return_value.values_list.return_value.first.return_value = suffix
        return model

    def test_set_suffix_yields_dedicated_tables(self):
        with patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam", self._patch_suffix("alpha")):
            assert _resolve_table_names(1) == ("events_alpha", "persons_alpha")

    def test_distinct_suffixes_isolate_two_teams(self):
        with patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam", self._patch_suffix("alpha")):
            assert _resolve_table_names(1) == ("events_alpha", "persons_alpha")
        with patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam", self._patch_suffix("beta")):
            assert _resolve_table_names(2) == ("events_beta", "persons_beta")

    @parameterized.expand([("none", None), ("empty", "")])
    def test_unset_suffix_falls_back_to_shared_tables(self, _name, suffix):
        with patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam", self._patch_suffix(suffix)):
            assert _resolve_table_names(1) == ("events", "persons")

    def test_unsafe_suffix_is_rejected(self):
        with patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam", self._patch_suffix("a-b; DROP")):
            with pytest.raises(ValueError):
                _resolve_table_names(1)


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
        ddl = EVENTS_TABLE_DDL.format(catalog="memory", table="events")
        conn.execute(ddl)

        # Verify table was created with expected columns
        result = conn.execute("DESCRIBE memory.posthog.events").fetchall()
        column_names = {row[0] for row in result}

        assert column_names == EXPECTED_DUCKLAKE_EVENTS_COLUMNS
        conn.close()

    def test_events_ddl_is_idempotent(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        ddl = EVENTS_TABLE_DDL.format(catalog="memory", table="events")
        # Should not raise on second execution
        conn.execute(ddl)
        conn.execute(ddl)
        conn.close()

    def test_events_ddl_honors_suffixed_table_name(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        conn.execute(EVENTS_TABLE_DDL.format(catalog="memory", table="events_alpha"))

        result = conn.execute("DESCRIBE memory.posthog.events_alpha").fetchall()
        assert {row[0] for row in result} == EXPECTED_DUCKLAKE_EVENTS_COLUMNS
        conn.close()


class TestPersonsDDL:
    def test_persons_ddl_is_valid_sql(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        ddl = PERSONS_TABLE_DDL.format(catalog="memory", table="persons")
        conn.execute(ddl)

        # Verify table was created with expected columns
        result = conn.execute("DESCRIBE memory.posthog.persons").fetchall()
        column_names = {row[0] for row in result}

        assert column_names == EXPECTED_DUCKLAKE_PERSONS_COLUMNS
        conn.close()

    def test_persons_ddl_is_idempotent(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        ddl = PERSONS_TABLE_DDL.format(catalog="memory", table="persons")
        # Should not raise on second execution
        conn.execute(ddl)
        conn.execute(ddl)
        conn.close()

    def test_persons_ddl_honors_suffixed_table_name(self):
        conn = duckdb.connect()
        conn.execute("CREATE SCHEMA IF NOT EXISTS memory.posthog")
        conn.execute(PERSONS_TABLE_DDL.format(catalog="memory", table="persons_beta"))

        result = conn.execute("DESCRIBE memory.posthog.persons_beta").fetchall()
        assert {row[0] for row in result} == EXPECTED_DUCKLAKE_PERSONS_COLUMNS
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
    @patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam")
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
        backfill.earliest_event_date = None  # unresolved → sensor resolves + caches it
        mock_backfill_cls.objects.filter.return_value.order_by.return_value = [backfill]

        instance = DagsterInstance.ephemeral()
        context = build_sensor_context(instance=instance)
        result = duckling_events_full_backfill_sensor(context)
        assert isinstance(result, SensorResult)
        assert result.run_requests is not None

        assert len(result.run_requests) > 0
        first_key = result.run_requests[0].partition_key
        assert first_key == f"1_{expected_first_month}"
        # Round-robin order is oldest-month-first for a single team.
        assert result.run_requests[0].run_key == first_key
        # Earliest date is cached on the row so later ticks never re-query ClickHouse.
        assert backfill.earliest_event_date == max(earliest_dt, datetime(2015, 1, 1)).date()

    @patch("posthog.dags.events_backfill_to_duckling.get_earliest_event_date_for_team")
    @patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam")
    @patch("posthog.dags.events_backfill_to_duckling.timezone")
    def test_no_events_returns_empty(self, mock_tz, mock_backfill_cls, mock_get_earliest):
        from dagster import DagsterInstance, SensorResult, build_sensor_context

        mock_tz.now.return_value = datetime(2025, 2, 10, 12, 0, 0)
        mock_get_earliest.return_value = None

        backfill = MagicMock()
        backfill.team_id = 1
        backfill.earliest_event_date = None
        mock_backfill_cls.objects.filter.return_value.order_by.return_value = [backfill]

        instance = DagsterInstance.ephemeral()
        context = build_sensor_context(instance=instance)
        result = duckling_events_full_backfill_sensor(context)
        assert isinstance(result, SensorResult)
        assert result.run_requests is not None

        assert len(result.run_requests) == 0
        # No events → cache the sentinel so the team isn't re-queried every tick.
        from posthog.dags.events_backfill_to_duckling import _NO_HISTORY_SENTINEL

        assert backfill.earliest_event_date == _NO_HISTORY_SENTINEL

    def test_earliest_backfill_date_is_2015(self):
        assert EARLIEST_BACKFILL_DATE == datetime(2015, 1, 1)

    @staticmethod
    def _bf(team_id: int, earliest=None):
        m = MagicMock()
        m.team_id = team_id
        m.earliest_event_date = earliest
        return m

    def _run_full_sensor(self, backfills, *, now, get_earliest, existing=None, get_runs=None):
        """Drive duckling_events_full_backfill_sensor against mocked backfills + an ephemeral instance."""
        from dagster import DagsterInstance, build_sensor_context

        with (
            patch("posthog.dags.events_backfill_to_duckling.timezone") as mock_tz,
            patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam") as mock_cls,
            patch("posthog.dags.events_backfill_to_duckling.get_earliest_event_date_for_team") as mock_ge,
        ):
            mock_tz.now.return_value = now
            mock_cls.objects.filter.return_value.order_by.return_value = backfills
            if isinstance(get_earliest, list):
                mock_ge.side_effect = get_earliest
            else:
                mock_ge.return_value = get_earliest

            instance = DagsterInstance.ephemeral()
            if existing:
                instance.add_dynamic_partitions("duckling_events_backfill", list(existing))

            context = build_sensor_context(instance=instance)
            if get_runs is not None:
                with patch.object(instance, "get_runs", return_value=get_runs):
                    result = duckling_events_full_backfill_sensor(context)
            else:
                result = duckling_events_full_backfill_sensor(context)
            return result, mock_ge

    def test_round_robin_interleaves_teams(self):
        # Two teams with the same range → emission alternates team by month index, so the
        # FIFO queue drains both fairly rather than finishing team 1's whole history first.
        # The current month (2020-03) is excluded — it's the daily sensor's job.
        backfills = [self._bf(1), self._bf(2)]
        result, _ = self._run_full_sensor(
            backfills, now=datetime(2020, 3, 10, 12, 0, 0), get_earliest=datetime(2020, 1, 1)
        )
        keys = [rr.partition_key for rr in result.run_requests]
        assert keys == ["1_2020-01", "2_2020-01", "1_2020-02", "2_2020-02"]
        # Every full-backfill run is tagged so the next tick's in-flight count excludes daily runs.
        assert all(rr.tags.get("duckling_backfill_type") == "full" for rr in result.run_requests)

    def test_excludes_current_in_progress_month(self):
        # The full backfill stops at the end of last month; the current, in-progress month
        # (2020-03) is owned by the daily sensor and must never be emitted as a monthly
        # partition (it would race the daily runs for the same team-days).
        result, _ = self._run_full_sensor(
            [self._bf(1, earliest=date(2020, 1, 1))],
            now=datetime(2020, 3, 10, 12, 0, 0),
            get_earliest=None,
        )
        keys = [rr.partition_key for rr in result.run_requests]
        assert keys == ["1_2020-01", "1_2020-02"]

    def test_team_with_only_current_month_history_gets_nothing(self):
        # A team whose earliest event is in the current month has no complete month to
        # full-backfill, so the sensor emits nothing for it — the daily sensor covers it.
        result, _ = self._run_full_sensor(
            [self._bf(1, earliest=date(2020, 3, 2))],
            now=datetime(2020, 3, 10, 12, 0, 0),
            get_earliest=None,
        )
        assert result.run_requests == []

    def test_skips_existing_partitions(self):
        result, _ = self._run_full_sensor(
            [self._bf(1, earliest=date(2020, 1, 1))],
            now=datetime(2020, 3, 10, 12, 0, 0),
            get_earliest=None,  # earliest already cached → no lookup
            existing=["1_2020-01"],
        )
        keys = [rr.partition_key for rr in result.run_requests]
        assert "1_2020-01" not in keys
        assert keys == ["1_2020-02"]

    def test_does_not_requery_cached_earliest(self):
        result, mock_ge = self._run_full_sensor(
            [self._bf(1, earliest=date(2020, 1, 1))],
            now=datetime(2020, 2, 10, 12, 0, 0),
            get_earliest=None,
        )
        mock_ge.assert_not_called()
        assert [rr.partition_key for rr in result.run_requests] == ["1_2020-01"]

    def test_caps_earliest_lookups_per_tick(self):
        # 7 unresolved teams, cap is 5 → only 5 ClickHouse lookups this tick; the other two
        # stay unresolved and contribute no partitions until a later tick.
        backfills = [self._bf(t) for t in range(1, 8)]
        result, mock_ge = self._run_full_sensor(
            backfills, now=datetime(2020, 2, 10, 12, 0, 0), get_earliest=datetime(2020, 1, 1)
        )
        assert mock_ge.call_count == 5
        teams_emitted = {rr.partition_key.split("_")[0] for rr in result.run_requests}
        assert teams_emitted == {"1", "2", "3", "4", "5"}
        assert backfills[5].earliest_event_date is None and backfills[6].earliest_event_date is None

    def test_top_up_only_fills_to_target_depth(self):
        # 98 runs already in flight against the depth-100 target → only 2 slots free this tick.
        result, _ = self._run_full_sensor(
            [self._bf(1, earliest=date(2015, 1, 1))],
            now=datetime(2020, 3, 10, 12, 0, 0),
            get_earliest=None,
            get_runs=[MagicMock()] * 98,
        )
        assert len(result.run_requests) == 2

    def test_top_up_emits_nothing_when_queue_full(self):
        result, _ = self._run_full_sensor(
            [self._bf(1, earliest=date(2015, 1, 1))],
            now=datetime(2020, 3, 10, 12, 0, 0),
            get_earliest=None,
            get_runs=[MagicMock()] * 100,
        )
        assert len(result.run_requests) == 0

    def test_inflight_count_filters_by_full_backfill_tag(self):
        # The in-flight query must be scoped to full-backfill runs via the tag, so daily
        # runs on the shared job can't starve the top-up.
        from dagster import DagsterInstance, build_sensor_context

        with (
            patch("posthog.dags.events_backfill_to_duckling.timezone") as mock_tz,
            patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam") as mock_cls,
            patch("posthog.dags.events_backfill_to_duckling.get_earliest_event_date_for_team"),
        ):
            mock_tz.now.return_value = datetime(2020, 2, 10, 12, 0, 0)
            mock_cls.objects.filter.return_value.order_by.return_value = [self._bf(1, earliest=date(2020, 1, 1))]
            instance = DagsterInstance.ephemeral()
            context = build_sensor_context(instance=instance)
            with patch.object(instance, "get_runs", return_value=[]) as mock_get_runs:
                duckling_events_full_backfill_sensor(context)

        runs_filter = mock_get_runs.call_args.kwargs["filters"]
        assert runs_filter.tags == {"duckling_backfill_type": "full"}


class TestDailyBackfillSensor:
    @staticmethod
    def _team(team_id: int):
        m = MagicMock()
        m.team_id = team_id
        return m

    @staticmethod
    def _daily_keys(team_id: int, start: date, end: date) -> list[str]:
        # Build expected partition keys the same way prod does (strftime), so a formatting bug
        # (e.g. a hand-rolled zero-pad that breaks on two-digit days) would be caught.
        keys = []
        d = start
        while d <= end:
            keys.append(f"{team_id}_{d.strftime('%Y-%m-%d')}")
            d += timedelta(days=1)
        return keys

    def _run_daily(self, backfills, *, now, existing=None, get_runs=None):
        from dagster import DagsterInstance, build_sensor_context

        with (
            patch("posthog.dags.events_backfill_to_duckling.timezone") as mock_tz,
            patch("posthog.dags.events_backfill_to_duckling.DuckgresServerTeam") as mock_cls,
        ):
            mock_tz.now.return_value = now
            mock_cls.objects.filter.return_value = backfills

            instance = DagsterInstance.ephemeral()
            if existing:
                instance.add_dynamic_partitions("duckling_events_backfill", list(existing))

            context = build_sensor_context(instance=instance)
            if get_runs is not None:
                with patch.object(instance, "get_runs", return_value=get_runs):
                    return duckling_events_daily_backfill_sensor(context)
            return duckling_events_daily_backfill_sensor(context)

    def test_steady_state_creates_only_yesterday(self):
        # Established team already has every current-month day except yesterday → only
        # yesterday (2020-03-09) is new, matching the pre-catch-up behavior.
        existing = [f"1_2020-03-0{d}" for d in range(1, 9)]  # 2020-03-01 .. 2020-03-08
        result = self._run_daily([self._team(1)], now=datetime(2020, 3, 10, 12, 0, 0), existing=existing)
        assert [rr.partition_key for rr in result.run_requests] == ["1_2020-03-09"]

    def test_catches_up_current_month_for_newly_enabled_team(self):
        # A team with no existing partitions (just enabled) gets every current-month day from
        # the 1st through yesterday, closing the gap the full-backfill sensor won't cover.
        # now=the 15th so the range crosses the single/two-digit day boundary (01..14).
        result = self._run_daily([self._team(1)], now=datetime(2020, 3, 15, 12, 0, 0))
        keys = [rr.partition_key for rr in result.run_requests]
        assert keys == self._daily_keys(1, date(2020, 3, 1), date(2020, 3, 14))

    def test_first_of_month_is_noop(self):
        # On the 1st, yesterday is in the previous month (owned by that month's now-complete
        # full-backfill partition), so the daily sensor creates nothing.
        result = self._run_daily([self._team(1)], now=datetime(2020, 3, 1, 12, 0, 0))
        assert result.run_requests == []

    def test_retries_only_yesterday_not_older_days(self):
        # All current-month days already exist and their last run failed, but only yesterday
        # (2020-03-09) is retried — older caught-up days are left alone, keeping the per-tick
        # run lookup to one query per team.
        from dagster import DagsterRunStatus

        existing = [f"1_2020-03-0{d}" for d in range(1, 10)]  # 2020-03-01 .. 2020-03-09
        failed = MagicMock()
        failed.status = DagsterRunStatus.FAILURE
        failed.run_id = "deadbeefcafef00d"
        result = self._run_daily(
            [self._team(1)], now=datetime(2020, 3, 10, 12, 0, 0), existing=existing, get_runs=[failed]
        )
        keys = [rr.partition_key for rr in result.run_requests]
        assert keys == ["1_2020-03-09"]
        assert result.run_requests[0].run_key == "1_2020-03-09_retry_deadbeef"

    def test_catchup_is_bounded_per_tick_but_yesterday_always_emitted(self):
        # With the catch-up cap at 3 and two freshly enabled teams on 2020-03-05 (older days
        # 01/02/03, yesterday 04): the first team exhausts the cap with its three older days,
        # the second team's older days are dropped this tick, but BOTH teams still get
        # yesterday so freshness never starves behind the backlog.
        with patch(
            "posthog.dags.events_backfill_to_duckling.DAILY_BACKFILL_MAX_CATCHUP_PARTITIONS_PER_TICK",
            3,
        ):
            result = self._run_daily(
                [self._team(1), self._team(2)],
                now=datetime(2020, 3, 5, 12, 0, 0),
            )
        keys = [rr.partition_key for rr in result.run_requests]
        assert keys == [
            "1_2020-03-01",
            "1_2020-03-02",
            "1_2020-03-03",
            "1_2020-03-04",
            "2_2020-03-04",
        ]


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
        conn.execute(EVENTS_TABLE_DDL.format(catalog="test_lake", table="events"))
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


# The exact shape duckgres surfaces when S3 5xx/throttles mid-glob (HTTP GET listing the run's
# files); a ProgrammingError, NOT a connection drop — so it needs its own retry path.
_S3_503_GLOB_ERROR = psycopg.errors.SyntaxErrorOrAccessRuleViolation(
    "rpc error: code = Unknown desc = HTTP Error: HTTP GET error reading "
    "'s3://posthog-duckling-x-mw-prod-us/backfill/events/55513/year=2019/month=12/day=21/abc_' "
    "in region 'us-east-1' (HTTP 503 Service Unavailable)"
)


class TestIsTransientS3Error:
    """_is_transient_s3_error retries S3 5xx/throttles surfaced through the PG wire, but only
    when the message is genuinely about object storage (so a plain SQL error can't match)."""

    @parameterized.expand(
        [
            ("glob_503", _S3_503_GLOB_ERROR),
            (
                "add_files_500",
                psycopg.errors.InternalError(
                    "HTTP Error: HTTP GET error reading 's3://b/f.parquet' (HTTP 500 InternalError)"
                ),
            ),
            (
                "slowdown_throttle",
                psycopg.OperationalError("HTTP PUT error writing 's3://b/f' (HTTP 503 SlowDown: Please reduce ...)"),
            ),
            ("too_many_requests", psycopg.errors.InternalError("HTTP GET 's3://b/x' HTTP 429 Too Many Requests")),
        ]
    )
    def test_transient_s3_errors_are_retryable(self, _label, exc):
        assert _is_transient_s3_error(exc) is True

    @parameterized.expand(
        [
            # 404/403 are permanent S3 responses — not retryable.
            ("not_found", psycopg.errors.InternalError("HTTP GET error reading 's3://b/missing' (HTTP 404 Not Found)")),
            ("access_denied", psycopg.errors.InternalError("HTTP GET 's3://b/x' (HTTP 403 Forbidden)")),
            # A genuine SQL error that merely contains a number must not match (no S3/HTTP token).
            ("sql_error_with_500", psycopg.errors.SyntaxErrorOrAccessRuleViolation("error near column 500")),
            ("binder_error", psycopg.errors.InternalError("Binder Error: Referenced column not found")),
            # 503 text without any object-storage context must not match either.
            ("bare_503", psycopg.OperationalError("service had 503 issues")),
        ]
    )
    def test_non_transient_errors_are_not_retryable(self, _label, exc):
        assert _is_transient_s3_error(exc) is False


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

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckgres")
    def test_transient_s3_retries_on_same_connection(self, mock_connect, _sleep):
        # A transient S3 5xx is the worker hiccuping on object storage, not a worker drop —
        # so it replays on the SAME connection (no reconnect) and eventually succeeds.
        mock_connect.return_value = MagicMock()
        session = _DuckgresSession(MagicMock(), MagicMock())
        op = MagicMock(side_effect=[_S3_503_GLOB_ERROR, _S3_503_GLOB_ERROR, "ok"])

        assert session.run("register", op) == "ok"
        assert op.call_count == 3
        assert mock_connect.call_count == 1  # initial connect only — never reconnected

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep")
    @patch("posthog.dags.events_backfill_to_duckling._connect_duckgres")
    def test_transient_s3_gives_up_after_max_attempts(self, mock_connect, _sleep):
        mock_connect.return_value = MagicMock()
        session = _DuckgresSession(MagicMock(), MagicMock())
        op = MagicMock(side_effect=_S3_503_GLOB_ERROR)

        with pytest.raises(psycopg.errors.SyntaxErrorOrAccessRuleViolation):
            session.run("register", op)
        assert op.call_count == _DuckgresSession.MAX_ATTEMPTS
        assert mock_connect.call_count == 1  # never reconnects for an S3 hiccup


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
        # 50M rows at the 5M-row default target → 10 files.
        insert_sql, count_sql, s3_glob, _ = self._run_export(
            export_events_to_duckling_s3, target, row_count=50_000_000, team_id=2, date=datetime(2026, 6, 17)
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
        # 15M rows at the 5M-row default target → 3 files.
        insert_sql, count_sql, s3_glob, _ = self._run_export(
            export_persons_to_duckling_s3, target, row_count=15_000_000, team_id=2, date=datetime(2026, 6, 17)
        )
        assert "PARTITION BY toString(cityHash64(distinct_id) % 3)" in insert_sql
        # Pin the full predicate: dropping is_deleted/date would silently over-size the fan-out.
        assert "FROM person WHERE team_id = 2 AND toDate(_timestamp) = '2026-06-17' AND is_deleted = 0" in count_sql
        assert s3_glob == "s3://bkt/backfill/persons/2/year=2026/month=06/run1_*.parquet"

    def test_persons_full_export_sizes_fanout_and_returns_glob(self, target):
        # 25M rows at the 5M-row default target → 5 files.
        insert_sql, count_sql, s3_glob, _ = self._run_export(
            export_persons_full_to_duckling_s3, target, row_count=25_000_000, team_id=2
        )
        assert "PARTITION BY toString(cityHash64(distinct_id) % 5)" in insert_sql
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

    def test_glob_run_files_empty_day_returns_no_files(self):
        # A zero-event team-day writes no Parquet, so the glob matches nothing and
        # duckgres returns a command-complete with no result set: fetchall() raises
        # "the last operation didn't produce a result". _glob_run_files must absorb
        # that and return [] (nothing to register).
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.side_effect = psycopg.ProgrammingError("the last operation didn't produce a result")
        conn.cursor.return_value.__enter__.return_value = cur
        conn.cursor.return_value.__exit__.return_value = False

        assert _glob_run_files(conn, "s3://bkt/x/run1_*.parquet") == []

    def test_glob_run_files_propagates_other_programming_errors(self):
        # A genuine SQL error must not be swallowed as "no files".
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchall.side_effect = psycopg.ProgrammingError("syntax error at or near")
        conn.cursor.return_value.__enter__.return_value = cur
        conn.cursor.return_value.__exit__.return_value = False

        with pytest.raises(psycopg.ProgrammingError, match="syntax error"):
            _glob_run_files(conn, "s3://bkt/x/run1_*.parquet")


_EVENTS_SPEC_ROWS = [(0, "year"), (1, "month"), (2, "day")]
_PERSONS_SPEC_ROWS = [(0, "year"), (1, "month")]


def _make_catalog_conn_mock(
    *,
    post_condition_row: tuple[int, int, int],
    spec_rows: list[tuple[int, str]] | None = None,
    partition_info_rows: list[tuple[int, int]] | None = None,
    lock_acquired: bool = True,
):
    """Builds a MagicMock catalog conn + cur that returns scripted values for the
    sequence of fetches _fixup_partition_values_for_added_files makes. Order:
      fetchone() → advisory lock result
      fetchall() → partition_info_rows
      fetchall() → spec_rows (live partition_column spec)
      fetchone() → post_condition_row

    post_condition_row is required: defaulting it to (0, 0, 0) would silently
    trip the post-condition's `total != len(file_paths)` branch in any test
    that passes a non-empty file list — a footgun for future tests.
    """
    cur = MagicMock()
    cur.fetchone.side_effect = [(lock_acquired,), post_condition_row]
    cur.fetchall.side_effect = [
        partition_info_rows or [(760, 761)],
        spec_rows or _EVENTS_SPEC_ROWS,
    ]
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = None

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = None
    # `closed` defaults to a truthy MagicMock; explicitly False so the finally
    # block's `if not conn.closed` guard runs the unlock path.
    conn.closed = False
    return conn, cur


class TestDucklakeFilePartitionValueFixupFlag:
    @parameterized.expand(
        [
            ("unset", None, True),
            ("true", "true", True),
            ("True_mixedcase", "True", True),
            ("one", "1", True),
            ("yes", "yes", True),
            ("on", "on", True),
            ("false", "false", False),
            ("zero", "0", False),
            ("no", "no", False),
            ("garbage", "garbage", False),
            ("empty", "", False),
        ]
    )
    def test_flag_parsing(self, _label, env_value, expected):
        original = os.environ.get(_DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENV_VAR)
        if env_value is None:
            os.environ.pop(_DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENV_VAR, None)
        else:
            os.environ[_DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENV_VAR] = env_value
        try:
            assert _ducklake_file_partition_value_fixup_enabled() is expected
        finally:
            if original is None:
                os.environ.pop(_DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENV_VAR, None)
            else:
                os.environ[_DUCKLAKE_FILE_PARTITION_VALUE_FIXUP_ENV_VAR] = original


class TestDucklakeFilePartitionValueFixupHelper:
    @pytest.fixture
    def target(self):
        return DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")

    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_empty_file_list_is_noop(self, mock_open_conn, target):
        _fixup_partition_values_for_added_files(MagicMock(), target, "events", "events", [])
        mock_open_conn.assert_not_called()

    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_unknown_table_kind_raises(self, mock_open_conn, target):
        # table_kind is Literal["events", "persons"] so a bad value triggers a
        # mypy error too; the type: ignore is the test-only way to exercise the
        # runtime guard. The runtime guard exists as belt-and-suspenders for
        # any caller that bypasses static typing.
        with pytest.raises(ValueError, match="_DUCKLAKE_FILE_PARTITION_VALUE_SPEC has no entry"):
            _fixup_partition_values_for_added_files(
                MagicMock(),
                target,
                "unknown_kind",  # type: ignore[arg-type]
                "unknown_table",
                ["s3://bkt/whatever/year=2026/month=06/day=17/run1.parquet"],
            )
        mock_open_conn.assert_not_called()

    @parameterized.expand(
        [
            ("missing_year", "events", "s3://bkt/backfill/events/2/month=06/day=17/run1.parquet"),
            ("missing_day_events", "events", "s3://bkt/backfill/events/2/year=2026/month=06/run1.parquet"),
            ("missing_month_persons", "persons", "s3://bkt/backfill/persons/2/year=2026/run1.parquet"),
            ("nonparquet_suffix", "events", "s3://bkt/backfill/events/2/year=2026/month=06/day=17/run1.txt"),
            ("lake_relative", "events", "ducklake-abcdef.parquet"),
        ]
    )
    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_pre_flight_rejects_malformed_paths(self, _label, kind, bad_path, mock_open_conn):
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        with pytest.raises(ValueError, match="do not match the expected hive layout"):
            _fixup_partition_values_for_added_files(MagicMock(), target, kind, kind, [bad_path])
        mock_open_conn.assert_not_called()

    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_persons_full_export_path_accepted(self, mock_open_conn, target):
        # Persons "full" export writes year=0/month=0; the regex must accept it.
        # We let _open_catalog_conn raise so the test asserts regex-passed-but-then-stopped.
        mock_open_conn.side_effect = RuntimeError("regex passed")
        with pytest.raises(RuntimeError, match="regex passed"):
            _fixup_partition_values_for_added_files(
                MagicMock(),
                target,
                "persons",
                "persons",
                ["s3://bkt/backfill/persons/2/year=0/month=0/run1_0.parquet"],
            )
        mock_open_conn.assert_called_once_with(target)

    @parameterized.expand(
        [
            ("events_suffixed", "events", "events_acme"),
            ("persons_suffixed", "persons", "persons_acme"),
        ]
    )
    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_suffixed_table_name_uses_actual_name_in_catalog_lookup(
        self, _label, kind, actual_table_name, mock_open_conn
    ):
        # When DuckgresServerTeam.table_suffix is set, the dagster registration
        # path writes to events_<suffix> / persons_<suffix>. The fix-up must
        # look up THAT table in the catalog, not the bare kind name. Verified
        # by inspecting the cur.execute call binding the table_name param.
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        ext = "/day=17/run1_0.parquet" if kind == "events" else "/run1_0.parquet"
        files = [f"s3://bkt/backfill/{kind}/2/year=2026/month=06{ext}"]
        spec_rows = _EVENTS_SPEC_ROWS if kind == "events" else _PERSONS_SPEC_ROWS
        conn, cur = _make_catalog_conn_mock(post_condition_row=(0, 0, len(files)), spec_rows=spec_rows)
        mock_open_conn.return_value = conn

        _fixup_partition_values_for_added_files(MagicMock(), target, kind, actual_table_name, files)

        # The partition_info SELECT is parameter-bound with (table_name,); pin
        # that we're querying for the suffixed name, not the bare kind.
        partition_info_calls = [c for c in cur.execute.call_args_list if "ducklake_partition_info" in str(c.args[0])]
        assert len(partition_info_calls) == 1
        assert partition_info_calls[0].args[1] == (actual_table_name,)


class TestDucklakeFilePartitionValueFixupCatalogInteraction:
    @pytest.fixture
    def target(self):
        return DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")

    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_session_bounded_and_lock_taken_before_any_dml(self, mock_open_conn, target):
        files = ["s3://bkt/backfill/events/2/year=2026/month=06/day=17/run1_0.parquet"]
        conn, cur = _make_catalog_conn_mock(post_condition_row=(0, 0, len(files)))
        mock_open_conn.return_value = conn

        _fixup_partition_values_for_added_files(MagicMock(), target, "events", "events", files)

        executed_sql = [str(call.args[0]) for call in cur.execute.call_args_list]
        # Session advisory lock is acquired OUTSIDE the txn (the very first SQL)
        # so retry backoffs don't sit idle-in-transaction. SET LOCAL bounds come
        # immediately after, inside the txn, before any DML.
        assert "pg_try_advisory_lock" in executed_sql[0]
        assert "SET LOCAL statement_timeout" in executed_sql[1]
        assert "SET LOCAL lock_timeout" in executed_sql[2]
        # Nothing touches the file_partition_value table before the lock is held.
        assert not any("file_partition_value" in s for s in executed_sql[:3])
        # Lock is released at the end (best-effort, via finally).
        assert "pg_advisory_unlock" in executed_sql[-1]

    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_runtime_spec_mismatch_raises(self, mock_open_conn, target):
        files = ["s3://bkt/backfill/events/2/year=2026/month=06/day=17/run1_0.parquet"]
        # Live catalog returns only (year, month) for an events table that expects
        # (year, month, day) — the fix-up must fail before any DML.
        # post_condition_row never reached (spec mismatch raises earlier); pass a dummy.
        conn, cur = _make_catalog_conn_mock(spec_rows=[(0, "year"), (1, "month")], post_condition_row=(0, 0, 0))
        mock_open_conn.return_value = conn

        with pytest.raises(RuntimeError, match="live catalog spec for posthog.events"):
            _fixup_partition_values_for_added_files(MagicMock(), target, "events", "events", files)

        executed_sql = [str(call.args[0]) for call in cur.execute.call_args_list]
        assert not any("DELETE FROM" in s for s in executed_sql)
        assert not any("INSERT INTO" in s for s in executed_sql)

    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_post_condition_failure_raises(self, mock_open_conn, target):
        files = ["s3://bkt/backfill/events/2/year=2026/month=06/day=17/run1_0.parquet"]
        # Post-condition returns 1 wrong-indexes row → must raise.
        conn, _cur = _make_catalog_conn_mock(post_condition_row=(1, 0, 1))
        mock_open_conn.return_value = conn

        with pytest.raises(RuntimeError, match="post-condition failed"):
            _fixup_partition_values_for_added_files(MagicMock(), target, "events", "events", files)

    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_unique_partition_info_required(self, mock_open_conn, target):
        files = ["s3://bkt/backfill/events/2/year=2026/month=06/day=17/run1_0.parquet"]
        # Two live partition_info rows for the same table → ambiguous → fail loud.
        # post_condition_row never reached (partition_info-cardinality check raises earlier).
        conn, _cur = _make_catalog_conn_mock(partition_info_rows=[(760, 761), (760, 999)], post_condition_row=(0, 0, 0))
        mock_open_conn.return_value = conn

        with pytest.raises(RuntimeError, match="expected exactly one live partition_info"):
            _fixup_partition_values_for_added_files(MagicMock(), target, "events", "events", files)

    @patch("posthog.dags.events_backfill_to_duckling.time.sleep", lambda _: None)
    @patch("posthog.dags.events_backfill_to_duckling._open_catalog_conn")
    def test_advisory_lock_exhaustion_raises(self, mock_open_conn, target):
        files = ["s3://bkt/backfill/events/2/year=2026/month=06/day=17/run1_0.parquet"]
        # Lock acquisition never succeeds within the retry budget.
        cur = MagicMock()
        cur.fetchone.side_effect = [(False,)] * 100  # plenty for the retry loop
        cur.__enter__.return_value = cur
        cur.__exit__.return_value = None
        conn = MagicMock()
        conn.cursor.return_value = cur
        conn.__enter__.return_value = conn
        conn.__exit__.return_value = None
        mock_open_conn.return_value = conn

        with pytest.raises(RuntimeError, match="could not acquire .* advisory lock"):
            _fixup_partition_values_for_added_files(MagicMock(), target, "events", "events", files)


class TestRegisterTriggersFixup:
    @parameterized.expand(
        [
            ("events", register_files_with_duckling, "events"),
            ("persons", register_persons_files_with_duckling, "persons"),
        ]
    )
    @patch("posthog.dags.events_backfill_to_duckling._fixup_partition_values_for_added_files")
    @patch("posthog.dags.events_backfill_to_duckling._ducklake_file_partition_value_fixup_enabled", return_value=True)
    def test_fixup_called_with_registered_paths_when_enabled(
        self, _label, register_fn, kind, _mock_enabled, mock_fixup
    ):
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        files = [f"s3://bkt/backfill/{kind}/2/year=2026/month=06/day=17/run1_{i}.parquet" for i in range(3)]
        conn, _cur = _mock_glob_conn(files)
        config = DucklingBackfillConfig()

        register_fn(MagicMock(), target, "s3://bkt/.../run1_*.parquet", config, conn)

        assert mock_fixup.call_count == 1
        # Positional signature: (context, target, table_kind, table_name, file_paths).
        # Pin the non-context args; context is a MagicMock so we don't compare it.
        passed_target, passed_kind, passed_table_name, passed_files = mock_fixup.call_args.args[1:]
        assert passed_target == target
        assert passed_kind == kind
        # Unsuffixed: actual table name equals the kind (target defaults events_table="events").
        assert passed_table_name == kind
        assert passed_files == files

    @parameterized.expand(
        [
            (
                "events_suffixed",
                register_files_with_duckling,
                "events",
                "events_acme",
                {"events_table": "events_acme"},
            ),
            (
                "persons_suffixed",
                register_persons_files_with_duckling,
                "persons",
                "persons_acme",
                {"persons_table": "persons_acme"},
            ),
        ]
    )
    @patch("posthog.dags.events_backfill_to_duckling._fixup_partition_values_for_added_files")
    @patch("posthog.dags.events_backfill_to_duckling._ducklake_file_partition_value_fixup_enabled", return_value=True)
    def test_fixup_passes_suffixed_table_name(
        self, _label, register_fn, kind, expected_table_name, target_overrides, _mock_enabled, mock_fixup
    ):
        # When DuckgresServerTeam.table_suffix is set, target.{events,persons}_table
        # carries the suffixed name. The fix-up trigger must pass that actual
        # name through so the catalog lookup targets the right table.
        target = DucklingTarget(
            team_id=2,
            organization_id="org-1",
            bucket="bkt",
            bucket_region="us-east-1",
            **target_overrides,
        )
        files = [f"s3://bkt/backfill/{kind}/2/year=2026/month=06/day=17/run1_0.parquet"]
        conn, _cur = _mock_glob_conn(files)
        config = DucklingBackfillConfig()

        register_fn(MagicMock(), target, "s3://bkt/.../run1_*.parquet", config, conn)

        passed_kind, passed_table_name = mock_fixup.call_args.args[2:4]
        assert passed_kind == kind
        assert passed_table_name == expected_table_name

    @parameterized.expand(
        [
            ("events", register_files_with_duckling),
            ("persons", register_persons_files_with_duckling),
        ]
    )
    @patch("posthog.dags.events_backfill_to_duckling._fixup_partition_values_for_added_files")
    @patch("posthog.dags.events_backfill_to_duckling._ducklake_file_partition_value_fixup_enabled", return_value=False)
    def test_fixup_skipped_when_flag_disabled(self, _label, register_fn, _mock_enabled, mock_fixup):
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        files = ["s3://bkt/backfill/events/2/year=2026/month=06/day=17/run1_0.parquet"]
        conn, _cur = _mock_glob_conn(files)
        config = DucklingBackfillConfig()

        register_fn(MagicMock(), target, "s3://bkt/.../run1_*.parquet", config, conn)

        mock_fixup.assert_not_called()

    @parameterized.expand(
        [
            ("events", register_files_with_duckling),
            ("persons", register_persons_files_with_duckling),
        ]
    )
    @patch("posthog.dags.events_backfill_to_duckling._fixup_partition_values_for_added_files")
    @patch("posthog.dags.events_backfill_to_duckling._ducklake_file_partition_value_fixup_enabled", return_value=True)
    def test_fixup_skipped_when_no_files_registered(self, _label, register_fn, _mock_enabled, mock_fixup):
        # Empty glob → no ducklake_add_data_files calls → no fixup either.
        target = DucklingTarget(team_id=2, organization_id="org-1", bucket="bkt", bucket_region="us-east-1")
        conn, _cur = _mock_glob_conn([])
        config = DucklingBackfillConfig()

        register_fn(MagicMock(), target, "s3://bkt/.../run1_*.parquet", config, conn)

        mock_fixup.assert_not_called()


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
        conn.execute(EVENTS_TABLE_DDL.format(catalog=DUCKLAKE_ALIAS, table="events"))
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
