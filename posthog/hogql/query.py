import dataclasses
from typing import Optional, Union, cast, ClassVar

from posthog.clickhouse.client.connection import Workload
from posthog.errors import ExposedCHQueryError
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext, get_default_limit_for_context
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import replace_placeholders, find_placeholders
from posthog.hogql.printer import (
    prepare_ast_for_printing,
    print_ast,
    print_prepared_ast,
)
from posthog.hogql.filters import replace_filters
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import clone_expr
from posthog.hogql.resolver_utils import extract_select_queries
from posthog.models.team import Team
from posthog.clickhouse.query_tagging import tag_queries
from posthog.client import sync_execute
from posthog.schema import (
    HogQLQueryResponse,
    HogQLFilters,
    HogQLQueryModifiers,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogLanguage,
    HogQLVariable,
)
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME


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

    __uninitialized_context: ClassVar[HogQLContext] = HogQLContext()

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

    def _parse_query(self):
        with self.timings.measure("query"):
            if isinstance(self.query, ast.SelectQuery) or isinstance(self.query, ast.SelectSetQuery):
                self.select_query = self.query
                self.query = None
            else:
                self.select_query = parse_select(str(self.query), timings=self.timings)

    def _process_variables(self):
        with self.timings.measure("variables"):
            if self.variables and len(self.variables.keys()) > 0:
                self.select_query = replace_variables(
                    node=self.select_query, variables=list(self.variables.values()), team=self.team
                )

    def _process_placeholders(self):
        with self.timings.measure("replace_placeholders"):
            placeholders_in_query = find_placeholders(self.select_query)
            self.placeholders = self.placeholders or {}

            if "filters" in self.placeholders and self.filters is not None:
                raise ValueError(
                    f"Query contains 'filters' placeholder, yet filters are also provided as a standalone query parameter."
                )

            if "filters" in placeholders_in_query or any(
                placeholder and placeholder.startswith("filters.") for placeholder in placeholders_in_query
            ):
                self.select_query = replace_filters(self.select_query, self.filters, self.team)

                leftover_placeholders: list[str] = []
                for placeholder in placeholders_in_query:
                    if placeholder is None:
                        raise ValueError("Placeholder expressions are not yet supported")
                    if placeholder != "filters" and not placeholder.startswith("filters."):
                        leftover_placeholders.append(placeholder)
                placeholders_in_query = leftover_placeholders

            if len(placeholders_in_query) > 0:
                if len(self.placeholders) == 0:
                    raise ValueError(
                        f"Query contains placeholders, but none were provided. Placeholders in query: {', '.join(s for s in placeholders_in_query if s is not None)}"
                    )
                self.select_query = replace_placeholders(self.select_query, self.placeholders)

    def _apply_limit(self):
        with self.timings.measure("max_limit"):
            for one_query in extract_select_queries(self.select_query):
                if one_query.limit is None:
                    one_query.limit = ast.Constant(value=get_default_limit_for_context(self.limit_context))

    def _generate_hogql(self):
        with self.timings.measure("hogql"):
            with self.timings.measure("prepare_ast"):
                hogql_query_context = dataclasses.replace(
                    self.context,
                    team_id=self.team.pk,
                    team=self.team,
                    enable_select_queries=True,
                    timings=self.timings,
                    modifiers=self.query_modifiers,
                )

            with self.timings.measure("clone"):
                cloned_query = clone_expr(self.select_query, True)

            select_query_hogql = cast(
                ast.SelectQuery,
                prepare_ast_for_printing(node=cloned_query, context=hogql_query_context, dialect="hogql"),
            )

        with self.timings.measure("print_ast"):
            self.hogql = print_prepared_ast(
                select_query_hogql,
                hogql_query_context,
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
                            context=hogql_query_context,
                            dialect="hogql",
                            stack=[select_query_hogql],
                        )
                    )

    def _generate_clickhouse_sql(self):
        settings = self.settings or HogQLGlobalSettings()
        if self.limit_context in (LimitContext.EXPORT, LimitContext.COHORT_CALCULATION, LimitContext.QUERY_ASYNC):
            settings.max_execution_time = HOGQL_INCREASED_MAX_EXECUTION_TIME
        try:
            self.clickhouse_context = dataclasses.replace(
                self.context,
                team_id=self.team.pk,
                team=self.team,
                enable_select_queries=True,
                timings=self.timings,
                modifiers=self.query_modifiers,
            )
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

    def _execute_clickhouse_query(self):
        timings_dict = self.timings.to_dict()
        with self.timings.measure("clickhouse_execute"):
            tag_queries(
                team_id=self.team.pk,
                query_type=self.query_type,
                has_joins="JOIN" in self.clickhouse_sql,
                has_json_operations="JSONExtract" in self.clickhouse_sql or "JSONHas" in self.clickhouse_sql,
                timings=timings_dict,
                modifiers={k: v for k, v in self.modifiers.model_dump().items() if v is not None}
                if self.modifiers
                else {},
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

    def generate_clickhouse_sql(self) -> tuple[str, HogQLContext]:
        self._parse_query()
        self._process_variables()
        self._process_placeholders()
        self._apply_limit()
        self._generate_hogql()
        self._generate_clickhouse_sql()
        return self.clickhouse_sql, self.clickhouse_context

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


"""
import dataclasses
from typing import Optional, Union, cast

from posthog.clickhouse.client.connection import Workload
from posthog.errors import ExposedCHQueryError
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext, get_default_limit_for_context
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import replace_placeholders, find_placeholders
from posthog.hogql.printer import (
    prepare_ast_for_printing,
    print_ast,
    print_prepared_ast,
)
from posthog.hogql.filters import replace_filters
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import clone_expr
from posthog.hogql.resolver_utils import extract_select_queries
from posthog.models.team import Team
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql.database.database import create_hogql_database
from posthog.client import sync_execute
from posthog.schema import (
    HogQLQueryResponse,
    HogQLFilters,
    HogQLQueryModifiers,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogLanguage,
    HogQLVariable,
)
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME


def execute_hogql_query(
        query: Union[str, ast.SelectQuery, ast.SelectSetQuery],
        team: Team,
        *,
        query_type: str = "hogql_query",
        filters: Optional[HogQLFilters] = None,
        placeholders: Optional[dict[str, ast.Expr]] = None,
        variables: Optional[dict[str, HogQLVariable]] = None,
        workload: Workload = Workload.DEFAULT,
        settings: Optional[HogQLGlobalSettings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = LimitContext.QUERY,
        timings: Optional[HogQLTimings] = None,
        pretty: Optional[bool] = True,
        context: Optional[HogQLContext] = None,
) -> HogQLQueryResponse:
    if timings is None:
        timings = HogQLTimings()

    if context is None:
        context = HogQLContext(team_id=team.pk, timings=timings)
        with timings.measure("create_hogql_database"):
            context.database = create_hogql_database(team.pk, modifiers, team_arg=team, timings=timings)

    query_modifiers = create_default_modifiers_for_team(team, modifiers)
    debug = modifiers is not None and modifiers.debug
    error: Optional[str] = None
    explain: Optional[list[str]] = None
    results = None
    types = None
    metadata: Optional[HogQLMetadataResponse] = None

    with timings.measure("query"):
        if isinstance(query, ast.SelectQuery) or isinstance(query, ast.SelectSetQuery):
            select_query = query
            query = None
        else:
            select_query = parse_select(str(query), timings=timings)

    with timings.measure("variables"):
        if variables and len(variables.keys()) > 0:
            select_query = replace_variables(node=select_query, variables=list(variables.values()), team=team)

    with timings.measure("replace_placeholders"):
        placeholders_in_query = find_placeholders(select_query)
        placeholders = placeholders or {}

        if "filters" in placeholders and filters is not None:
            raise ValueError(
                f"Query contains 'filters' placeholder, yet filters are also provided as a standalone query parameter."
            )
        if "filters" in placeholders_in_query or any(
                placeholder and placeholder.startswith("filters.") for placeholder in placeholders_in_query
        ):
            select_query = replace_filters(select_query, filters, team)

            leftover_placeholders: list[str] = []
            for placeholder in placeholders_in_query:
                if placeholder is None:
                    raise ValueError("Placeholder expressions are not yet supported")
                if placeholder != "filters" and not placeholder.startswith("filters."):
                    leftover_placeholders.append(placeholder)

            placeholders_in_query = leftover_placeholders

        if len(placeholders_in_query) > 0:
            if len(placeholders) == 0:
                raise ValueError(
                    f"Query contains placeholders, but none were provided. Placeholders in query: {', '.join(s for s in placeholders_in_query if s is not None)}"
                )
            select_query = replace_placeholders(select_query, placeholders)

    with timings.measure("max_limit"):
        for one_query in extract_select_queries(select_query):
            if one_query.limit is None:
                one_query.limit = ast.Constant(value=get_default_limit_for_context(limit_context))

    # Get printed HogQL query, and returned columns. Using a cloned query.
    with timings.measure("hogql"):
        with timings.measure("prepare_ast"):
            hogql_query_context = dataclasses.replace(
                context,
                # set the team.pk here so someone can't pass a context for a different team 🤷‍️
                team_id=team.pk,
                team=team,
                enable_select_queries=True,
                timings=timings,
                modifiers=query_modifiers,
            )

            with timings.measure("clone"):
                cloned_query = clone_expr(select_query, True)
            select_query_hogql = cast(
                ast.SelectQuery,
                prepare_ast_for_printing(node=cloned_query, context=hogql_query_context, dialect="hogql"),
            )

        with timings.measure("print_ast"):
            hogql = print_prepared_ast(
                select_query_hogql, hogql_query_context, "hogql", pretty=pretty if pretty is not None else True
            )
            print_columns = []
            columns_query = (
                next(extract_select_queries(select_query_hogql))
                if isinstance(select_query_hogql, ast.SelectSetQuery)
                else select_query_hogql
            )
            for node in columns_query.select:
                if isinstance(node, ast.Alias):
                    print_columns.append(node.alias)
                else:
                    print_columns.append(
                        print_prepared_ast(
                            node=node,
                            context=hogql_query_context,
                            dialect="hogql",
                            stack=[select_query_hogql],
                        )
                    )

    settings = settings or HogQLGlobalSettings()
    if limit_context in (LimitContext.EXPORT, LimitContext.COHORT_CALCULATION, LimitContext.QUERY_ASYNC):
        settings.max_execution_time = HOGQL_INCREASED_MAX_EXECUTION_TIME

    # Print the ClickHouse SQL query
    with timings.measure("print_ast"):
        try:
            clickhouse_context = dataclasses.replace(
                context,
                # set the team.pk here so someone can't pass a context for a different team 🤷‍️
                team_id=team.pk,
                team=team,
                enable_select_queries=True,
                timings=timings,
                modifiers=query_modifiers,
            )
            clickhouse_sql = print_ast(
                select_query,
                context=clickhouse_context,
                dialect="clickhouse",
                settings=settings,
                pretty=pretty if pretty is not None else True,
            )
        except Exception as e:
            if debug:
                clickhouse_sql = None
                if isinstance(e, ExposedCHQueryError | ExposedHogQLError):
                    error = str(e)
                else:
                    error = "Unknown error"
            else:
                raise

    if clickhouse_sql is not None:
        timings_dict = timings.to_dict()
        with timings.measure("clickhouse_execute"):
            tag_queries(
                team_id=team.pk,
                query_type=query_type,
                has_joins="JOIN" in clickhouse_sql,
                has_json_operations="JSONExtract" in clickhouse_sql or "JSONHas" in clickhouse_sql,
                timings=timings_dict,
                modifiers={k: v for k, v in modifiers.model_dump().items() if v is not None} if modifiers else {},
            )

            try:
                results, types = sync_execute(
                    clickhouse_sql,
                    clickhouse_context.values,
                    with_column_types=True,
                    workload=workload,
                    team_id=team.pk,
                    readonly=True,
                )
            except Exception as e:
                if debug:
                    results = []
                    if isinstance(e, ExposedCHQueryError | ExposedHogQLError):
                        error = str(e)
                    else:
                        error = "Unknown error"
                else:
                    raise

        if debug and error is None:  # If the query errored, explain will fail as well.
            with timings.measure("explain"):
                explain_results = sync_execute(
                    f"EXPLAIN {clickhouse_sql}",
                    clickhouse_context.values,
                    with_column_types=True,
                    workload=workload,
                    team_id=team.pk,
                    readonly=True,
                )
                explain = [str(r[0]) for r in explain_results[0]]
            with timings.measure("metadata"):
                from posthog.hogql.metadata import get_hogql_metadata

                metadata = get_hogql_metadata(HogQLMetadata(language=HogLanguage.HOG_QL, query=hogql, debug=True), team)

    return HogQLQueryResponse(
        query=query,
        hogql=hogql,
        clickhouse=clickhouse_sql,
        error=error,
        timings=timings.to_list(),
        results=results,
        columns=print_columns,
        types=types,
        modifiers=query_modifiers,
        explain=explain,
        metadata=metadata,
    )
"""
