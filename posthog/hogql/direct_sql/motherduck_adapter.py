from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, cast

import sqlparse
from opentelemetry import trace
from sqlparse import tokens as sqlparse_tokens
from sqlparse.sql import Token

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_query_metrics import DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL, observe_direct_query
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.capability import is_direct_capable
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.motherduck_connection_cache import cached_motherduck_connection

if TYPE_CHECKING:
    import duckdb

    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motherduck import (
        MotherduckSourceConfig,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.source import MotherduckSource

DIRECT_MOTHERDUCK_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
# Hard backstop against loading an unbounded result set into memory. The connection is
# opened read-only, but a raw passthrough `SELECT * FROM huge_table` with no LIMIT would
# still stream everything back. HogQL-authored queries already carry a LIMIT from the printer.
DIRECT_MOTHERDUCK_MAX_ROWS = 1_000_000
RAW_MOTHERDUCK_READ_ONLY_ERROR = "Raw MotherDuck queries must be read-only SELECT statements."
RAW_MOTHERDUCK_BLOCKED_FUNCTION_ERROR = "This DuckDB function is not allowed in direct queries."
DIRECT_MOTHERDUCK_ROW_CAP_ERROR = (
    f"MotherDuck query returned more than {DIRECT_MOTHERDUCK_MAX_ROWS:,} rows. Add a LIMIT clause."
)
DIRECT_MOTHERDUCK_TIMEOUT_ERROR = "MotherDuck query timed out."

# Functions that parse as a plain SELECT but touch the worker's environment or filesystem,
# read back the connection's own credentials, or smuggle a second statement past the SELECT
# gate. The connection is opened with `saas_mode=true` (no local filesystem, no extension
# installs) and `read_only=True`, so the filesystem entries are defense in depth for the raw
# passthrough path — HogQL-authored SQL never emits them. The credential entries are not:
# `motherduck_token` travels in the DSN and lands as a readable DuckDB setting, so
# `current_setting`/`duckdb_settings` would hand the source's token to anyone who can run
# raw SQL, and `query()` would run `PRAGMA PRINT_MD_TOKEN` inside an outer SELECT.
#
# Only call positions are rejected, so a column or table legitimately named `query` or `glob`
# still resolves. Quoting doesn't help an attacker either: DuckDB resolves `"glob"('/*')` to
# the same function, so the check covers quoted identifiers in call position too.
_RAW_MOTHERDUCK_BLOCKED_FUNCTIONS = frozenset(
    {
        "QUERY",
        "QUERY_TABLE",
        "CURRENT_SETTING",
        "DUCKDB_SETTINGS",
        "DUCKDB_SECRETS",
        "READ_CSV",
        "READ_CSV_AUTO",
        "READ_JSON",
        "READ_JSON_AUTO",
        "READ_JSON_OBJECTS",
        "READ_JSON_OBJECTS_AUTO",
        "READ_NDJSON",
        "READ_NDJSON_AUTO",
        "READ_NDJSON_OBJECTS",
        "READ_PARQUET",
        "PARQUET_SCAN",
        "READ_TEXT",
        "READ_BLOB",
        "READ_XLSX",
        "GLOB",
        "GETENV",
        "SNIFF_CSV",
    }
)

# `%(name)s` placeholders as the Postgres-family printers emit them. Printed constants can
# never contain a stray `%` (the printer rejects it), so every match is a real placeholder.
_PYFORMAT_PLACEHOLDER_RE = re.compile(r"%\((?P<name>[A-Za-z0-9_]+)\)s")


def convert_pyformat_placeholders(sql: str, values: dict[str, object] | None) -> tuple[str, dict[str, object]]:
    """Rewrite psycopg-style `%(name)s` placeholders to DuckDB's `$name` form.

    The DuckDB printer inherits the Postgres printer's value binding, but the duckdb Python
    API only understands `$name`/`?` parameters.
    """
    if not values:
        return sql, {}
    converted = _PYFORMAT_PLACEHOLDER_RE.sub(lambda match: f"${match.group('name')}", sql)
    return converted, dict(values)


def duckdb_type_to_clickhouse_type(duckdb_type: object | None) -> str:
    # Function-local: keeps warehouse_sources model imports off this module's import path.
    from products.warehouse_sources.backend.models.util import duckdb_to_clickhouse_type  # noqa: PLC0415

    if duckdb_type is None:
        return "String"
    return duckdb_to_clickhouse_type(str(duckdb_type))


def motherduck_error_to_message(error: Exception) -> str:
    # Deferred so the module imports without the driver loaded.
    from products.warehouse_sources.backend.facade.source_management import translate_motherduck_error  # noqa: PLC0415

    return translate_motherduck_error(error)


def _blocked_function_name(token: Token) -> str | None:
    """The blocked-function name this token could resolve to, or None."""
    if token.ttype in sqlparse_tokens.Name:
        name = token.value.upper()
    elif token.ttype in sqlparse_tokens.String.Symbol and len(token.value) >= 2:
        # DuckDB resolves `"glob"(...)` to the same function as `glob(...)`.
        name = token.value[1:-1].upper()
    else:
        return None
    return name if name in _RAW_MOTHERDUCK_BLOCKED_FUNCTIONS else None


def _opens_call(tokens: list[Token], index: int) -> bool:
    """Whether the token at `index` is immediately followed by `(`, i.e. invoked as a function."""
    for token in tokens[index + 1 :]:
        if token.ttype in sqlparse_tokens.Whitespace or token.ttype in sqlparse_tokens.Comment:
            continue
        return token.ttype is sqlparse_tokens.Punctuation and token.value == "("
    return False


def ensure_read_only_raw_motherduck_statement(sql: str) -> str:
    sql = ensure_single_direct_statement(sql)
    statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip(" \t\r\n;")]
    if len(statements) != 1 or statements[0].get_type() != "SELECT":
        raise ExposedHogQLError(RAW_MOTHERDUCK_READ_ONLY_ERROR)
    # The connection itself is read-only (DuckDB rejects writes engine-side) and runs in
    # MotherDuck's SaaS mode, so this gate is defense in depth for the raw passthrough path:
    # reject DDL, any DML other than SELECT, and calls to the blocked functions above.
    tokens = list(statements[0].flatten())
    for index, token in enumerate(tokens):
        if token.ttype in sqlparse_tokens.DDL:
            raise ExposedHogQLError(RAW_MOTHERDUCK_READ_ONLY_ERROR)
        if token.ttype in sqlparse_tokens.DML and token.value.upper() != "SELECT":
            raise ExposedHogQLError(RAW_MOTHERDUCK_READ_ONLY_ERROR)
        if _blocked_function_name(token) is not None and _opens_call(tokens, index):
            raise ExposedHogQLError(RAW_MOTHERDUCK_BLOCKED_FUNCTION_ERROR)
    return sql


def _fetch_capped_motherduck_rows(connection: duckdb.DuckDBPyConnection) -> list:
    """Fetch up to the row cap, raising if the result would exceed it.

    Reads one row past the cap so the limit can be enforced without materializing the
    entire result set first.
    """
    rows = connection.fetchmany(DIRECT_MOTHERDUCK_MAX_ROWS + 1)
    if len(rows) > DIRECT_MOTHERDUCK_MAX_ROWS:
        DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL.labels(dialect="motherduck").inc()
        raise ExposedHogQLError(DIRECT_MOTHERDUCK_ROW_CAP_ERROR)
    return list(rows)


class _InterruptWatchdog:
    """Cancel a running DuckDB query after a deadline.

    DuckDB has no statement-timeout setting; `connection.interrupt()` is the supported way
    to cancel from another thread, surfacing in the query thread as an InterruptException.
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection, timeout_seconds: float) -> None:
        self._fired = threading.Event()

        def _interrupt() -> None:
            self._fired.set()
            try:
                connection.interrupt()
            except Exception:
                pass

        self._timer = threading.Timer(timeout_seconds, _interrupt)
        self._timer.daemon = True

    def __enter__(self) -> _InterruptWatchdog:
        self._timer.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._timer.cancel()

    @property
    def fired(self) -> bool:
        return self._fired.is_set()


class MotherDuckAdapter:
    engine = "motherduck"
    dialect: HogQLDialect | None = "duckdb"

    def validate_source_config(
        self, source: ExternalDataSource, team: Team
    ) -> tuple[MotherduckSource, MotherduckSourceConfig]:
        from products.warehouse_sources.backend.facade.source_management import SourceRegistry
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

        # Capability, not access_method: a synced source with the direct-query toggle on is valid too.
        if not (is_direct_capable(source) and source.direct_engine == self.engine):
            raise ExposedHogQLError("Invalid direct MotherDuck connection.")

        motherduck_source = cast("MotherduckSource", SourceRegistry.get_source(ExternalDataSourceType.MOTHERDUCK))
        config = motherduck_source.parse_config(source.job_inputs or {})

        # No host/SSH-tunnel config to validate: the driver always dials MotherDuck's fixed
        # SaaS endpoint, so there is no SSRF surface equivalent to the Postgres/MySQL hosts.
        if not (config.access_token or "").strip():
            raise ExposedHogQLError("This MotherDuck connection has no access token configured.")

        return motherduck_source, config

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_read_only_raw_motherduck_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        """Execute a single read-only statement against the source's MotherDuck account.

        Read-only is enforced engine-side: the connection is opened with `read_only=True`
        (DuckDB rejects every write statement) and `saas_mode=true` (no local filesystem, no
        extension installs). `prepare_raw_sql` additionally gates raw SQL to a single SELECT.
        """
        import duckdb  # noqa: PLC0415 — keeps the heavy dep off the import path

        from products.warehouse_sources.backend.facade.source_management import (  # noqa: PLC0415
            MotherDuckConnectionError,
        )

        source = request.source
        motherduck_source, source_config = self.validate_source_config(source, request.team)
        settings = request.settings
        statement_timeout_seconds = max(
            settings.max_execution_time or DIRECT_MOTHERDUCK_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1
        )

        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(source.id))

        sql, values = convert_pyformat_placeholders(request.sql, request.values)

        try:
            with request.timings.measure("motherduck_execute"), observe_direct_query("motherduck"):
                # Reuse a per-thread connection across queries — the extension load + WebSocket
                # handshake is the dominant cost for interactive use.
                with cached_motherduck_connection(motherduck_source, source_config) as connection:
                    with _InterruptWatchdog(connection, statement_timeout_seconds) as watchdog:
                        try:
                            connection.execute(sql, values or None)
                            results = _fetch_capped_motherduck_rows(connection)
                        except duckdb.InterruptException:
                            if watchdog.fired:
                                raise ExposedHogQLError(DIRECT_MOTHERDUCK_TIMEOUT_ERROR) from None
                            raise
                    description = connection.description or []
        except (duckdb.Error, MotherDuckConnectionError, ExposedHogQLError) as error:
            span.set_attribute("error_type", error.__class__.__name__)
            # A failed cold connect already arrives translated; only raw driver errors need it.
            message = str(error) if isinstance(error, MotherDuckConnectionError) else motherduck_error_to_message(error)
            if request.debug:
                return DirectQueryResult(results=[], types=[], print_columns=[], error=message)
            if isinstance(error, ExposedHogQLError):
                raise
            raise ExposedHogQLError(message) from error

        span.set_attribute("row_count", len(results))
        types: list[tuple[str, str]] = [
            (column[0], duckdb_type_to_clickhouse_type(column[1])) for column in description
        ]
        print_columns = [column[0] for column in description]
        return DirectQueryResult(results=results, types=types, print_columns=print_columns)
