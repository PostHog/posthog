import abc
import uuid
import typing
import datetime as dt

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse import query_tagging
from posthog.clickhouse.query_tagging import Product
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.service import BatchExportModel, BatchExportSchema
from products.batch_exports.backend.temporal import sql
from products.batch_exports.backend.temporal.metrics import log_query_duration

LOGGER = get_write_only_logger()

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
        context.database = await database_sync_to_async(Database.create_for)(team=team, modifiers=context.modifiers)

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
        s3_key: str | None,
        s3_secret: str | None,
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
        hogql_query = clone_expr(sql.SELECT_FROM_SESSIONS_HOGQL)

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
        s3_key: str | None,
        s3_secret: str | None,
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

        s3_function = sql.get_s3_function_call(s3_folder, s3_key, s3_secret, num_partitions)
        insert_query = f"""
INSERT INTO FUNCTION {s3_function}
{printed}{log_comment}
"""

        return insert_query, context.values

    def get_backfill_info_hogql_query(
        self, start_at: dt.datetime | None, end_at: dt.datetime | None
    ) -> ast.SelectQuery:
        """Return a HogQL query to estimate record count and earliest timestamp for a backfill."""
        where_and = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["sessions", "team_id"]),
                    right=ast.Constant(value=self.team_id),
                ),
                # filter out sessions before 2000-01-01 in case we have any incorrect timestamps
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Field(chain=["$end_timestamp"]),
                    right=ast.Constant(value=dt.datetime(2000, 1, 1, tzinfo=dt.UTC)),
                ),
            ]
        )

        if end_at is not None:
            where_and.exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["$end_timestamp"]),
                    right=ast.Constant(value=end_at),
                ),
            )

        if start_at is not None:
            where_and.exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["$end_timestamp"]),
                    right=ast.Constant(value=start_at),
                ),
            )

        return ast.SelectQuery(
            select=[
                parse_expr("min($end_timestamp) as min_timestamp"),
                parse_expr("count() as record_count"),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
            where=where_and,
            settings=sql.HogQLQueryBatchExportSettings(),
        )

    async def get_backfill_info(
        self, start_at: dt.datetime | None, end_at: dt.datetime | None, log_comment: str
    ) -> tuple[dt.datetime | None, int | None]:
        """Estimate record count and earliest timestamp for a backfill.

        Returns:
            A tuple of (min_timestamp, estimated_records_count).
            If no data exists, returns (None, 0).
        """
        hogql_query = self.get_backfill_info_hogql_query(start_at, end_at)
        context = await self.get_hogql_context()

        context.values["log_comment"] = log_comment

        prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
            hogql_query, context=context, dialect="clickhouse", stack=[]
        )
        assert prepared_hogql_query is not None
        context.output_format = "JSONEachRow"
        printed = print_prepared_ast(
            prepared_hogql_query,
            context=context,
            dialect="clickhouse",
            stack=[],
        )

        if "settings" not in printed.lower():
            printed += " SETTINGS log_comment={log_comment}"
        else:
            printed += ", log_comment={log_comment}"

        query_id = str(uuid.uuid4())
        logger = LOGGER.bind(query_id=query_id)

        with log_query_duration(
            logger=logger,
            query_id=query_id,
            query_type="backfill_info:sessions",
        ):
            async with get_client(team_id=self.team_id) as client:
                result = await client.read_query_as_jsonl(printed, query_parameters=context.values, query_id=query_id)

        min_timestamp_str = result[0]["min_timestamp"]
        record_count = int(result[0]["record_count"])

        min_timestamp = dt.datetime.fromisoformat(min_timestamp_str)
        if min_timestamp.tzinfo is None:
            min_timestamp = min_timestamp.replace(tzinfo=dt.UTC)
        else:
            min_timestamp = min_timestamp.astimezone(dt.UTC)

        if min_timestamp.year == 1970:
            return None, 0

        return min_timestamp, record_count


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
