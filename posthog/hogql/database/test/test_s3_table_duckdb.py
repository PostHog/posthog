import re
import tempfile
from pathlib import Path

import pytest

import duckdb
from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.s3_table import (
    DuckDBAzureSource,
    DuckDBS3Source,
    S3Table,
    parse_duckdb_azure_source,
    parse_duckdb_s3_source,
)
from posthog.hogql.errors import ExposedHogQLError


class TestParseDuckDBS3Source:
    @parameterized.expand(
        [
            (
                "aws_virtual_host",
                "https://my-bucket.s3.amazonaws.com/data/*.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/*.parquet",
                    scope="s3://my-bucket/data/",
                    endpoint="s3.amazonaws.com",
                    region="us-east-1",
                    use_ssl=True,
                    url_style="vhost",
                ),
            ),
            (
                "aws_regional_virtual_host",
                "https://my-bucket.s3.eu-west-2.amazonaws.com/data/items.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/items.parquet",
                    scope="s3://my-bucket/data/items.parquet",
                    endpoint="s3.eu-west-2.amazonaws.com",
                    region="eu-west-2",
                    use_ssl=True,
                    url_style="vhost",
                ),
            ),
            (
                "aws_path_style",
                "https://s3.us-west-1.amazonaws.com/my-bucket/data/*.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/*.parquet",
                    scope="s3://my-bucket/data/",
                    endpoint="s3.us-west-1.amazonaws.com",
                    region="us-west-1",
                    use_ssl=True,
                    url_style="path",
                ),
            ),
            (
                "aws_china_region",
                "https://my-bucket.s3.cn-north-1.amazonaws.com.cn/data/items.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/items.parquet",
                    scope="s3://my-bucket/data/items.parquet",
                    endpoint="s3.cn-north-1.amazonaws.com.cn",
                    region="cn-north-1",
                    use_ssl=True,
                    url_style="vhost",
                ),
            ),
            (
                "google_cloud_storage",
                "https://storage.googleapis.com/my-bucket/data/*.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/*.parquet",
                    scope="s3://my-bucket/data/",
                    endpoint="storage.googleapis.com",
                    region="us-east-1",
                    use_ssl=True,
                    url_style="path",
                ),
            ),
            (
                "google_cloud_storage_virtual_host",
                "https://my-bucket.storage.googleapis.com/data/items.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/items.parquet",
                    scope="s3://my-bucket/data/items.parquet",
                    endpoint="storage.googleapis.com",
                    region="us-east-1",
                    use_ssl=True,
                    url_style="vhost",
                ),
            ),
            (
                "cloudflare_r2",
                "https://account-id.r2.cloudflarestorage.com/my-bucket/data/*.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/*.parquet",
                    scope="s3://my-bucket/data/",
                    endpoint="account-id.r2.cloudflarestorage.com",
                    region="us-east-1",
                    use_ssl=True,
                    url_style="path",
                ),
            ),
            (
                "digitalocean_spaces_virtual_host",
                "https://my-bucket.nyc3.digitaloceanspaces.com/data/items.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/items.parquet",
                    scope="s3://my-bucket/data/items.parquet",
                    endpoint="nyc3.digitaloceanspaces.com",
                    region="us-east-1",
                    use_ssl=True,
                    url_style="vhost",
                ),
            ),
            (
                "wasabi_virtual_host",
                "https://my-bucket.s3.eu-central-1.wasabisys.com/data/items.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/items.parquet",
                    scope="s3://my-bucket/data/items.parquet",
                    endpoint="s3.eu-central-1.wasabisys.com",
                    region="eu-central-1",
                    use_ssl=True,
                    url_style="vhost",
                ),
            ),
            (
                "backblaze_virtual_host",
                "https://my-bucket.s3.us-west-004.backblazeb2.com/data/items.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/items.parquet",
                    scope="s3://my-bucket/data/items.parquet",
                    endpoint="s3.us-west-004.backblazeb2.com",
                    region="us-west-004",
                    use_ssl=True,
                    url_style="vhost",
                ),
            ),
            (
                "local_s3_compatible",
                "http://objectstorage:19000/my-bucket/data/items.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/items.parquet",
                    scope="s3://my-bucket/data/items.parquet",
                    endpoint="objectstorage:19000",
                    region="us-east-1",
                    use_ssl=False,
                    url_style="path",
                ),
            ),
            (
                "s3_uri",
                "s3://my-bucket/data/*.parquet",
                DuckDBS3Source(
                    uri="s3://my-bucket/data/*.parquet",
                    scope="s3://my-bucket/data/",
                    endpoint=None,
                    region="us-east-1",
                    use_ssl=True,
                    url_style="vhost",
                ),
            ),
            (
                "azure_is_not_s3_compatible",
                "https://account.blob.core.windows.net/container/data/*.parquet",
                None,
            ),
            ("missing_object_key", "https://storage.googleapis.com/my-bucket", None),
        ]
    )
    def test_parses_provider_url(
        self,
        _name: str,
        url: str,
        expected: DuckDBS3Source | None,
    ) -> None:
        assert parse_duckdb_s3_source(url) == expected


class TestParseDuckDBAzureSource:
    @parameterized.expand(
        [
            (
                "glob",
                "https://account.blob.core.windows.net/container/data/*.parquet",
                DuckDBAzureSource(
                    uri="az://account.blob.core.windows.net/container/data/*.parquet",
                    scope="az://account.blob.core.windows.net/container/data/",
                    account_name="account",
                ),
            ),
            (
                "exact_file",
                "https://account.blob.core.windows.net/container/data/items.parquet",
                DuckDBAzureSource(
                    uri="az://account.blob.core.windows.net/container/data/items.parquet",
                    scope="az://account.blob.core.windows.net/container/data/",
                    account_name="account",
                ),
            ),
            ("missing_object_key", "https://account.blob.core.windows.net/container", None),
            ("non_azure_host", "https://storage.googleapis.com/bucket/items.parquet", None),
        ]
    )
    def test_parses_azure_blob_url(
        self,
        _name: str,
        url: str,
        expected: DuckDBAzureSource | None,
    ) -> None:
        assert parse_duckdb_azure_source(url) == expected


class TestS3TableDuckDBPrinting:
    @parameterized.expand(
        [
            ("parquet", "Parquet", "data/*.parquet", "read_parquet(", ("hive_partitioning = false",), False),
            (
                "csv_with_headers",
                "CSVWithNames",
                "data/*.csv",
                "read_csv(",
                ("header = true", "hive_partitioning = false"),
                False,
            ),
            (
                "csv_without_headers",
                "CSV",
                "data/*.csv",
                "read_csv(",
                ("header = false", "names = [", "hive_partitioning = false"),
                True,
            ),
            (
                "newline_delimited_json",
                "JSONEachRow",
                "data/*.jsonl",
                "read_json(",
                ("format = 'newline_delimited'", "hive_partitioning = false"),
                False,
            ),
            ("delta", "Delta", "data/orders", "delta_scan(", (), False),
        ]
    )
    def test_supported_format_uses_native_reader_and_keeps_credentials_out_of_sql(
        self,
        _name: str,
        table_format: str,
        path: str,
        reader: str,
        expected_options: tuple[str, ...],
        binds_column_names: bool,
    ) -> None:
        context = HogQLContext(team_id=1)
        table = S3Table(
            name="orders",
            url=f"https://my-bucket.s3.amazonaws.com/{path}",
            format=table_format,
            access_key="access-key",
            access_secret="access-secret",
            column_names=("order id", "amount"),
            fields={},
        )

        sql = table.to_printed_duckdb(context)

        assert sql.startswith(reader)
        assert all(option in sql for option in expected_options)
        expected_values = [f"s3://my-bucket/{path}"]
        if binds_column_names:
            expected_values.extend(["order id", "amount"])
        assert list(context.values.values()) == expected_values
        assert "access-key" not in sql
        assert "access-secret" not in sql

    def test_unsupported_format_has_clear_error(self) -> None:
        table = S3Table(
            name="orders",
            url="https://my-bucket.s3.amazonaws.com/data/*.avro",
            format="Avro",
            fields={},
        )

        with pytest.raises(ExposedHogQLError, match="can't read this self-managed table format"):
            table.to_printed_duckdb(HogQLContext(team_id=1))

    @parameterized.expand(
        [
            ("csv_with_headers", "CSVWithNames", "order_id,amount\n1,12.5\n", (), ["order_id", "amount"]),
            ("csv_without_headers", "CSV", "1,12.5\n", ("order_id", "amount"), ["order_id", "amount"]),
            (
                "newline_delimited_json",
                "JSONEachRow",
                '{"order_id":1,"amount":12.5}\n',
                (),
                ["order_id", "amount"],
            ),
        ]
    )
    def test_row_format_reader_executes_with_saved_column_names(
        self,
        _name: str,
        table_format: str,
        contents: str,
        column_names: tuple[str, ...],
        expected_columns: list[str],
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "orders"
            source_path.write_text(contents)
            context = HogQLContext(team_id=1)
            table = S3Table(
                name="orders",
                url="s3://bucket/orders",
                format=table_format,
                access_key="access-key",
                access_secret="access-secret",
                column_names=column_names,
                fields={},
            )

            sql = table.to_printed_duckdb(context)
            positional_sql = re.sub(r"%\([^)]+\)s", "?", sql)
            values = list(context.values.values())
            values[0] = str(source_path)

            with duckdb.connect() as connection:
                result = connection.execute(f"SELECT * FROM {positional_sql}", values)
                actual_columns = [description[0] for description in result.description]
                rows = result.fetchall()

        assert actual_columns == expected_columns
        assert rows == [(1, 12.5)]

    @parameterized.expand(
        [
            ("csv_with_headers", "CSVWithNames", 'order_id,amount\n"12345","12.5"\n'),
            ("csv_without_headers", "CSV", '"12345","12.5"\n'),
        ]
    )
    def test_csv_reader_keeps_saved_column_types(self, _name: str, table_format: str, contents: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "orders"
            source_path.write_text(contents)
            context = HogQLContext(team_id=1)
            table = S3Table(
                name="orders",
                url="s3://bucket/orders",
                format=table_format,
                access_key="access-key",
                access_secret="access-secret",
                column_names=("order_id", "amount"),
                clickhouse_column_types=("String", "Decimal256(2)"),
                fields={},
            )

            sql = table.to_printed_duckdb(context)
            positional_sql = re.sub(r"%\([^)]+\)s", "?", sql)
            values = list(context.values.values())
            values[0] = str(source_path)

            with duckdb.connect() as connection:
                rows = connection.execute(f"SELECT * FROM {positional_sql}", values).fetchall()

        assert rows == [("12345", 12.5)]

    def test_csv_reader_preserves_unsigned_integer_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "orders"
            source_path.write_text("order_id\n18446744073709551615\n")
            context = HogQLContext(team_id=1)
            table = S3Table(
                name="orders",
                url="s3://bucket/orders",
                format="CSVWithNames",
                access_key="access-key",
                access_secret="access-secret",
                column_names=("order_id",),
                clickhouse_column_types=("UInt64",),
                fields={},
            )

            sql = table.to_printed_duckdb(context)
            positional_sql = re.sub(r"%\([^)]+\)s", "?", sql)
            values = list(context.values.values())
            values[0] = str(source_path)

            with duckdb.connect() as connection:
                rows = connection.execute(f"SELECT * FROM {positional_sql}", values).fetchall()

        assert rows == [(18446744073709551615,)]

    def test_azure_uses_native_reader(self) -> None:
        context = HogQLContext(team_id=1)
        table = S3Table(
            name="orders",
            url="https://account.blob.core.windows.net/container/data/*.parquet",
            format="Parquet",
            access_key="account",
            access_secret="ZmFrZS1hY2NvdW50LWtleQ==",
            fields={},
        )

        sql = table.to_printed_duckdb(context)

        assert sql.startswith("read_parquet(")
        assert list(context.values.values()) == ["az://account.blob.core.windows.net/container/data/*.parquet"]

    @parameterized.expand(
        [
            ("account_name_mismatch", "otheraccount", "ZmFrZQ=="),
            ("connection_string_injection", "account", "ZmFrZQ==;BlobEndpoint=http://127.0.0.1"),
        ]
    )
    def test_invalid_azure_credentials_have_clear_error(
        self,
        _name: str,
        access_key: str,
        access_secret: str,
    ) -> None:
        table = S3Table(
            name="orders",
            url="https://account.blob.core.windows.net/container/data/*.parquet",
            format="Parquet",
            access_key=access_key,
            access_secret=access_secret,
            fields={},
        )

        with pytest.raises(ExposedHogQLError, match="can't use these Azure Blob Storage credentials"):
            table.to_printed_duckdb(HogQLContext(team_id=1))

    @parameterized.expand(
        [
            ("missing_access_key", None, "secret"),
            ("missing_access_secret", "key", None),
            ("missing_both", None, None),
        ]
    )
    def test_missing_credentials_has_clear_error(
        self,
        _name: str,
        access_key: str | None,
        access_secret: str | None,
    ) -> None:
        table = S3Table(
            name="orders",
            url="https://my-bucket.s3.amazonaws.com/data/*.parquet",
            format="Parquet",
            access_key=access_key,
            access_secret=access_secret,
            fields={},
        )

        with pytest.raises(ExposedHogQLError, match="object storage credentials are missing"):
            table.to_printed_duckdb(HogQLContext(team_id=1))
