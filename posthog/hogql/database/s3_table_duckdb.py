import re
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlparse

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.escape_sql import escape_duckdb_identifier

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


class _DuckDBReadableTable(Protocol):
    url: str
    format: str
    access_key: str | None
    access_secret: str | None
    column_names: tuple[str, ...]
    clickhouse_column_types: tuple[str, ...]
    table_id: str | None
    external_data_source_id: str | None


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
class _ObjectLocation:
    bucket: str
    key: str


@dataclass(frozen=True, kw_only=True)
class DuckDBAzureSource:
    uri: str
    scope: str
    account_name: str


def _split_bucket_and_key(path: str) -> _ObjectLocation | None:
    bucket, separator, key = path.lstrip("/").partition("/")
    if not bucket or not separator or not key:
        return None
    return _ObjectLocation(bucket=bucket, key=key)


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
    uri = f"az://{hostname}/{location.bucket}/{location.key}"
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
    if type_name in {"DateTime", "DateTime32"}:
        return "TIMESTAMP_S"
    if type_name == "DateTime64":
        return "TIMESTAMP_MS"

    datetime_match = re.fullmatch(r"DateTime64\((\d+)\)", type_name)
    if datetime_match is not None:
        precision = int(datetime_match.group(1))
        if precision <= 0:
            return "TIMESTAMP_S"
        if precision <= 3:
            return "TIMESTAMP_MS"
        if precision <= 6:
            return "TIMESTAMP"
        if precision <= 9:
            return "TIMESTAMP_NS"
        return None

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
        bucket = location.bucket
        key = location.key
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


def _duckdb_csv_types(table: _DuckDBReadableTable) -> str:
    """The ``types`` argument that holds a CSV read to the column types HogQL resolves against.

    The ClickHouse reader pins them through ``structure``; without the same pinning here a
    quoted ``"12345"`` saved as a string comes back as a number, so the same table answers
    differently under DuckLake and fails to bind the string operations HogQL allows on it.
    Pinning is keyed by name, so it needs the saved column names and ClickHouse types. A type
    without an exact DuckDB counterpart stays sniffed. Column names go through the DuckDB
    identifier escape, and ``%`` names stay sniffed because psycopg reads one as a placeholder.
    """
    if len(table.column_names) != len(table.clickhouse_column_types):
        return ""

    pinned: list[str] = []
    for name, clickhouse_type in zip(table.column_names, table.clickhouse_column_types):
        if "%" in name:
            continue
        duckdb_type = _duckdb_csv_type_for_clickhouse_type(clickhouse_type)
        if duckdb_type is None:
            continue
        pinned.append(f"{escape_duckdb_identifier(name)} := '{duckdb_type}'")
    return f", types = struct_pack({', '.join(pinned)})" if pinned else ""


def print_duckdb_table(table: _DuckDBReadableTable, context: HogQLContext) -> str:
    if table.format not in DUCKDB_SELF_MANAGED_SUPPORTED_FORMATS:
        raise ExposedHogQLError(
            "DuckLake can't read this self-managed table format. Save the table as Parquet, CSV, JSON, or Delta."
        )

    source = parse_duckdb_azure_source(table.url) or parse_duckdb_s3_source(table.url)
    if source is None:
        raise ExposedHogQLError(
            "DuckLake can't read this self-managed table URL. Point the table at an S3-compatible "
            "or Azure Blob Storage URL."
        )
    if not table.access_key or not table.access_secret:
        raise ExposedHogQLError(
            "DuckLake can't read this self-managed table because its object storage credentials are missing. "
            "Add an access key and secret to the table."
        )
    if (
        isinstance(source, DuckDBAzureSource)
        and build_duckdb_azure_connection_string(source, table.access_key, table.access_secret) is None
    ):
        raise ExposedHogQLError(
            "DuckLake can't use these Azure Blob Storage credentials. "
            "Make sure the storage account name matches the table URL and the account key is valid."
        )

    if table.table_id is not None and table.external_data_source_id is None:
        context.referenced_self_managed_table_ids.add(table.table_id)

    uri = context.add_value(source.uri)
    if table.format == "Parquet":
        return f"read_parquet({uri}, hive_partitioning = false)"
    if table.format == "CSVWithNames":
        return f"read_csv({uri}, header = true{_duckdb_csv_types(table)}, hive_partitioning = false)"
    if table.format == "CSV":
        names = ""
        if table.column_names:
            column_names = ", ".join(context.add_value(name) for name in table.column_names)
            names = f", names = [{column_names}]"
        return f"read_csv({uri}, header = false{names}{_duckdb_csv_types(table)}, hive_partitioning = false)"
    if table.format == "JSONEachRow":
        return f"read_json({uri}, format = 'newline_delimited', hive_partitioning = false)"
    return f"delta_scan({uri})"
