import re
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import urlparse, urlunparse

from django.conf import settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.escape_sql import escape_hogql_identifier

from posthog.clickhouse.client.escape import substitute_params


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


# Virtual-hosted-style S3 host, e.g. ``bucket.s3.amazonaws.com`` or
# ``bucket.s3.us-east-1.amazonaws.com`` (also legacy ``bucket.s3-us-east-1...``).
_S3_VHOST_RE = re.compile(r"^(?P<bucket>.+?)\.s3([.-][a-z0-9-]+)*\.amazonaws\.com$", re.IGNORECASE)
# Path-style S3 host, e.g. ``s3.amazonaws.com`` or ``s3.us-east-1.amazonaws.com``.
_S3_PATH_HOST_RE = re.compile(r"^s3([.-][a-z0-9-]+)*\.amazonaws\.com$", re.IGNORECASE)


def to_duckdb_s3_uri(url: str) -> str:
    """Rewrite an HTTP(S) AWS S3 URL into an ``s3://bucket/key`` URI.

    DuckDB only applies a configured S3 secret (credentials) to ``s3://`` URIs;
    an ``https://…amazonaws.com/…`` URL is treated as plain HTTP and reaches a
    private bucket unauthenticated. We recognize the two AWS addressing styles
    and rewrite them; any other scheme or host is returned unchanged so DuckDB's
    httpfs can handle it.
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme in ("s3", "s3a", "s3n"):
        return url
    if scheme not in ("http", "https"):
        return url

    host = (parsed.hostname or "").lower()
    path = parsed.path.lstrip("/")

    vhost_match = _S3_VHOST_RE.match(host)
    if vhost_match:
        return f"s3://{vhost_match.group('bucket')}/{path}"
    if _S3_PATH_HOST_RE.match(host):
        # Path-style: the bucket is the first path segment.
        return f"s3://{path}"
    return url


def _resolve_duckdb_data_url(url: str, format: str, queryable_folder: Optional[str]) -> str:
    """Resolve the concrete file URL DuckDB should read, mirroring the ClickHouse path.

    For ``DeltaS3Wrapper`` tables the queryable Parquet lives under a ``__query``
    sibling folder (or an explicit ``queryable_folder``), so we point DuckDB at
    that Parquet glob rather than the Delta root.
    """
    if format != "DeltaS3Wrapper":
        return url

    if queryable_folder:
        parsed = urlparse(url)
        new_path = str(PurePosixPath(parsed.path).parent) + "/"
        new_url = urlunparse(parsed._replace(path=new_path))
        return new_url + queryable_folder + "/**.parquet"

    if url.endswith("/"):
        return f"{url[:-1]}__query/**.parquet"
    return f"{url}__query/**.parquet"


def build_duckdb_function_call(
    url: str,
    format: str,
    queryable_folder: Optional[str] = None,
    context: Optional[HogQLContext] = None,
) -> str:
    """Render an S3-backed warehouse table as a DuckDB/DuckLake table function.

    DuckLake (duckgres/DuckDB) has no ClickHouse ``s3()`` table function, so the
    Postgres-dialect print can't reuse :func:`build_function_call`. We map the
    stored file format to the matching DuckDB reader and rewrite the HTTP(S) S3
    URL into an ``s3://`` URI so DuckDB applies the server-side S3 secret.
    """
    data_url = _resolve_duckdb_data_url(url, format, queryable_folder)
    s3_uri = to_duckdb_s3_uri(data_url)

    if context is not None:
        escaped_url = context.add_value(s3_uri)
    else:
        escaped_url = "'" + s3_uri.replace("'", "''") + "'"

    if format == "Delta":
        return f"delta_scan({escaped_url})"
    if format in ("CSV", "CSVWithNames"):
        header = "true" if format == "CSVWithNames" else "false"
        return f"read_csv({escaped_url}, header = {header})"
    if format == "JSONEachRow":
        return f"read_json({escaped_url}, format = 'newline_delimited')"
    # Parquet and DeltaS3Wrapper (whose queryable folder holds Parquet) both read Parquet.
    return f"read_parquet({escaped_url})"


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

    def to_printed_postgres(self, context):
        return build_duckdb_function_call(
            url=self.url,
            format=self.format,
            queryable_folder=self.queryable_folder,
            context=context,
        )


class DataWarehouseTable(S3Table):
    """A table placeholder for checking warehouse tables"""

    pass
