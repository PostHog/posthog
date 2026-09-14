import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, Optional
from urllib.parse import urlparse, urlunparse

from django.conf import settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.escape_sql import escape_hogql_identifier

from posthog.clickhouse.client.escape import substitute_params

_AWS_S3_ENDPOINT_RE = re.compile(r"s3(?:[.-][a-z0-9-]+)*\.amazonaws\.com(?:\.cn)?")
_AWS_S3_VIRTUAL_HOST_RE = re.compile(r"(?P<bucket>.+)\.(?P<endpoint>s3(?:[.-][a-z0-9-]+)*\.amazonaws\.com(?:\.cn)?)")
_AWS_REGION_RE = re.compile(r"(?:^|[.-])(?P<region>[a-z]{2,4}(?:-[a-z0-9]+)+-\d)(?:\.|$)")
_AZURE_BLOB_HOST_SUFFIX = ".blob.core.windows.net"
_FORMAT_LABELS = {
    "CSV": "CSV",
    "CSVWithNames": "CSV with headers",
    "JSONEachRow": "JSON",
    "Delta": "Delta",
    "DeltaS3Wrapper": "Delta",
}


@dataclass(frozen=True, kw_only=True)
class DuckDBS3Source:
    uri: str
    scope: str
    endpoint: str | None
    region: str
    use_ssl: bool
    url_style: Literal["path", "vhost"]


def _split_bucket_and_key(path: str) -> tuple[str, str] | None:
    bucket, separator, key = path.lstrip("/").partition("/")
    if not bucket or not separator or not key:
        return None
    return bucket, key


def _scope_for_s3_uri(uri: str) -> str:
    wildcard_positions = [position for token in ("*", "?", "[") if (position := uri.find(token)) >= 0]
    return uri[: min(wildcard_positions)] if wildcard_positions else uri


def _region_for_aws_endpoint(endpoint: str) -> str:
    match = _AWS_REGION_RE.search(endpoint)
    return match.group("region") if match else "us-east-1"


def parse_duckdb_s3_source(url: str) -> DuckDBS3Source | None:
    parsed = urlparse(url)
    if parsed.scheme == "s3":
        if not parsed.netloc or not parsed.path.lstrip("/"):
            return None
        uri = f"s3://{parsed.netloc}/{parsed.path.lstrip('/')}"
        return DuckDBS3Source(
            uri=uri,
            scope=_scope_for_s3_uri(uri),
            endpoint=None,
            region="us-east-1",
            use_ssl=True,
            url_style="vhost",
        )

    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        return None

    hostname = parsed.hostname.lower()
    if hostname.endswith(_AZURE_BLOB_HOST_SUFFIX):
        return None

    endpoint = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
    key = parsed.path.lstrip("/")
    virtual_host_match = _AWS_S3_VIRTUAL_HOST_RE.fullmatch(hostname)
    if virtual_host_match is not None:
        bucket = virtual_host_match.group("bucket")
        aws_endpoint = virtual_host_match.group("endpoint")
        endpoint = aws_endpoint if parsed.port is None else f"{aws_endpoint}:{parsed.port}"
        url_style: Literal["path", "vhost"] = "vhost"
        region = _region_for_aws_endpoint(aws_endpoint)
    else:
        location = _split_bucket_and_key(parsed.path)
        if location is None:
            return None
        bucket, key = location
        url_style = "path"
        region = _region_for_aws_endpoint(hostname) if _AWS_S3_ENDPOINT_RE.fullmatch(hostname) else "us-east-1"

    if not key:
        return None

    uri = f"s3://{bucket}/{key}"
    return DuckDBS3Source(
        uri=uri,
        scope=_scope_for_s3_uri(uri),
        endpoint=endpoint,
        region=region,
        use_ssl=parsed.scheme == "https",
        url_style=url_style,
    )


def build_function_call(
    url: str,
    format: str,
    queryable_folder: Optional[str] = None,
    access_key: Optional[str] = None,
    access_secret: Optional[str] = None,
    structure: Optional[str] = None,
    context: Optional[HogQLContext] = None,
    table_size_mib: Optional[float] = None,
) -> str:
    if access_key is None and access_secret is None and (settings.DEBUG or settings.TEST or settings.USE_LOCAL_SETUP):
        access_key = settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY
        access_secret = settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET

    use_s3_cluster = False
    if table_size_mib is not None and table_size_mib >= 1024:  # 1 GiB
        use_s3_cluster = True

    # If a table has a queryable url set, then use that directly
    if queryable_folder and format == "DeltaS3Wrapper":
        # Hack: Remove the last directory from the URL and add the queryable folder instead
        # TODO(Gilbert09): Fix this: simplify logic around how we construct the S3 and
        # http urls and make all url generation going through a single place
        parsed = urlparse(url)
        new_path = str(PurePosixPath(parsed.path).parent) + "/"
        new_url = urlunparse(parsed._replace(path=new_path))
        url = new_url + queryable_folder + "/**.parquet"
        format = "Parquet"

    raw_params: dict[str, str] = {}

    def add_param(value: str, is_sensitive: bool = True) -> str:
        if context is not None:
            if is_sensitive:
                return context.add_sensitive_value(value)
            return context.add_value(value)

        param_name = f"value_{len(raw_params.items())}"
        raw_params[param_name] = value
        return f"%({param_name})s"

    def return_expr(expr: str) -> str:
        if context is not None:
            return f"{expr})"

        return f"{substitute_params(expr, raw_params)})"

    # DeltaS3Wrapper format
    if format == "DeltaS3Wrapper":
        if url.endswith("/"):
            escaped_url = add_param(f"{url[:-1]}__query/**.parquet")
        else:
            escaped_url = add_param(f"{url}__query/**.parquet")

        if structure:
            escaped_structure = add_param(structure, False)

        if use_s3_cluster:
            expr = f"s3Cluster('posthog', {escaped_url}"
        else:
            expr = f"s3({escaped_url}"

        if access_key and access_secret:
            escaped_access_key = add_param(access_key)
            escaped_access_secret = add_param(access_secret)

            expr += f", {escaped_access_key}, {escaped_access_secret}"

        expr += ", 'Parquet'"

        if structure:
            expr += f", {escaped_structure}"

        return return_expr(expr)

    # Delta format
    if format == "Delta":
        escaped_url = add_param(url)
        if structure:
            escaped_structure = add_param(structure, False)

        expr = f"deltaLake({escaped_url}"

        if access_key and access_secret:
            escaped_access_key = add_param(access_key)
            escaped_access_secret = add_param(access_secret)

            expr += f", {escaped_access_key}, {escaped_access_secret}"

        expr += ", 'Parquet'"

        if structure:
            expr += f", {escaped_structure}"

        return return_expr(expr)

    # Azure
    if re.match(r"^https:\/\/.+\.blob\.core\.windows\.net\/", url):
        regex_result = re.search(r"(https:\/\/.+\.blob\.core\.windows\.net)\/(.+?)\/(.*)", url)
        if regex_result is None:
            raise ExposedHogQLError("Can't parse Azure blob storage URL")

        groups = regex_result.groups()
        if len(groups) < 3:
            raise ExposedHogQLError("Can't parse Azure blob storage URL")

        storage_account_url = add_param(groups[0])
        container = add_param(groups[1])
        blob_path = add_param(groups[2])

        if not access_key or not access_secret:
            raise ExposedHogQLError("Azure blob storage has no access key or secret")

        escaped_access_key = add_param(access_key)
        escaped_access_secret = add_param(access_secret)
        escaped_format = add_param(format, False)

        expr = f"azureBlobStorage({storage_account_url}, {container}, {blob_path}, {escaped_access_key}, {escaped_access_secret}, {escaped_format}, 'auto'"

        if structure:
            escaped_structure = add_param(structure, False)
            expr += f", {escaped_structure}"

        return return_expr(expr)

    # S3
    escaped_url = add_param(url)
    escaped_format = add_param(format, False)
    if structure:
        escaped_structure = add_param(structure, False)

    if use_s3_cluster:
        expr = f"s3Cluster('posthog', {escaped_url}"
    else:
        expr = f"s3({escaped_url}"

    if access_key and access_secret:
        escaped_access_key = add_param(access_key)
        escaped_access_secret = add_param(access_secret)

        expr += f", {escaped_access_key}, {escaped_access_secret}"

    expr += f", {escaped_format}"

    if structure:
        expr += f", {escaped_structure}"

    return return_expr(expr)


class S3Table(FunctionCallTable):
    requires_args: bool = False
    url: str
    format: str = "CSVWithNames"
    queryable_folder: Optional[str] = None
    access_key: Optional[str] = None
    access_secret: Optional[str] = None
    structure: Optional[str] = None
    table_id: Optional[str] = None
    table_size_mib: Optional[float] = None
    # Set for connector-synced warehouse tables (backed by an ExternalDataSource); None for self-managed S3 tables.
    # Used to attribute query execution back to the source that was synced, for usage telemetry.
    external_data_source_id: Optional[str] = None
    source_type: Optional[str] = None

    def to_printed_hogql(self):
        return escape_hogql_identifier(self.name)

    def to_printed_clickhouse(self, context):
        return build_function_call(
            url=self.url,
            queryable_folder=self.queryable_folder,
            format=self.format,
            access_key=self.access_key,
            access_secret=self.access_secret,
            structure=self.structure,
            context=context,
            table_size_mib=self.table_size_mib,
        )

    def to_printed_duckdb(self, context: HogQLContext) -> str:
        if self.format != "Parquet":
            format_label = _FORMAT_LABELS.get(self.format, self.format)
            raise ExposedHogQLError(
                "DuckLake currently supports Parquet self-managed tables only. "
                f"Support for {format_label} is coming soon. "
                "Use Parquet or run the query without DuckLake for now."
            )

        source = parse_duckdb_s3_source(self.url)
        if source is None:
            hostname = urlparse(self.url).hostname
            if hostname is not None and hostname.lower().endswith(_AZURE_BLOB_HOST_SUFFIX):
                raise ExposedHogQLError(
                    "DuckLake currently supports S3-compatible self-managed sources only. "
                    "Support for Azure Blob Storage is coming soon. "
                    "Run the query without DuckLake for now."
                )
            raise ExposedHogQLError(
                "DuckLake currently supports S3-compatible self-managed sources only. "
                "Use an S3-compatible URL or run the query without DuckLake for now."
            )

        return f"read_parquet({context.add_value(source.uri)}, hive_partitioning = false)"


class DataWarehouseTable(S3Table):
    """A table placeholder for checking warehouse tables"""

    pass
