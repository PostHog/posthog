from typing import TYPE_CHECKING

import psycopg
from opentelemetry import trace

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_query_metrics import DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL, observe_direct_query
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.pgwire import (
    LenientDirectPostgresDateLoader,
    postgres_error_to_message,
    postgres_oid_to_clickhouse_type,
)
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.errors import ExposedHogQLError

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource


DIRECT_DUCKGRES_CONNECT_TIMEOUT_SECONDS = 15
DIRECT_DUCKGRES_DEFAULT_STATEMENT_TIMEOUT_SECONDS = 600
DIRECT_DUCKGRES_MAX_ROWS = 1_000_000
DIRECT_DUCKGRES_ROW_CAP_ERROR = (
    f"Managed warehouse query returned more than {DIRECT_DUCKGRES_MAX_ROWS:,} rows. Add a LIMIT clause."
)
MANAGED_WAREHOUSE_UNAVAILABLE_ERROR = "Managed warehouse is unavailable. Contact support if the problem persists."
MANAGED_WAREHOUSE_CONNECTION_ERROR = (
    "Could not connect to the managed warehouse. Try again, and contact support if the problem persists."
)


def make_duckgres_conninfo(*, team_id: int, organization_id: str) -> str:
    from products.managed_warehouse.backend.facade.client import (
        make_duckgres_conninfo as make_conninfo,  # noqa: PLC0415 - keeps managed-warehouse client imports off the direct-SQL module path
    )

    return make_conninfo(team_id=team_id, organization_id=organization_id)


def _fetch_capped_duckgres_rows(cursor: psycopg.Cursor) -> list:
    rows = cursor.fetchmany(DIRECT_DUCKGRES_MAX_ROWS + 1)
    if len(rows) > DIRECT_DUCKGRES_MAX_ROWS:
        DIRECT_QUERY_ROW_CAP_EXCEEDED_TOTAL.labels(dialect="duckgres").inc()
        raise ExposedHogQLError(DIRECT_DUCKGRES_ROW_CAP_ERROR)
    return list(rows)


class DuckgresRawAdapter:
    engine = "duckgres"
    dialect: HogQLDialect | None = None

    def validate_source_config(self, source: "ExternalDataSource", team: "Team") -> tuple[None, None]:
        return None, None

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_single_direct_statement(sql)

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        statement_timeout_ms = (
            max(request.settings.max_execution_time or DIRECT_DUCKGRES_DEFAULT_STATEMENT_TIMEOUT_SECONDS, 1) * 1000
        )
        span = trace.get_current_span()
        span.set_attribute("team_id", request.team.pk)
        span.set_attribute("query_type", request.query_type)
        span.set_attribute("source_id", str(request.source.id))

        try:
            with request.timings.measure("duckgres_execute"), observe_direct_query("duckgres"):
                try:
                    with request.timings.measure("duckgres_connect", emit_span=True):
                        connection_context = psycopg.connect(
                            make_duckgres_conninfo(
                                team_id=request.team.pk,
                                organization_id=str(request.team.organization_id),
                            ),
                            connect_timeout=DIRECT_DUCKGRES_CONNECT_TIMEOUT_SECONDS,
                            options=(
                                f"-c default_transaction_read_only=on -c statement_timeout={statement_timeout_ms}"
                            ),
                        )
                except ValueError as error:
                    span.set_attribute("error_type", error.__class__.__name__)
                    raise ExposedHogQLError(MANAGED_WAREHOUSE_UNAVAILABLE_ERROR) from error
                except psycopg.Error as error:
                    span.set_attribute("error_type", error.__class__.__name__)
                    raise ExposedHogQLError(MANAGED_WAREHOUSE_CONNECTION_ERROR) from error

                with connection_context as connection:
                    with request.timings.measure("duckgres_session_setup"):
                        connection.execute("USE ducklake")
                    connection.adapters.register_loader("date", LenientDirectPostgresDateLoader)
                    with connection.cursor() as cursor:
                        with request.timings.measure("duckgres_query_execute", emit_span=True):
                            cursor.execute(  # nosemgrep: python.django.security.injection.sql.sql-injection-using-db-cursor-execute.sql-injection-db-cursor-execute
                                request.sql, request.values or None
                            )
                        description = cursor.description or []
                        with request.timings.measure("duckgres_query_fetch"):
                            results = _fetch_capped_duckgres_rows(cursor) if description else []
        except (psycopg.Error, ExposedHogQLError) as error:
            span.set_attribute("error_type", error.__class__.__name__)
            if request.debug:
                return DirectQueryResult(results=[], types=[], print_columns=[], error=postgres_error_to_message(error))
            raise ExposedHogQLError(postgres_error_to_message(error)) from error

        span.set_attribute("row_count", len(results))
        types = [
            (column.name, postgres_oid_to_clickhouse_type(getattr(column, "type_code", None))) for column in description
        ]
        return DirectQueryResult(results=results, types=types, print_columns=[column.name for column in description])
