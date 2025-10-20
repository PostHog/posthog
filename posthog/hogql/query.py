import dataclasses
from typing import ClassVar, Optional, Union, cast

from opentelemetry import trace

from posthog.schema import (
    HogLanguage,
    HogQLFilters,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    HogQLVariable,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext, get_default_limit_for_context
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.filters import replace_filters
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_ast_for_printing, print_ast, print_prepared_ast
from posthog.hogql.resolver_utils import extract_select_queries
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.transforms.preaggregated_table_transformation import do_preaggregated_table_transforms
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tag_queries
from posthog.errors import ExposedCHQueryError
from posthog.models.team import Team
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME

tracer = trace.get_tracer(__name__)


@dataclasses.dataclass
class HogQLQueryExecutor:
    query: Union[str, ast.SelectQuery, ast.SelectSetQuery]
    team: Team
    _: dataclasses.KW_ONLY
    query_type: str = "hogql_query"
    filters: Optional[HogQLFilters] = None
    placeholders: Optional[dict[str, ast.Expr]] = None
    variables: Optional[dict[str, HogQLVariable]] = None
    workload: Workload = Workload.DEFAULT
    settings: Optional[HogQLGlobalSettings] = None
    modifiers: Optional[HogQLQueryModifiers] = None
    limit_context: Optional[LimitContext] = LimitContext.QUERY
    timings: HogQLTimings = dataclasses.field(default_factory=HogQLTimings)
    pretty: Optional[bool] = True
    context: HogQLContext = dataclasses.field(default_factory=lambda: HogQLQueryExecutor.__uninitialized_context)
    hogql_context: Optional[HogQLContext] = None

    __uninitialized_context: ClassVar[HogQLContext] = HogQLContext()

    @tracer.start_as_current_span("HogQLQueryExecutor.__post_init__")
    def __post_init__(self):
        if self.context is self.__uninitialized_context:
            self.context = HogQLContext(team_id=self.team.pk)

        self.query_modifiers = create_default_modifiers_for_team(self.team, self.modifiers)
        self.debug = self.modifiers is not None and self.modifiers.debug
        self.error: Optional[str] = None
        self.explain: Optional[list[str]] = None
        self.results = None
        self.types = None
        self.metadata: Optional[HogQLMetadataResponse] = None

    @tracer.start_as_current_span("HogQLQueryExecutor._parse_query")
    def _parse_query(self):
        with self.timings.measure("query"):
            if isinstance(self.query, ast.SelectQuery) or isinstance(self.query, ast.SelectSetQuery):
                self.select_query = self.query
                self.query = None
            else:
                self.select_query = parse_select(str(self.query), timings=self.timings)

    @tracer.start_as_current_span("HogQLQueryExecutor._process_variables")
    def _process_variables(self):
        with self.timings.measure("variables"):
            if self.variables and len(self.variables.keys()) > 0:
                self.select_query = replace_variables(
                    node=self.select_query, variables=list(self.variables.values()), team=self.team
                )

    @tracer.start_as_current_span("HogQLQueryExecutor._process_placeholders")
    def _process_placeholders(self):
        with self.timings.measure("replace_placeholders"):
            if not self.placeholders:
                self.placeholders = {}
            finder = find_placeholders(self.select_query)

            # Need to use the "filters" system to replace a few special placeholders
            if finder.has_filters:
                if "filters" in self.placeholders and self.filters is not None:
                    raise ValueError(f"Query contains 'filters' both as placeholder and as a query parameter.")
                self.select_query = replace_filters(self.select_query, self.filters, self.team)

            # If there are placeholders remaining
            if finder.placeholder_fields or finder.placeholder_expressions:
                self.select_query = cast(ast.SelectQuery, replace_placeholders(self.select_query, self.placeholders))

    @tracer.start_as_current_span("HogQLQueryExecutor._apply_limit")
    def _apply_limit(self):
        if self.limit_context in (LimitContext.COHORT_CALCULATION, LimitContext.SAVED_QUERY):
            self.context.limit_top_select = False

        with self.timings.measure("max_limit"):
            for one_query in extract_select_queries(self.select_query):
                if one_query.limit is None:
                    one_query.limit = ast.Constant(
                        value=get_default_limit_for_context(self.limit_context or LimitContext.QUERY)
                    )

    @tracer.start_as_current_span("HogQLQueryExecutor._apply_optimizers")
    def _apply_optimizers(self):
        if self.query_modifiers.usePreaggregatedTableTransforms:
            with self.timings.measure("preaggregated_table_transforms"):
                assert self.hogql_context is not None
                assert self.hogql_context.team is not None
                transformed_node = do_preaggregated_table_transforms(self.select_query, self.hogql_context)
                if isinstance(transformed_node, ast.SelectQuery) or isinstance(transformed_node, ast.SelectSetQuery):
                    self.select_query = transformed_node

    @tracer.start_as_current_span("HogQLQueryExecutor._generate_hogql")
    def _generate_hogql(self):
        self.hogql_context = dataclasses.replace(
            self.context,
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            timings=self.timings,
            modifiers=self.query_modifiers,
            limit_context=self.limit_context,
        )

        self._apply_optimizers()

        with self.timings.measure("clone"):
            cloned_query = clone_expr(self.select_query, True)

        with self.timings.measure("prepare_ast_for_printing"):
            select_query_hogql = cast(
                ast.SelectQuery,
                prepare_ast_for_printing(node=cloned_query, context=self.hogql_context, dialect="hogql"),
            )

        with self.timings.measure("print_prepared_ast"):
            self.hogql = print_prepared_ast(
                select_query_hogql,
                self.hogql_context,
                "hogql",
                pretty=self.pretty if self.pretty is not None else True,
            )
            self.print_columns = []
            columns_query = (
                next(extract_select_queries(select_query_hogql))
                if isinstance(select_query_hogql, ast.SelectSetQuery)
                else select_query_hogql
            )
            for node in columns_query.select:
                if isinstance(node, ast.Alias):
                    self.print_columns.append(node.alias)
                else:
                    self.print_columns.append(
                        print_prepared_ast(
                            node=node,
                            context=self.hogql_context,
                            dialect="hogql",
                            stack=[select_query_hogql],
                        )
                    )

    @tracer.start_as_current_span("HogQLQueryExecutor._generate_clickhouse_sql")
    def _generate_clickhouse_sql(self):
        settings = self.settings or HogQLGlobalSettings()
        if self.limit_context in (
            LimitContext.EXPORT,
            LimitContext.COHORT_CALCULATION,
            LimitContext.QUERY_ASYNC,
            LimitContext.SAVED_QUERY,
            LimitContext.RETENTION,
        ):
            settings.max_execution_time = max(settings.max_execution_time or 0, HOGQL_INCREASED_MAX_EXECUTION_TIME)

        if self.query_modifiers.formatCsvAllowDoubleQuotes is not None:
            settings.format_csv_allow_double_quotes = self.query_modifiers.formatCsvAllowDoubleQuotes

        try:
            self.clickhouse_context = dataclasses.replace(
                self.context,
                team_id=self.team.pk,
                team=self.team,
                enable_select_queries=True,
                timings=self.timings,
                modifiers=self.query_modifiers,
                limit_context=self.limit_context,
                # it's valid to reuse the hogql DB because the modifiers are the same,
                # and if we don't we end up creating the virtual DB twice per query
                database=self.hogql_context.database if self.hogql_context else None,
            )
            with self.timings.measure("print_ast"):
                self.clickhouse_sql = print_ast(
                    self.select_query,
                    context=self.clickhouse_context,
                    dialect="clickhouse",
                    settings=settings,
                    pretty=self.pretty if self.pretty is not None else True,
                )
        except Exception as e:
            if self.debug:
                self.clickhouse_sql = ""
                if isinstance(e, ExposedCHQueryError | ExposedHogQLError):
                    self.error = str(e)
                else:
                    self.error = "Unknown error"
            else:
                raise

    @tracer.start_as_current_span("HogQLQueryExecutor._execute_clickhouse_query")
    def _execute_clickhouse_query(self):
        timings_dict = self.timings.to_dict()
        with self.timings.measure("clickhouse_execute"):
            tag_queries(
                team_id=self.team.pk,
                query_type=self.query_type,
                has_joins="JOIN" in self.clickhouse_sql,
                has_json_operations="JSONExtract" in self.clickhouse_sql or "JSONHas" in self.clickhouse_sql,
                timings=timings_dict,
                modifiers=(
                    {k: v for k, v in self.modifiers.model_dump().items() if v is not None} if self.modifiers else {}
                ),
            )

            try:
                self.results, self.types = sync_execute(
                    self.clickhouse_sql,
                    self.clickhouse_context.values,
                    with_column_types=True,
                    workload=self.workload,
                    team_id=self.team.pk,
                    readonly=True,
                )
            except Exception as e:
                if self.debug:
                    self.results = []
                    if isinstance(e, ExposedCHQueryError | ExposedHogQLError):
                        self.error = str(e)
                    else:
                        self.error = "Unknown error"
                else:
                    raise

        if self.debug and self.error is None:  # If the query errored, explain will fail as well.
            with self.timings.measure("explain"):
                explain_results = sync_execute(
                    f"EXPLAIN {self.clickhouse_sql}",
                    self.clickhouse_context.values,
                    with_column_types=True,
                    workload=self.workload,
                    team_id=self.team.pk,
                    readonly=True,
                )
                self.explain = [str(r[0]) for r in explain_results[0]]
            with self.timings.measure("metadata"):
                from posthog.hogql.metadata import get_hogql_metadata

                self.metadata = get_hogql_metadata(
                    HogQLMetadata(language=HogLanguage.HOG_QL, query=self.hogql, debug=True), self.team
                )

    @tracer.start_as_current_span("HogQLQueryExecutor.generate_clickhouse_sql")
    def generate_clickhouse_sql(self) -> tuple[str, HogQLContext]:
        self._parse_query()
        self._process_variables()
        self._process_placeholders()
        self._apply_limit()
        with self.timings.measure("_generate_hogql"):
            self._generate_hogql()
        with self.timings.measure("_generate_clickhouse_sql"):
            self._generate_clickhouse_sql()
        return self.clickhouse_sql, self.clickhouse_context

    @tracer.start_as_current_span("HogQLQueryExecutor.execute")
    def execute(self) -> HogQLQueryResponse:
        self.generate_clickhouse_sql()
        if self.clickhouse_sql is not None:
            self._execute_clickhouse_query()

        return HogQLQueryResponse(
            query=self.query,
            hogql=self.hogql,
            clickhouse=self.clickhouse_sql,
            error=self.error,
            timings=self.timings.to_list(),
            results=self.results,
            columns=self.print_columns,
            types=self.types,
            modifiers=self.query_modifiers,
            explain=self.explain,
            metadata=self.metadata,
        )


def execute_hogql_query(*args, **kwargs) -> HogQLQueryResponse:
    return HogQLQueryExecutor(*args, **kwargs).execute()
