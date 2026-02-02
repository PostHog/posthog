import pytest

import duckdb
from parameterized import parameterized

from posthog.dags.events_backfill_to_duckling import (
    EVENTS_TABLE_DDL,
    EXPECTED_DUCKLAKE_COLUMNS,
    EXPECTED_DUCKLAKE_PERSONS_COLUMNS,
    PERSONS_TABLE_DDL,
    _validate_identifier,
    get_s3_url_for_clickhouse,
    parse_partition_key,
    table_exists,
)


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
        ddl = EVENTS_TABLE_DDL.format(catalog="memory")
        conn.execute(ddl)

        # Verify table was created with expected columns
        result = conn.execute("DESCRIBE memory.posthog.events").fetchall()
        column_names = {row[0] for row in result}

        assert column_names == EXPECTED_DUCKLAKE_COLUMNS
        conn.close()

    def test_events_ddl_is_idempotent(self):
        conn = duckdb.connect()
        ddl = EVENTS_TABLE_DDL.format(catalog="memory")
        # Should not raise on second execution
        conn.execute(ddl)
        conn.execute(ddl)
        conn.close()


class TestPersonsDDL:
    def test_persons_ddl_is_valid_sql(self):
        conn = duckdb.connect()
        ddl = PERSONS_TABLE_DDL.format(catalog="memory")
        conn.execute(ddl)

        # Verify table was created with expected columns
        result = conn.execute("DESCRIBE memory.posthog.persons").fetchall()
        column_names = {row[0] for row in result}

        assert column_names == EXPECTED_DUCKLAKE_PERSONS_COLUMNS
        conn.close()

    def test_persons_ddl_is_idempotent(self):
        conn = duckdb.connect()
        ddl = PERSONS_TABLE_DDL.format(catalog="memory")
        # Should not raise on second execution
        conn.execute(ddl)
        conn.execute(ddl)
        conn.close()
