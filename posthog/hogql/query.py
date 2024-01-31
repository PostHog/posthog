from typing import Dict, Optional, Union, cast

from posthog.clickhouse.client.connection import Workload
from posthog.errors import ExposedCHQueryError
from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext, get_default_limit_for_context
from posthog.hogql.errors import HogQLException
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
from posthog.hogql.visitor import clone_expr
from posthog.models.team import Team
from posthog.clickhouse.query_tagging import tag_queries
from posthog.client import sync_execute
from posthog.schema import HogQLQueryResponse, HogQLFilters, HogQLQueryModifiers

INCREASED_MAX_EXECUTION_TIME = 600


def execute_hogql_query(
    query: Union[str, ast.SelectQuery, ast.SelectUnionQuery],
    team: Team,
    query_type: str = "hogql_query",
    filters: Optional[HogQLFilters] = None,
    placeholders: Optional[Dict[str, ast.Expr]] = None,
    workload: Workload = Workload.ONLINE,
    settings: Optional[HogQLGlobalSettings] = None,
    modifiers: Optional[HogQLQueryModifiers] = None,
    limit_context: Optional[LimitContext] = LimitContext.QUERY,
    timings: Optional[HogQLTimings] = None,
    explain: Optional[bool] = False,
    pretty: Optional[bool] = True,
) -> HogQLQueryResponse:
    if timings is None:
        timings = HogQLTimings()

    query_modifiers = create_default_modifiers_for_team(team, modifiers)

    with timings.measure("query"):
        if isinstance(query, ast.SelectQuery) or isinstance(query, ast.SelectUnionQuery):
            select_query = query
            query = None
        else:
            select_query = parse_select(str(query), timings=timings)

    with timings.measure("replace_placeholders"):
        placeholders_in_query = find_placeholders(select_query)
        placeholders = placeholders or {}

        if "filters" in placeholders and filters is not None:
            raise HogQLException(
                f"Query contains 'filters' placeholder, yet filters are also provided as a standalone query parameter."
            )
        if "filters" in placeholders_in_query:
            select_query = replace_filters(select_query, filters, team)
            placeholders_in_query.remove("filters")

        if len(placeholders_in_query) > 0:
            if len(placeholders) == 0:
                raise HogQLException(
                    f"Query contains placeholders, but none were provided. Placeholders in query: {', '.join(placeholders_in_query)}"
                )
            select_query = replace_placeholders(select_query, placeholders)

    with timings.measure("max_limit"):
        select_queries = (
            select_query.select_queries if isinstance(select_query, ast.SelectUnionQuery) else [select_query]
        )
        for one_query in select_queries:
            if one_query.limit is None:
                one_query.limit = ast.Constant(value=get_default_limit_for_context(limit_context))

    # Get printed HogQL query, and returned columns. Using a cloned query.
    with timings.measure("hogql"):
        with timings.measure("prepare_ast"):
            hogql_query_context = HogQLContext(
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
                select_query_hogql.select_queries[0]
                if isinstance(select_query_hogql, ast.SelectUnionQuery)
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
        settings.max_execution_time = INCREASED_MAX_EXECUTION_TIME

    # Print the ClickHouse SQL query
    with timings.measure("print_ast"):
        clickhouse_context = HogQLContext(
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

    timings_dict = timings.to_dict()
    with timings.measure("clickhouse_execute"):
        tag_queries(
            team_id=team.pk,
            query_type=query_type,
            has_joins="JOIN" in clickhouse_sql,
            has_json_operations="JSONExtract" in clickhouse_sql or "JSONHas" in clickhouse_sql,
            timings=timings_dict,
        )

        error = None
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
            if explain:
                results, types = None, None
                if isinstance(e, (ExposedCHQueryError, HogQLException)):
                    error = str(e)
                else:
                    error = "Unknown error"
            else:
                raise e

    if explain and error is None:  # If the query errored, explain will fail as well.
        with timings.measure("explain"):
            explain_results = sync_execute(
                f"EXPLAIN {clickhouse_sql}",
                clickhouse_context.values,
                with_column_types=True,
                workload=workload,
                team_id=team.pk,
                readonly=True,
            )
            explain_output = [str(r[0]) for r in explain_results[0]]
    else:
        explain_output = None

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
        explain=explain_output,
    )
