from datetime import datetime

import pytest

from parameterized import parameterized

from posthog.dags.events_backfill_to_duckling import get_s3_path_for_duckling, parse_partition_key


class TestParsePartitionKey:
    @parameterized.expand(
        [
            ("12345_2024-01-15", (12345, "2024-01-15")),
            ("1_2020-12-31", (1, "2020-12-31")),
            ("999999_2025-06-01", (999999, "2025-06-01")),
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


class TestGetS3PathForDuckling:
    def test_basic_path(self):
        path = get_s3_path_for_duckling(
            bucket="my-bucket",
            team_id=12345,
            date=datetime(2024, 1, 15),
            run_id="abc123",
        )
        assert path == "s3://my-bucket/backfill/events/team_id=12345/year=2024/month=01/day=15/abc123.parquet"

    def test_different_dates(self):
        path = get_s3_path_for_duckling(
            bucket="test-bucket",
            team_id=1,
            date=datetime(2020, 12, 31),
            run_id="xyz",
        )
        assert path == "s3://test-bucket/backfill/events/team_id=1/year=2020/month=12/day=31/xyz.parquet"
