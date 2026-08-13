from typing import TYPE_CHECKING

import psycopg
from opentelemetry import trace

from posthog.hogql.constants import HogQLDialect
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


def make_duckgres_conninfo(*, team_id: int, organization_id: str) -> str:
    from products.managed_warehouse.backend.facade.client import (
        make_duckgres_conninfo as make_conninfo,  # noqa: PLC0415 - keeps managed-warehouse client imports off the direct-SQL module path
    )

    return make_conninfo(team_id=team_id, organization_id=organization_id)


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
            with request.timings.measure("duckgres_execute"):
                with request.timings.measure("duckgres_connect", emit_span=True):
                    connection_context = psycopg.connect(
                        make_duckgres_conninfo(
                            team_id=request.team.pk,
                            organization_id=str(request.team.organization_id),
                        ),
                        connect_timeout=DIRECT_DUCKGRES_CONNECT_TIMEOUT_SECONDS,
                        options=(f"-c default_transaction_read_only=on -c statement_timeout={statement_timeout_ms}"),
                    )
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
                            results = cursor.fetchall() if description else []
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
