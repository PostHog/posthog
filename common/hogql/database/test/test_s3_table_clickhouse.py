"""Integration tests for S3/Parquet queries via ClickHouse."""

import uuid
import datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.config import Config

from posthog.clickhouse.client import sync_execute

MINIO_ENDPOINT = "http://localhost:19000"
MINIO_CH_ENDPOINT = "http://objectstorage:19000"
MINIO_ACCESS_KEY = "object_storage_root_user"
MINIO_SECRET_KEY = "object_storage_root_password"
BUCKET = "test-s3-tz-bug"


def _upload_parquet_to_minio(table: pa.Table, key: str) -> str:
    """Write a pyarrow table to MinIO and return the ClickHouse-accessible URL."""
    local_path = f"/tmp/{uuid.uuid4().hex}.parquet"
    pq.write_table(table, local_path)

    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )
    try:
        s3.create_bucket(Bucket=BUCKET)
    except s3.exceptions.BucketAlreadyOwnedByYou:
        pass

    s3.upload_file(local_path, BUCKET, key)
    return f"{MINIO_CH_ENDPOINT}/{BUCKET}/{key}"


def _s3_query(url: str, schema: str, sql: str) -> list:
    """Execute a query against an S3 Parquet file."""
    full_sql = sql.format(s3_source=f"s3('{url}', '{MINIO_ACCESS_KEY}', '{MINIO_SECRET_KEY}', 'Parquet', '{schema}')")
    return sync_execute(full_sql)


class TestS3ParquetTimezoneConversion(ClickhouseTestMixin, BaseTest):
    """Tests for toTimeZone() on Nullable(DateTime64) columns from S3/Parquet sources.

    Documents a ClickHouse 25.12 bug where toTimeZone() returns NULL in SELECT
    when the same expression appears in the WHERE clause.

    Issue: https://github.com/ClickHouse/ClickHouse/pull/90635
    """

    url: str
    schema: str

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        table = pa.table(
            {
                "id": ["row1", "row2", "row3", None],
                "team_id": [1, 1, 2, 1],
                "created_at": pa.array(
                    [
                        datetime.datetime(2024, 5, 1, 10, 0, 0),
                        datetime.datetime(2024, 6, 15, 14, 30, 0),
                        datetime.datetime(2024, 4, 20, 8, 0, 0),
                        None,
                    ],
                    type=pa.timestamp("us"),
                ),
            }
        )
        cls.url = _upload_parquet_to_minio(table, "tz_bug_test.parquet")
        cls.schema = "`id` Nullable(String), `team_id` Nullable(Int32), `created_at` Nullable(DateTime64(6))"

    def test_toTimeZone_works_without_where(self):
        rows = _s3_query(
            self.url,
            self.schema,
            "SELECT id, toTimeZone(created_at, 'US/Pacific') AS tz FROM {s3_source} WHERE id IS NOT NULL ORDER BY id",
        )
        assert len(rows) == 3
        for row in rows:
            assert row[1] is not None, f"toTimeZone returned NULL for id={row[0]}"

    def test_toTimeZone_returns_value_when_same_expression_in_where(self):
        """When toTimeZone(col, 'TZ') appears in both SELECT and WHERE on an S3 source,
        the SELECT result should not become NULL."""
        rows = _s3_query(
            self.url,
            self.schema,
            """SELECT
                id,
                toTimeZone(created_at, 'US/Pacific') AS tz_pacific,
                toTimeZone(created_at, 'Asia/Yekaterinburg') AS tz_yek
            FROM {s3_source}
            WHERE greaterOrEquals(toTimeZone(created_at, 'US/Pacific'), '2024-04-17')
            ORDER BY id""",
        )
        assert len(rows) == 3
        for row in rows:
            _id, tz_pacific, tz_yek = row
            # Asia/Yekaterinburg works because it's not in the WHERE clause
            assert tz_yek is not None, f"Asia/Yekaterinburg unexpectedly NULL for id={_id}"
            # US/Pacific is NULL due to the bug (same expression in WHERE)
            assert tz_pacific is not None, f"US/Pacific is NULL for id={_id} — ClickHouse S3 toTimeZone bug"

    def test_workaround_assumeNotNull_in_where(self):
        """Wrapping the WHERE expression with assumeNotNull breaks CSE and avoids the bug."""
        rows = _s3_query(
            self.url,
            self.schema,
            """SELECT
                id,
                toTimeZone(created_at, 'US/Pacific') AS tz_pacific
            FROM {s3_source}
            WHERE greaterOrEquals(toTimeZone(assumeNotNull(created_at), 'US/Pacific'), '2024-04-17')
            ORDER BY id""",
        )
        assert len(rows) == 3
        for row in rows:
            assert row[1] is not None, f"toTimeZone returned NULL for id={row[0]} even with workaround"

    def test_not_affected_on_mergetree(self):
        """The bug does not affect regular MergeTree tables."""
        table_name = "posthog_test.test_tz_bug_mergetree"
        sync_execute(f"DROP TABLE IF EXISTS {table_name}")
        sync_execute(f"""
            CREATE TABLE {table_name} (
                id String,
                created_at Nullable(DateTime64(6))
            ) ENGINE = MergeTree() ORDER BY id
        """)
        sync_execute(f"""
            INSERT INTO {table_name} VALUES
                ('row1', '2024-05-01 10:00:00'),
                ('row2', '2024-06-15 14:30:00'),
                ('row3', '2024-04-20 08:00:00')
        """)
        try:
            rows = sync_execute(f"""
                SELECT id, toTimeZone(created_at, 'US/Pacific') AS tz_pacific
                FROM {table_name}
                WHERE greaterOrEquals(toTimeZone(created_at, 'US/Pacific'), '2024-04-17')
                ORDER BY id
            """)
            assert len(rows) == 3
            for row in rows:
                assert row[1] is not None, f"MergeTree: toTimeZone NULL for id={row[0]}"
        finally:
            sync_execute(f"DROP TABLE IF EXISTS {table_name}")
