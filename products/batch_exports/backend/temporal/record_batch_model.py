import abc
import uuid
import typing
import datetime as dt

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.hogql import ast
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema
from posthog.clickhouse import query_tagging
from posthog.clickhouse.query_tagging import Product
from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.batch_exports.backend.temporal import sql

Query = str
QueryParameters = dict[str, typing.Any]
BatchExportDateRange = tuple[dt.datetime | None, dt.datetime]


class RecordBatchModel(abc.ABC):
    """Base class for models that can be produced as record batches.

    Attributes:
       team_id: The ID of the team we are producing records for.
       batch_export_id: The ID of the batch export we are producing records for.
    """

    def __init__(self, team_id: int, batch_export_id: str | None = None):
        self.team_id = team_id
        self.batch_export_id = batch_export_id

    async def get_hogql_context(self) -> HogQLContext:
        """Return a HogQLContext to generate a ClickHouse query."""
        team = await Team.objects.aget(id=self.team_id)
        context = HogQLContext(
            team=team,
            team_id=team.id,
            enable_select_queries=True,
            limit_top_select=False,
            values={
                "log_comment": self.get_log_comment(),
            },
        )
        context.database = await database_sync_to_async(create_hogql_database)(team=team, modifiers=context.modifiers)

        return context

    def get_log_comment(self) -> str:
        tags = query_tagging.get_query_tags()
        tags.team_id = self.team_id
        if self.batch_export_id:
            tags.batch_export_id = uuid.UUID(self.batch_export_id)
        tags.product = Product.BATCH_EXPORT
        tags.query_type = "batch_export"
        return tags.to_json()

    @abc.abstractmethod
    async def as_query_with_parameters(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> tuple[Query, QueryParameters]:
        """Produce a printed query and any necessary ClickHouse query parameters."""
        raise NotImplementedError

    @abc.abstractmethod
    async def as_insert_into_s3_query_with_parameters(
        self,
        data_interval_start: dt.datetime | None,
        data_interval_end: dt.datetime,
        s3_folder: str,
        s3_key: str,
        s3_secret: str,
        num_partitions: int,
    ) -> tuple[Query, QueryParameters]:
        """Produce a printed query and any necessary ClickHouse query parameters."""
        raise NotImplementedError


class SessionsRecordBatchModel(RecordBatchModel):
    """A model to produce record batches from the sessions table."""

    def get_hogql_query(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> ast.SelectQuery:
        """Return the HogQLQuery used for the sessions model."""
        hogql_query = sql.SELECT_FROM_SESSIONS_HOGQL

        where_and = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["sessions", "team_id"]),
                    right=ast.Constant(value=self.team_id),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["_inserted_at"]),
                    right=ast.Constant(value=data_interval_end),
                ),
                # include $end_timestamp because hogql uses this to add a where clause to the inner query
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["$end_timestamp"]),
                    right=ast.Constant(value=data_interval_end),
                ),
            ]
        )
        if data_interval_start is not None:
            where_and.exprs.extend(
                [
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["_inserted_at"]),
                        right=ast.Constant(value=data_interval_start),
                    ),
                    # include $end_timestamp because hogql uses this to add a where clause to the inner query
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["$end_timestamp"]),
                        right=ast.Constant(value=data_interval_start),
                    ),
                ]
            )

        hogql_query.where = where_and

        return hogql_query

    async def as_query_with_parameters(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> tuple[Query, QueryParameters]:
        """Produce a printed query and any necessary ClickHouse query parameters."""
        hogql_query = self.get_hogql_query(data_interval_start, data_interval_end)
        context = await self.get_hogql_context()

        prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
            hogql_query, context=context, dialect="clickhouse", stack=[]
        )
        assert prepared_hogql_query is not None
        context.output_format = "ArrowStream"
        printed = print_prepared_ast(
            prepared_hogql_query,
            context=context,
            dialect="clickhouse",
            stack=[],
        )
        return printed, context.values

    async def as_insert_into_s3_query_with_parameters(
        self,
        data_interval_start: dt.datetime | None,
        data_interval_end: dt.datetime,
        s3_folder: str,
        s3_key: str,
        s3_secret: str,
        num_partitions: int,
    ) -> tuple[Query, QueryParameters]:
        """Produce a printed query and any necessary ClickHouse query parameters."""
        hogql_query = self.get_hogql_query(data_interval_start, data_interval_end)
        context = await self.get_hogql_context()

        prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
            hogql_query, context=context, dialect="clickhouse", stack=[]
        )
        assert prepared_hogql_query is not None
        printed = print_prepared_ast(
            prepared_hogql_query,
            context=context,
            dialect="clickhouse",
            stack=[],
        )

        log_comment = "log_comment={log_comment}"
        if "settings" not in printed.lower():
            log_comment = " SETTINGS log_comment={log_comment}"
        else:
            log_comment = ", " + log_comment

        insert_query = f"""
INSERT INTO FUNCTION
   s3(
       '{s3_folder}/export_{{{{_partition_id}}}}.arrow',
       '{s3_key}',
       '{s3_secret}',
       'ArrowStream'
    )
    PARTITION BY rand() %% {num_partitions}
{printed}{log_comment}
"""

        return insert_query, context.values


def resolve_batch_exports_model(
    team_id: int,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    batch_export_id: str | None = None,
):
    """Resolve which model and model parameters to use for a batch export.

    This function exists to isolate a lot of repetitive checks that deal with deprecated
    and new parameters. Eventually, once everything is a `RecordBatchModel`, this could
    be removed.
    """
    model: BatchExportModel | BatchExportSchema | None = None
    record_batch_model = None
    if batch_export_schema is None:
        model = batch_export_model
        if model is not None:
            model_name = model.name
            extra_query_parameters = model.schema["values"] if model.schema is not None else None
            fields = model.schema["fields"] if model.schema is not None else None
            filters = model.filters

            if model_name == "sessions":
                record_batch_model = SessionsRecordBatchModel(team_id=team_id, batch_export_id=batch_export_id)
        else:
            model_name = "events"
            extra_query_parameters = None
            fields = None
            filters = None
    else:
        model = batch_export_schema
        model_name = "custom"
        extra_query_parameters = model["values"] if model is not None else {}
        fields = model["fields"] if model is not None else None
        filters = None

    return model, record_batch_model, model_name, fields, filters, extra_query_parameters
