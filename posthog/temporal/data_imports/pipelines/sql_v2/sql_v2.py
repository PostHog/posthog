from typing import Any, Optional
from collections.abc import Iterator
import psycopg
from psycopg import sql

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_iterator
from posthog.warehouse.models import ExternalDataSource, IncrementalFieldType

from dlt.common.normalizers.naming.snake_case import NamingConvention


def postgres_source(
    source_type: ExternalDataSource.Type,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    sslmode: str,
    schema: str,
    table_names: list[str],
    db_incremental_field_last_value: Optional[Any],
    using_ssl: Optional[bool] = True,
    team_id: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    print("===================")  # noqa: T201
    print("USING NEW SOURCE!!!")  # noqa: T201
    print("===================")  # noqa: T201

    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    def get_rows() -> Iterator[Any]:
        with psycopg.connect(
            f"postgresql://{user}:{password}@{host}:{port}/{database}?sslmode={sslmode}",
            cursor_factory=psycopg.ServerCursor,
        ) as connection:
            with connection.cursor(name=f"posthog_{team_id}_{table_name}") as cursor:
                query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(table_name))
                cursor.execute(query)

                column_names = [column.name for column in cursor.description or []]

                while True:
                    rows = cursor.fetchmany(10_000)
                    if not rows:
                        break

                    yield table_from_iterator(dict(zip(column_names, row)) for row in rows)

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(name=name, items=get_rows(), primary_keys=None)
