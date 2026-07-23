import re
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

from products.batch_exports.backend.hogql_source import UnsupportedHogQLQueryError, parse_hogql_select_for_batch_export
from products.batch_exports.backend.service import BatchExportModel, BatchExportSchema
from products.batch_exports.backend.temporal import sql
from products.batch_exports.backend.temporal.metrics import log_query_duration

LOGGER = get_write_only_logger()

Query = str
QueryParameters = dict[str, typing.Any]
BatchExportDateRange = tuple[dt.datetime | None, dt.datetime]


def _print_setting_value(value: typing.Any) -> str:
    """Render a setting value the same way the HogQL printer does."""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


# A SETTINGS clause at the very end of the query, i.e. at the top level: anything after
# a subquery's SETTINGS clause includes at least its closing parenthesis.
TRAILING_SETTINGS_CLAUSE = re.compile(r"\bSETTINGS\s+[^()]*$", re.IGNORECASE)


def append_settings_to_query(printed_query: str, settings_pairs: list[str]) -> str:
    """Append a `SETTINGS` clause (given as `name=value` strings) to a printed query.

    If the query already ends in a top-level SETTINGS clause (the printer merges in
    settings required by some tables), extend it rather than open a second one. A
    SETTINGS clause inside a subquery (e.g. from a lazy table expansion) doesn't count.
    """
    if not settings_pairs:
        return printed_query
    separator = ", " if TRAILING_SETTINGS_CLAUSE.search(printed_query) else " SETTINGS "
    return printed_query + separator + ", ".join(settings_pairs)


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
    def get_hogql_query(
        self, data_interval_start: dt.datetime | None, data_interval_end: dt.datetime
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        """Return the HogQL query to export, scoped to the given data interval."""
        raise NotImplementedError

    def _get_insert_settings(self) -> list[str]:
        """Extra `SETTINGS` (as `name=value` strings) to string-append to the INSERT query.

        Models that bake their settings onto the query AST return an empty list; models
        whose query can lack an AST settings slot (e.g. a UNION, which parses to an
        `ast.SelectSetQuery`) append them here. The log comment is always appended on
        top of these.
        """
        return []

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
        s3_key: str | None,
        s3_secret: str | None,
        num_partitions: int,
    ) -> tuple[Query, QueryParameters]:
        """Produce an `INSERT INTO FUNCTION s3(...)` query and its ClickHouse parameters."""
        printed, parameters = await self._print_query(data_interval_start, data_interval_end, output_format=None)
        printed = append_settings_to_query(printed, [*self._get_insert_settings(), "log_comment={log_comment}"])
        s3_function = sql.get_s3_function_call(s3_folder, s3_key, s3_secret, num_partitions)
        insert_query = f"""
INSERT INTO FUNCTION {s3_function}
{printed}
"""
        return insert_query, parameters


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
                parse_expr("toTimeZone(min($end_timestamp), 'UTC') as min_timestamp"),
                parse_expr("count() as record_count"),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
            where=where_and,
            settings=sql.HogQLQueryBatchExportSettings(),
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

    def _get_insert_settings(self) -> list[str]:
        # The user query may not parse to a simple `ast.SelectQuery` (e.g. a UNION parses
        # to an `ast.SelectSetQuery`, which has no `settings` field to attach these to), so
        # we append them to the printed SQL as a string, which works for either shape.
        return [
            f"{name}={_print_setting_value(value)}"
            for name, value in sql.HogQLQueryBatchExportSettings().model_dump(exclude_none=True).items()
        ]


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
    record_batch_model: RecordBatchModel | None = None
    if batch_export_schema is None:
        model = batch_export_model
        if model is not None:
            model_name = model.name
            extra_query_parameters = model.schema["values"] if model.schema is not None else None
            fields = model.schema["fields"] if model.schema is not None else None
            filters = model.filters

            if model_name == "sessions":
                record_batch_model = SessionsRecordBatchModel(team_id=team_id, batch_export_id=batch_export_id)
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
