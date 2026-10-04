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


class _FunctionCallParams:
    def __init__(self, context: Optional[HogQLContext]) -> None:
        self._context = context
        self._raw_params: dict[str, str] = {}

    def add(self, value: str, is_sensitive: bool = True) -> str:
        if self._context is not None:
            if is_sensitive:
                return self._context.add_sensitive_value(value)
            return self._context.add_value(value)

        param_name = f"value_{len(self._raw_params)}"
        self._raw_params[param_name] = value
        return f"%({param_name})s"

    def finish(self, expr: str) -> str:
        if self._context is not None:
            return f"{expr})"

        return f"{substitute_params(expr, self._raw_params)})"


def _s3_function(table_size_mib: Optional[float]) -> str:
    if table_size_mib is not None and table_size_mib >= 1024:  # 1 GiB
        return "s3Cluster('posthog', "
    return "s3("


def _queryable_folder_url(url: str, queryable_folder: str) -> str:
    # Hack: Remove the last directory from the URL and add the queryable folder instead
    # TODO(Gilbert09): Fix this: simplify logic around how we construct the S3 and
    # http urls and make all url generation going through a single place
    parsed = urlparse(url)
    new_path = str(PurePosixPath(parsed.path).parent) + "/"
    new_url = urlunparse(parsed._replace(path=new_path))
    return new_url + queryable_folder + "/**.parquet"


def _url_table_function(
    params: _FunctionCallParams,
    function: str,
    url: str,
    format: Optional[str],
    structure: Optional[str],
    access_key: Optional[str],
    access_secret: Optional[str],
) -> str:
    """Renders `s3`, `s3Cluster` and `deltaLake` calls, which share one argument order.

    A `format` of None renders the literal 'Parquet' instead of a parameter.
    """
    escaped_url = params.add(url)
    format_arg = params.add(format, False) if format else "'Parquet'"
    escaped_structure = params.add(structure, False) if structure else None

    expr = f"{function}{escaped_url}"

    if access_key and access_secret:
        escaped_access_key = params.add(access_key)
        escaped_access_secret = params.add(access_secret)
        expr += f", {escaped_access_key}, {escaped_access_secret}"

    expr += f", {format_arg}"

    if escaped_structure:
        expr += f", {escaped_structure}"

    return params.finish(expr)


def _azure_blob_storage_call(
    params: _FunctionCallParams,
    url: str,
    format: str,
    structure: Optional[str],
    access_key: Optional[str],
    access_secret: Optional[str],
) -> str:
    regex_result = re.search(r"(https:\/\/.+\.blob\.core\.windows\.net)\/(.+?)\/(.*)", url)
    if regex_result is None:
        raise ExposedHogQLError("Can't parse Azure blob storage URL")

    groups = regex_result.groups()
    if len(groups) < 3:
        raise ExposedHogQLError("Can't parse Azure blob storage URL")

    storage_account_url = params.add(groups[0])
    container = params.add(groups[1])
    blob_path = params.add(groups[2])

    if not access_key or not access_secret:
        raise ExposedHogQLError("Azure blob storage has no access key or secret")

    escaped_access_key = params.add(access_key)
    escaped_access_secret = params.add(access_secret)
    escaped_format = params.add(format, False)

    expr = f"azureBlobStorage({storage_account_url}, {container}, {blob_path}, {escaped_access_key}, {escaped_access_secret}, {escaped_format}, 'auto'"

    if structure:
        escaped_structure = params.add(structure, False)
        expr += f", {escaped_structure}"

    return params.finish(expr)


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

    # If a table has a queryable url set, then use that directly
    if queryable_folder and format == "DeltaS3Wrapper":
        url = _queryable_folder_url(url, queryable_folder)
        format = "Parquet"

    params = _FunctionCallParams(context)

    if format == "DeltaS3Wrapper":
        query_url = f"{url.removesuffix('/')}__query/**.parquet"
        return _url_table_function(
            params, _s3_function(table_size_mib), query_url, None, structure, access_key, access_secret
        )

    if format == "Delta":
        return _url_table_function(params, "deltaLake(", url, None, structure, access_key, access_secret)

    if re.match(r"^https:\/\/.+\.blob\.core\.windows\.net\/", url):
        return _azure_blob_storage_call(params, url, format, structure, access_key, access_secret)

    return _url_table_function(params, _s3_function(table_size_mib), url, format, structure, access_key, access_secret)


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
    # Set when this table backs a materialized saved query, so a query that reads the table is attributed to the view.
    saved_query_id: Optional[str] = None

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
