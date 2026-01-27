from datetime import datetime

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.dags.events_backfill_to_ducklake import (
    EVENTS_COLUMNS,
    EXPECTED_DUCKLAKE_COLUMNS,
    get_partition_where_clause,
    get_s3_function_args,
    get_s3_path_for_partition,
    tags_for_events_partition,
)


class TestTagsForEventsPartition:
    @parameterized.expand(
        [
            ("2025-01-15", {"events_ducklake_partition": "dl_20250115"}),
            ("2025-10-31", {"events_ducklake_partition": "dl_20251031"}),
            ("2025-11-01", {"events_ducklake_partition": "dl_20251101"}),
            ("2019-01-01", {"events_ducklake_partition": "dl_20190101"}),
        ]
    )
    def test_tags_for_events_partition(self, partition_key, expected_tags):
        result = tags_for_events_partition(partition_key)
        assert result == expected_tags


class TestGetS3PathForPartition:
    @parameterized.expand(
        [
            (
                "posthog-ducklake-dev",
                "us-east-1",
                "mod64eq0",
                datetime(2025, 1, 15),
                "chunk_0000_run_abc12345",
                False,
                "https://posthog-ducklake-dev.s3.us-east-1.amazonaws.com/backfill/events/team_id=mod64eq0/year=2025/month=01/day=15/chunk_0000_run_abc12345.parquet",
            ),
            (
                "posthog-ducklake-prod-eu",
                "eu-central-1",
                "mod64eq63",
                datetime(2025, 12, 31),
                "chunk_0063_run_xyz98765",
                False,
                "https://posthog-ducklake-prod-eu.s3.eu-central-1.amazonaws.com/backfill/events/team_id=mod64eq63/year=2025/month=12/day=31/chunk_0063_run_xyz98765.parquet",
            ),
        ]
    )
    def test_get_s3_path_for_partition_prod(
        self,
        bucket,
        region,
        team_id,
        date,
        chunk_id,
        is_local,
        expected_path,
    ):
        result = get_s3_path_for_partition(
            bucket=bucket,
            region=region,
            team_id=team_id,
            date=date,
            chunk_id=chunk_id,
            is_local=is_local,
        )
        assert result == expected_path

    def test_get_s3_path_for_partition_local(self):
        with patch(
            "posthog.dags.events_backfill_to_ducklake.OBJECT_STORAGE_ENDPOINT",
            "http://localhost:19000",
        ):
            result = get_s3_path_for_partition(
                bucket="posthog-ducklake-dev",
                region="us-east-1",
                team_id="mod64eq0",
                date=datetime(2025, 1, 15),
                chunk_id="chunk_0000_run_abc12345",
                is_local=True,
            )
            assert (
                result
                == "http://localhost:19000/posthog-ducklake-dev/backfill/events/team_id=mod64eq0/year=2025/month=01/day=15/chunk_0000_run_abc12345.parquet"
            )


class TestGetS3FunctionArgs:
    def test_production_mode(self):
        args, safe_args = get_s3_function_args(
            "https://bucket.s3.us-east-1.amazonaws.com/path/file.parquet",
            is_local=False,
        )
        assert args == "'https://bucket.s3.us-east-1.amazonaws.com/path/file.parquet', 'Parquet'"
        assert safe_args == args

    def test_local_mode_redacts_credentials(self):
        with patch(
            "posthog.dags.events_backfill_to_ducklake.OBJECT_STORAGE_ACCESS_KEY_ID",
            "test_key_id",
        ):
            with patch(
                "posthog.dags.events_backfill_to_ducklake.OBJECT_STORAGE_SECRET_ACCESS_KEY",
                "test_secret",
            ):
                args, safe_args = get_s3_function_args(
                    "http://localhost:19000/bucket/path/file.parquet",
                    is_local=True,
                )
                assert "test_key_id" in args
                assert "test_secret" in args
                assert "[REDACTED]" in safe_args
                assert "test_key_id" not in safe_args
                assert "test_secret" not in safe_args


class TestGetPartitionWhereClause:
    def test_generates_correct_where_clause(self):
        mock_context = MagicMock()
        mock_context.partition_time_window.start = datetime(2025, 1, 15)
        mock_context.partition_time_window.end = datetime(2025, 1, 16)

        result = get_partition_where_clause(mock_context)

        assert result == "toDate(timestamp) >= '2025-01-15' AND toDate(timestamp) < '2025-01-16'"

    def test_custom_timestamp_field(self):
        mock_context = MagicMock()
        mock_context.partition_time_window.start = datetime(2025, 1, 15)
        mock_context.partition_time_window.end = datetime(2025, 1, 16)

        result = get_partition_where_clause(mock_context, timestamp_field="created_at")

        assert result == "toDate(created_at) >= '2025-01-15' AND toDate(created_at) < '2025-01-16'"


class TestEventsColumnsSchema:
    def test_events_columns_has_expected_columns(self):
        columns_in_sql = set()
        for col in EVENTS_COLUMNS.strip().split("\n"):
            if col.strip():
                # Handle columns with 'AS' alias (e.g., "toString(uuid) as uuid")
                if " as " in col.lower():
                    # Extract the alias after 'as'
                    alias = col.lower().split(" as ")[1].split(",")[0].strip()
                    columns_in_sql.add(alias)
                else:
                    # No alias, use the column name directly
                    columns_in_sql.add(col.strip().split()[0].rstrip(","))

        assert "uuid" in columns_in_sql
        assert "event" in columns_in_sql
        assert "properties" in columns_in_sql
        assert "timestamp" in columns_in_sql
        assert "team_id" in columns_in_sql
        assert "project_id" in columns_in_sql
        assert "distinct_id" in columns_in_sql
        assert "person_id" in columns_in_sql
        assert "person_mode" in columns_in_sql
        assert "historical_migration" in columns_in_sql

    def test_expected_ducklake_columns_matches_export(self):
        export_columns = {
            "uuid",
            "event",
            "properties",
            "timestamp",
            "team_id",
            "project_id",
            "distinct_id",
            "elements_chain",
            "created_at",
            "person_id",
            "person_created_at",
            "person_properties",
            "group0_properties",
            "group1_properties",
            "group2_properties",
            "group3_properties",
            "group4_properties",
            "group0_created_at",
            "group1_created_at",
            "group2_created_at",
            "group3_created_at",
            "group4_created_at",
            "person_mode",
            "historical_migration",
            "_inserted_at",
        }
        assert EXPECTED_DUCKLAKE_COLUMNS == export_columns
