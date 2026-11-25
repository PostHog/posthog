from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team

from products.data_modeling.backend.facade.contracts import IncrementalConfig
from products.data_modeling.backend.logic.incremental_eligibility import repeated_keys_are_event_duplicates
from products.data_modeling.backend.logic.incremental_filter import parse_model_query

MAX_ROW_LEVEL_INCREMENTAL_ROWS = 40_000_000
ROW_COUNT_QUERY_NAME = "data_modeling_row_level_incremental_row_count"


def fits_the_unique_key_budget(team_id: int, query: str, config: IncrementalConfig) -> bool:
    """False when the config keys every event row and the query returns more rows than one run can check."""
    if not repeated_keys_are_event_duplicates(query, config.unique_key):
        return True
    tag_queries(product=Product.DATA_MODELING, team_id=team_id, name=ROW_COUNT_QUERY_NAME)
    try:
        response = execute_hogql_query(
            query=_bounded_row_count(query),
            team=Team.objects.get(id=team_id),
            workload=Workload.OFFLINE,
            bypass_warehouse_access_control=True,
        )
    except Exception as error:
        capture_exception(error)
        return False
    return response.results[0][0] <= MAX_ROW_LEVEL_INCREMENTAL_ROWS


def _bounded_row_count(query: str) -> ast.SelectQuery:
    rows_past_the_budget = ast.SelectQuery(
        select=[ast.Constant(value=1)],
        select_from=ast.JoinExpr(table=parse_model_query(query)),
        limit=ast.Constant(value=MAX_ROW_LEVEL_INCREMENTAL_ROWS + 1),
    )
    return ast.SelectQuery(
        select=[ast.Call(name="count", args=[])],
        select_from=ast.JoinExpr(table=rows_past_the_budget),
    )
