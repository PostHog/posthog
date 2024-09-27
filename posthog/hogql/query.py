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
from posthog.hogql.visitor import clone_expr
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
)
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME


def execute_hogql_query(
    query: Union[str, ast.SelectQuery, ast.SelectUnionQuery],
    team: Team,
    *,
    query_type: str = "hogql_query",
    filters: Optional[HogQLFilters] = None,
    placeholders: Optional[dict[str, ast.Expr]] = None,
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
        context = HogQLContext(team_id=team.pk)

    query_modifiers = create_default_modifiers_for_team(team, modifiers)
    debug = modifiers is not None and modifiers.debug
    error: Optional[str] = None
    explain: Optional[list[str]] = None
    results = None
    types = None
    metadata: Optional[HogQLMetadataResponse] = None

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
        select_queries = (
            select_query.select_queries if isinstance(select_query, ast.SelectUnionQuery) else [select_query]
        )
        for one_query in select_queries:
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
