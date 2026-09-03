import pytest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.s3_table import DuckDBS3Source, S3Table, parse_duckdb_s3_source
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


class TestS3TableDuckDBPrinting:
    def test_parquet_uses_native_reader_without_credentials(self) -> None:
        context = HogQLContext(team_id=1)
        table = S3Table(
            name="orders",
            url="https://my-bucket.s3.amazonaws.com/data/*.parquet",
            format="Parquet",
            access_key="access-key",
            access_secret="access-secret",
            fields={},
        )

        sql = table.to_printed_duckdb(context)

        assert sql.startswith("read_parquet(")
        assert "hive_partitioning = false" in sql
        assert list(context.values.values()) == ["s3://my-bucket/data/*.parquet"]
        assert "access-key" not in sql
        assert "access-secret" not in sql

    def test_non_parquet_format_has_clear_error(self) -> None:
        table = S3Table(
            name="orders",
            url="https://my-bucket.s3.amazonaws.com/data/*.csv",
            format="CSVWithNames",
            fields={},
        )

        with pytest.raises(ExposedHogQLError, match="Support for CSV with headers is coming soon"):
            table.to_printed_duckdb(HogQLContext(team_id=1))

    def test_azure_has_clear_error(self) -> None:
        table = S3Table(
            name="orders",
            url="https://account.blob.core.windows.net/container/data/*.parquet",
            format="Parquet",
            fields={},
        )

        with pytest.raises(ExposedHogQLError, match="Support for Azure Blob Storage is coming soon"):
            table.to_printed_duckdb(HogQLContext(team_id=1))
