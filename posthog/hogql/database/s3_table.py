import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, Optional
from urllib.parse import urlparse, urlunparse

from django.conf import settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.escape_sql import escape_duckdb_identifier, escape_hogql_identifier

from posthog.clickhouse.client.escape import substitute_params

_AWS_S3_ENDPOINT_RE = re.compile(r"s3(?:[.-][a-z0-9-]+)*\.amazonaws\.com(?:\.cn)?")
_AWS_S3_VIRTUAL_HOST_RE = re.compile(r"(?P<bucket>.+)\.(?P<endpoint>s3(?:[.-][a-z0-9-]+)*\.amazonaws\.com(?:\.cn)?)")
_S3_REGION_RE = re.compile(r"(?:^|[.-])(?P<region>[a-z]{2,4}(?:-[a-z0-9]+)+-\d+)(?:\.|$)")
_NON_AWS_S3_VIRTUAL_HOST_RES = (
    re.compile(r"(?P<bucket>.+)\.(?P<endpoint>storage\.googleapis\.com)"),
    re.compile(r"(?P<bucket>.+)\.(?P<endpoint>[a-z0-9-]+\.digitaloceanspaces\.com)"),
    re.compile(r"(?P<bucket>.+)\.(?P<endpoint>s3(?:\.[a-z0-9-]+)?\.wasabisys\.com)"),
    re.compile(r"(?P<bucket>.+)\.(?P<endpoint>s3\.[a-z0-9-]+\.backblazeb2\.com)"),
)
_AZURE_BLOB_HOST_SUFFIX = ".blob.core.windows.net"
_AZURE_ACCOUNT_NAME_RE = re.compile(r"[a-z0-9]{3,24}")
_AZURE_ACCOUNT_KEY_RE = re.compile(r"[A-Za-z0-9+/]+={0,2}")
DUCKDB_SELF_MANAGED_SUPPORTED_FORMATS: frozenset[str] = frozenset(
    {"CSV", "CSVWithNames", "Delta", "JSONEachRow", "Parquet"}
)
_DUCKDB_CSV_INTEGER_TYPES: dict[str, str] = {
    "Int8": "TINYINT",
    "Int16": "SMALLINT",
    "Int32": "INTEGER",
    "Int64": "BIGINT",
    "Int128": "HUGEINT",
    "UInt8": "UTINYINT",
    "UInt16": "USMALLINT",
    "UInt32": "UINTEGER",
    "UInt64": "UBIGINT",
    "UInt128": "UHUGEINT",
}
_DUCKDB_CSV_DECIMAL_PRECISIONS: dict[str, int] = {
    "Decimal32": 9,
    "Decimal64": 18,
    "Decimal128": 38,
}


@dataclass(frozen=True, kw_only=True)
class DuckDBS3Source:
    uri: str
    scope: str
    endpoint: str | None
    region: str
    use_ssl: bool
    url_style: Literal["path", "vhost"]


@dataclass(frozen=True, kw_only=True)
class _S3VirtualHost:
    bucket: str
    endpoint: str


@dataclass(frozen=True, kw_only=True)
class DuckDBAzureSource:
    uri: str
    scope: str
    account_name: str


def _split_bucket_and_key(path: str) -> tuple[str, str] | None:
    bucket, separator, key = path.lstrip("/").partition("/")
    if not bucket or not separator or not key:
        return None
    return bucket, key


def _scope_for_s3_uri(uri: str) -> str:
    wildcard_positions = [position for token in ("*", "?", "[") if (position := uri.find(token)) >= 0]
    return uri[: min(wildcard_positions)] if wildcard_positions else uri


def _region_for_s3_endpoint(endpoint: str) -> str:
    match = _S3_REGION_RE.search(endpoint)
    return match.group("region") if match else "us-east-1"


def _parse_s3_virtual_host(hostname: str) -> _S3VirtualHost | None:
    match = _AWS_S3_VIRTUAL_HOST_RE.fullmatch(hostname)
    if match is not None:
        return _S3VirtualHost(bucket=match.group("bucket"), endpoint=match.group("endpoint"))
    for pattern in _NON_AWS_S3_VIRTUAL_HOST_RES:
        match = pattern.fullmatch(hostname)
        if match is not None:
            return _S3VirtualHost(bucket=match.group("bucket"), endpoint=match.group("endpoint"))
    return None


def _scope_for_azure_uri(uri: str) -> str:
    prefix = _scope_for_s3_uri(uri)
    if prefix.endswith("/"):
        return prefix
    parent, separator, _ = prefix.rpartition("/")
    return f"{parent}/" if separator else f"{prefix}/"


def parse_duckdb_azure_source(url: str) -> DuckDBAzureSource | None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname is None:
        return None

    hostname = parsed.hostname.lower()
    if not hostname.endswith(_AZURE_BLOB_HOST_SUFFIX):
        return None
    account_name = hostname.removesuffix(_AZURE_BLOB_HOST_SUFFIX)
    if _AZURE_ACCOUNT_NAME_RE.fullmatch(account_name) is None:
        return None

    location = _split_bucket_and_key(parsed.path)
    if location is None:
        return None
    container, key = location
    uri = f"az://{hostname}/{container}/{key}"
    return DuckDBAzureSource(
        uri=uri,
        scope=_scope_for_azure_uri(uri),
        account_name=account_name,
    )


def build_duckdb_azure_connection_string(
    source: DuckDBAzureSource,
    account_name: str,
    account_key: str,
) -> str | None:
    if account_name != source.account_name or _AZURE_ACCOUNT_KEY_RE.fullmatch(account_key) is None:
        return None
    return (
        "DefaultEndpointsProtocol=https;"
        f"AccountName={source.account_name};"
        f"AccountKey={account_key};"
        "EndpointSuffix=core.windows.net"
    )


def _unwrap_clickhouse_type(type_name: str, wrapper: str) -> str | None:
    prefix = f"{wrapper}("
    if type_name.startswith(prefix) and type_name.endswith(")"):
        return type_name[len(prefix) : -1].strip()
    return None


def _duckdb_csv_type_for_clickhouse_type(clickhouse_type: str) -> str | None:
    type_name = clickhouse_type.strip()
    while True:
        unwrapped = _unwrap_clickhouse_type(type_name, "Nullable") or _unwrap_clickhouse_type(
            type_name, "LowCardinality"
        )
        if unwrapped is None:
            break
        type_name = unwrapped

    if type_name in _DUCKDB_CSV_INTEGER_TYPES:
        return _DUCKDB_CSV_INTEGER_TYPES[type_name]
    if type_name in {"String", "Bool", "Boolean", "Date", "Date32", "UUID"}:
        return {
            "String": "VARCHAR",
            "Bool": "BOOLEAN",
            "Boolean": "BOOLEAN",
            "Date": "DATE",
            "Date32": "DATE",
            "UUID": "UUID",
        }[type_name]
    if type_name == "Float32":
        return "FLOAT"
    if type_name == "Float64":
        return "DOUBLE"
    if type_name.startswith("DateTime"):
        return "TIMESTAMP"

    decimal_match = re.fullmatch(r"Decimal\((\d+)\s*,\s*(\d+)\)", type_name)
    if decimal_match is not None:
        precision = int(decimal_match.group(1))
        scale = int(decimal_match.group(2))
        return f"DECIMAL({precision}, {scale})" if precision <= 38 and scale <= precision else None
    decimal_width_match = re.fullmatch(r"(Decimal(?:32|64|128))\((\d+)\)", type_name)
    if decimal_width_match is not None:
        precision = _DUCKDB_CSV_DECIMAL_PRECISIONS[decimal_width_match.group(1)]
        scale = int(decimal_width_match.group(2))
        return f"DECIMAL({precision}, {scale})" if scale <= precision else None
    return None


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
    virtual_host = _parse_s3_virtual_host(hostname)
    if virtual_host is not None:
        bucket = virtual_host.bucket
        endpoint = virtual_host.endpoint if parsed.port is None else f"{virtual_host.endpoint}:{parsed.port}"
        url_style: Literal["path", "vhost"] = "vhost"
        region = _region_for_s3_endpoint(virtual_host.endpoint)
    else:
        location = _split_bucket_and_key(parsed.path)
        if location is None:
            return None
        bucket, key = location
        url_style = "path"
        region = _region_for_s3_endpoint(hostname) if _AWS_S3_ENDPOINT_RE.fullmatch(hostname) else "us-east-1"

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
    column_names: tuple[str, ...] = ()
    clickhouse_column_types: tuple[str, ...] = ()
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

    def _duckdb_csv_types(self) -> str:
        """The ``types`` argument that holds a CSV read to the column types HogQL resolves against.

        The ClickHouse reader pins them through ``structure``; without the same pinning here a
        quoted ``"12345"`` saved as a string comes back as a number, so the same table answers
        differently under DuckLake and fails to bind the string operations HogQL allows on it.
        Pinning is keyed by name, so it needs the saved column names and ClickHouse types. A type
        without an exact DuckDB counterpart stays sniffed. Column names go through the DuckDB
        identifier escape, and ``%`` names stay sniffed because psycopg reads one as a placeholder.
        """
        if len(self.column_names) != len(self.clickhouse_column_types):
            return ""

        pinned: list[str] = []
        for name, clickhouse_type in zip(self.column_names, self.clickhouse_column_types):
            if "%" in name:
                continue
            duckdb_type = _duckdb_csv_type_for_clickhouse_type(clickhouse_type)
            if duckdb_type is None:
                continue
            pinned.append(f"{escape_duckdb_identifier(name)} := '{duckdb_type}'")
        return f", types = struct_pack({', '.join(pinned)})" if pinned else ""

    def to_printed_duckdb(self, context: HogQLContext) -> str:
        if self.format not in DUCKDB_SELF_MANAGED_SUPPORTED_FORMATS:
            raise ExposedHogQLError(
                "DuckLake can't read this self-managed table format. "
                "Use Parquet, CSV, JSON, or Delta, or run the query without DuckLake."
            )

        source = parse_duckdb_azure_source(self.url) or parse_duckdb_s3_source(self.url)
        if source is None:
            raise ExposedHogQLError(
                "DuckLake can't read this self-managed table URL. "
                "Use an S3-compatible or Azure Blob Storage URL, or run the query without DuckLake."
            )
        if not self.access_key or not self.access_secret:
            raise ExposedHogQLError(
                "DuckLake can't read this self-managed table because its object storage credentials are missing. "
                "Add an access key and secret to the table, or run the query without DuckLake."
            )
        if (
            isinstance(source, DuckDBAzureSource)
            and build_duckdb_azure_connection_string(source, self.access_key, self.access_secret) is None
        ):
            raise ExposedHogQLError(
                "DuckLake can't use these Azure Blob Storage credentials. "
                "Make sure the storage account name matches the table URL and the account key is valid, "
                "or run the query without DuckLake."
            )

        if self.table_id is not None and self.external_data_source_id is None:
            context.referenced_self_managed_table_ids.add(self.table_id)

        uri = context.add_value(source.uri)
        if self.format == "Parquet":
            return f"read_parquet({uri}, hive_partitioning = false)"
        if self.format == "CSVWithNames":
            return f"read_csv({uri}, header = true{self._duckdb_csv_types()}, hive_partitioning = false)"
        if self.format == "CSV":
            names = ""
            if self.column_names:
                column_names = ", ".join(context.add_value(name) for name in self.column_names)
                names = f", names = [{column_names}]"
            return f"read_csv({uri}, header = false{names}{self._duckdb_csv_types()}, hive_partitioning = false)"
        if self.format == "JSONEachRow":
            return f"read_json({uri}, format = 'newline_delimited', hive_partitioning = false)"
        return f"delta_scan({uri})"


class DataWarehouseTable(S3Table):
    """A table placeholder for checking warehouse tables"""

    pass
