import abc
import uuid
import typing
import datetime as dt

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.printer import prepare_ast_for_printing, print_prepared_ast
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse import query_tagging
from posthog.clickhouse.query_tagging import Product
from posthog.credentials import AWSKeyPair
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.hogql_source import (
    UnsupportedHogQLQueryError,
    create_hogql_context_for_batch_export,
    parse_hogql_select_for_batch_export,
)
from products.batch_exports.backend.service import BatchExportModel, BatchExportSchema
from products.batch_exports.backend.temporal.metrics import log_query_duration
from products.batch_exports.backend.temporal.sql.common import (
    BatchExportQuerySettings,
    get_s3_function_call,
    get_user_hogql_batch_export_query_settings,
)
from products.batch_exports.backend.temporal.sql.sessions import SELECT_FROM_SESSIONS_HOGQL, SESSIONS_LOOKBACK_DAYS

LOGGER = get_write_only_logger()

Query = str
QueryParameters = dict[str, typing.Any]
BatchExportDateRange = tuple[dt.datetime | None, dt.datetime]


def _as_clickhouse_request_settings(query_settings: HogQLQuerySettings) -> dict[str, str]:
    """Render HogQL query settings as ClickHouse HTTP-interface settings."""
    return {
        name: "1" if value is True else "0" if value is False else str(value)
        for name, value in query_settings.model_dump(exclude_none=True).items()
    }


class RecordBatchModel(abc.ABC):
    """Base class for models that can be produced as record batches.

    Attributes:
       team_id: The ID of the team we are producing records for.
       batch_export_id: The ID of the batch export we are producing records for.
       wait_for_data_interval_end: Whether to wait before querying until the data
           interval end has passed and replication lag past it has settled. Models
           without data interval semantics query "as of now" and skip the wait.
    """

    wait_for_data_interval_end: bool = True

    def __init__(self, team_id: int, batch_export_id: str | None = None):
        self.team_id = team_id
        self.batch_export_id = batch_export_id

    async def get_hogql_context(self) -> HogQLContext:
        """Return a HogQLContext to generate a ClickHouse query."""
        team = await Team.objects.aget(id=self.team_id)
        # Building the context reads from Postgres, so it must run off the event loop.
        return await database_sync_to_async(create_hogql_context_for_batch_export)(
            team,
            # A bit of a hack: the query references neither half of this, but both are required:
            # - we need to call `get_log_comment` in order to tag the queries
            # - we need to pass non-empty `values` to `ClickHouseClient.prepare_query` to avoid it returning
            # early and not resolving the `{{_partition_id}}` and `%%` escapes in the s3 function
            # call.
            values={"log_comment": self.get_log_comment()},
        )

    def get_log_comment(self) -> str:
        """Tag this export's queries, and return the tags as a log comment.

        The ClickHouse client reads these tags back to set `log_comment` on the requests
        it sends, which is what ties a row in `system.query_log` to its batch export.
        """
        tags = query_tagging.get_query_tags()
        tags.team_id = self.team_id
        if self.batch_export_id:
            tags.batch_export_id = uuid.UUID(self.batch_export_id)
        tags.product = Product.BATCH_EXPORT
        tags.query_type = "batch_export"
        return tags.to_json()

    @abc.abstractmethod
    def get_hogql_query(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        """Return the HogQL query to export, scoped to the given data interval."""
        raise NotImplementedError

    def get_clickhouse_request_settings(self) -> dict[str, str]:
        """ClickHouse settings to apply to this model's queries.

        These are sent as query parameters rather than written into the query, so
        we avoid having to manipulate a `SETTINGS` clause as a string. Models that bake
        their settings onto the query AST (letting the printer render them) need none.
        """
        return {}

    async def _print_query(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime, output_format: str | None
    ) -> tuple[str, QueryParameters]:
        """Transpile the model's HogQL query to ClickHouse SQL, returning it with its parameters."""
        hogql_query = self.get_hogql_query(data_interval_start, data_interval_end)
        context = await self.get_hogql_context()

        prepared_hogql_query = await database_sync_to_async(prepare_ast_for_printing)(
            hogql_query, context=context, dialect="clickhouse", stack=[]
        )
        assert prepared_hogql_query is not None
        if output_format is not None:
            context.output_format = output_format
        # Printing can lazily read from Postgres (e.g. the events table checks the
        # new-events-schema instance setting), so it must run off the event loop.
        printed = await database_sync_to_async(print_prepared_ast)(
            prepared_hogql_query, context=context, dialect="clickhouse", stack=[]
        )
        return printed, context.values

    async def as_query_with_parameters(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> tuple[Query, QueryParameters]:
        """Produce a printed query and any necessary ClickHouse query parameters."""
        return await self._print_query(data_interval_start, data_interval_end, output_format="ArrowStream")

    async def as_insert_into_s3_query_with_parameters(
        self,
        data_interval_start: dt.datetime | None,
        data_interval_end: dt.datetime,
        s3_folder: str,
        credentials: AWSKeyPair | None,
        num_partitions: int,
    ) -> tuple[Query, QueryParameters]:
        """Produce an `INSERT INTO FUNCTION s3(...)` query and its ClickHouse parameters."""
        printed, parameters = await self._print_query(data_interval_start, data_interval_end, output_format=None)
        s3_function = get_s3_function_call(s3_folder, credentials, num_partitions)
        insert_query = f"""
INSERT INTO FUNCTION {s3_function}
{printed}
"""
        return insert_query, parameters


class SessionsRecordBatchModel(RecordBatchModel):
    """A model to produce record batches from the sessions table.

    Attributes:
        is_backfill: Whether this model serves a backfill run. Incremental runs select
            sessions using `_inserted_at` (when the session's events were ingested), so
            sessions receiving late events are re-exported so that they can be updated.
            Backfill runs select instead by `$end_timestamp`.
    """

    def __init__(self, team_id: int, batch_export_id: str | None = None, is_backfill: bool = False):
        super().__init__(team_id=team_id, batch_export_id=batch_export_id)
        self.is_backfill = is_backfill

    def get_hogql_query(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> ast.SelectQuery:
        """Return the HogQLQuery used for the sessions model."""
        hogql_query = clone_expr(SELECT_FROM_SESSIONS_HOGQL)

        team_id_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["sessions", "team_id"]),
            right=ast.Constant(value=self.team_id),
        )

        if self.is_backfill:
            where_and = ast.And(
                exprs=[
                    team_id_filter,
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Lt,
                        left=ast.Field(chain=["$end_timestamp"]),
                        right=ast.Constant(value=data_interval_end),
                    ),
                ]
            )
            if data_interval_start is not None:
                where_and.exprs.append(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GtEq,
                        left=ast.Field(chain=["$end_timestamp"]),
                        right=ast.Constant(value=data_interval_start),
                    ),
                )
        else:
            where_and = ast.And(
                exprs=[
                    team_id_filter,
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
                        # Sessions whose events are ingested more than SESSIONS_LOOKBACK_DAYS
                        # after the session ended are not picked up by incremental runs. This
                        # is a trade-off to avoid a full table scan.
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.GtEq,
                            left=ast.Field(chain=["$end_timestamp"]),
                            right=ast.Constant(value=data_interval_start - SESSIONS_LOOKBACK_DAYS),
                        ),
                    ]
                )

        hogql_query.where = where_and

        return hogql_query

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

        # The estimate mirrors backfill runs, which $end_timestamp semantics.
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
                parse_expr("toTimeZone(min($end_timestamp), 'UTC') as min_timestamp"),
                parse_expr("count() as record_count"),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
            where=where_and,
            settings=BatchExportQuerySettings(),
        )

    async def get_backfill_info(
        self,
        start_at: dt.datetime | None,
        end_at: dt.datetime | None,
        log_comment: str,
        max_execution_time_seconds: int,
    ) -> tuple[dt.datetime | None, int | None]:
        """Estimate record count and earliest timestamp for a backfill.

        Returns:
            A tuple of (min_timestamp, estimated_records_count).
            If no data exists, returns (None, 0).
        """
        hogql_query = self.get_backfill_info_hogql_query(start_at, end_at)
        context = await self.get_hogql_context()

        context.values["log_comment"] = log_comment
        context.values["max_execution_time_seconds"] = max_execution_time_seconds

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

        query_settings = "max_execution_time={max_execution_time_seconds}, log_comment={log_comment}"
        if "settings" not in printed.lower():
            printed += f" SETTINGS {query_settings}"
        else:
            printed += f", {query_settings}"

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


class HogQLQueryRecordBatchModel(RecordBatchModel):
    """A model to produce record batches from an arbitrary HogQL query.

    The query is stored as a raw HogQL string and transpiled to ClickHouse SQL at run
    time, so it stays resilient to printer changes.

    TODO: Data interval bounds are accepted to satisfy the base class contract but ignored: the
    query has no interval semantics yet.
    """

    # The query is executed as-is with no data interval, so there is nothing to wait for.
    wait_for_data_interval_end = False

    def __init__(self, team_id: int, hogql_query: str, batch_export_id: str | None = None):
        super().__init__(team_id=team_id, batch_export_id=batch_export_id)
        self.hogql_query = hogql_query

    def get_hogql_query(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        """Return the parsed HogQL query used for this model.

        The data interval bounds are ignored: the query is exported as-is (see the class
        docstring). They are accepted to satisfy the base class contract.
        """
        return parse_hogql_select_for_batch_export(self.hogql_query)

    def get_clickhouse_request_settings(self) -> dict[str, str]:
        # Sent with the request instead of set on the query AST, because the user query may
        # not parse to a simple `ast.SelectQuery` (e.g. a UNION parses to an
        # `ast.SelectSetQuery`, which has no `settings` field to attach these to).
        return _as_clickhouse_request_settings(get_user_hogql_batch_export_query_settings())


def resolve_batch_exports_model(
    team_id: int,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    batch_export_id: str | None = None,
    is_backfill: bool = False,
):
    """Resolve which model and model parameters to use for a batch export.

    This function exists to isolate a lot of repetitive checks that deal with deprecated
    and new parameters. Eventually, once everything is a `RecordBatchModel`, this could
    be removed.
    """
    model: BatchExportModel | BatchExportSchema | None = None
    record_batch_model: RecordBatchModel | None = None
    if batch_export_schema is None:
        model = batch_export_model
        if model is not None:
            model_name = model.name
            extra_query_parameters = model.schema["values"] if model.schema is not None else None
            fields = model.schema["fields"] if model.schema is not None else None
            filters = model.filters

            if model_name == "sessions":
                record_batch_model = SessionsRecordBatchModel(
                    team_id=team_id, batch_export_id=batch_export_id, is_backfill=is_backfill
                )
            elif model_name == "hogql":
                if model.hogql_query is None:
                    raise UnsupportedHogQLQueryError("Batch export model is 'hogql' but no HogQL query was provided")
                record_batch_model = HogQLQueryRecordBatchModel(
                    team_id=team_id, hogql_query=model.hogql_query, batch_export_id=batch_export_id
                )
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
