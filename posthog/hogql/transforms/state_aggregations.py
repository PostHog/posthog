from typing import Union, cast

from posthog.hogql import ast
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import CloningVisitor

QueryType = Union[ast.SelectQuery, ast.SelectSetQuery]

"""
This module provides utilities for transforming ClickHouse aggregate functions to their State and Merge variants.

ClickHouse supports a two-step aggregation pattern where:
1. Functions like uniq() can be converted to uniqState() for partial aggregation
2. These state functions can then be processed with uniqMerge() to combine partial results

This is useful for:
- Optimizing queries by enabling parallel processing and pre-aggregation
- Creating materialized views with partial aggregates
- Combining preaggregated data with real-time data in a single query
"""

HOGQL_AGGREGATIONS_KEYS_SET = set(HOGQL_AGGREGATIONS.keys())

# Mapping of regular aggregation functions to their State/Merge equivalents.
# These should be present in posthog/hogql/functions/mapping.py
SUPPORTED_FUNCTIONS = ["uniq", "uniqIf", "count", "countIf", "sum", "sumIf", "avg", "avgIf"]
assert set(SUPPORTED_FUNCTIONS).issubset(
    HOGQL_AGGREGATIONS_KEYS_SET
), "All supported aggregation functions must be in HOGQL_AGGREGATIONS"

# Clickhouse allows many suffix combinations but we are trying to keep the number of transformations to just the ones we use now.
AGGREGATION_TO_STATE_MAPPING = {
    func: f"{func[:-2]}State{func[-2:]}" if func.endswith("If") else f"{func}State" for func in SUPPORTED_FUNCTIONS
}
assert set(
    AGGREGATION_TO_STATE_MAPPING.values()
).issubset(
    HOGQL_AGGREGATIONS_KEYS_SET
), f"All supported state aggregation functions must be in HOGQL_AGGREGATIONS. Missing: {set(AGGREGATION_TO_STATE_MAPPING.values()) - HOGQL_AGGREGATIONS_KEYS_SET}"

# Map state functions to their merge counterparts. MergeIf functions do exist but we're not supporting them right now so the filter must be applied on the State intermediate result or using a sumMerge(if(...)).
STATE_TO_MERGE_MAPPING = {
    state_func: f"{state_func.replace('State', 'Merge').replace('If', '')}"
    for state_func in AGGREGATION_TO_STATE_MAPPING.values()
}
assert set(
    STATE_TO_MERGE_MAPPING.values()
).issubset(
    HOGQL_AGGREGATIONS_KEYS_SET
), f"All supported aggregation merge functions must be in HOGQL_AGGREGATIONS. Missing: {set(STATE_TO_MERGE_MAPPING.values()) - HOGQL_AGGREGATIONS_KEYS_SET}"


class AggregationStateTransformer(CloningVisitor):
    """
    Transforms standard aggregation functions (uniq, count, sum, etc) to their State equivalents
    (uniqState, countState, sumState, etc).

    This is mostly used to transform regular ClickHouse queries so we're able to combine them
    with pre-aggregated data using the corresponding Merge functions but can also be used to create
    intermediate aggregation states for other transformations.
    """

    def __init__(self):
        super().__init__(clear_types=True)
        # Tracks depth of queries to identify top-level vs nested
        self.query_depth = 0
        # Tracks whether we're in a top-level SELECT list
        self.in_top_level_select = False

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        """Transform aggregations in SELECT queries."""
        # Track the query depth and update flags
        old_query_depth = self.query_depth
        old_in_top_level_select = self.in_top_level_select

        # Increment query depth for this query
        self.query_depth += 1

        # Set flag for top-level select list of the main query
        is_top_level = self.query_depth == 1
        self.in_top_level_select = is_top_level

        # Let CloningVisitor handle the cloning and transformation of child nodes
        result = super().visit_select_query(node)

        # Restore state
        self.query_depth = old_query_depth
        self.in_top_level_select = old_in_top_level_select

        return result

    def visit_call(self, node: ast.Call) -> ast.Call:
        """Visit a function call and transform it to a State function if it's an aggregation function."""
        result = super().visit_call(node)

        # Only transform aggregation functions in the top-level SELECT list
        if self.in_top_level_select and result.name in AGGREGATION_TO_STATE_MAPPING:
            result.name = AGGREGATION_TO_STATE_MAPPING[result.name]

        return result


def transform_query_to_state_aggregations(query: QueryType) -> QueryType:
    """
    Transforms a regular query to use State aggregation functions.
    This will transform only the top-level aggregation functions.

    Args:
        query: The HogQL query AST to transform
    """
    transformer = AggregationStateTransformer()
    transformed_query = transformer.visit(query)

    return cast(QueryType, transformed_query)


def wrap_state_query_in_merge_query(
    state_query: QueryType,
) -> QueryType:
    """
    Wrap a state query in an outer merge query so we can get the final results out of it.
    This is useful for testing and combining state queries into a literal result instead of the condensed intermediate state.

    Example:
    Input: SELECT uniqState(x) AS a, countState() AS b FROM table GROUP BY z
    Output: SELECT uniqMerge(a), countMerge(b) FROM (SELECT uniqState(x) AS a, countState() AS b FROM table GROUP BY z) GROUP BY z
    """
    # Handle SelectSetQuery (UNION/UNION ALL/etc.)
    if isinstance(state_query, ast.SelectSetQuery):
        # Transform each part of the SelectSetQuery
        transformed_initial = wrap_state_query_in_merge_query(state_query.initial_select_query)
        transformed_subsequent: list[ast.SelectSetNode] = []

        for node in state_query.subsequent_select_queries:
            # Manually create a new SelectSetNode
            node_query = wrap_state_query_in_merge_query(node.select_query)
            transformed_node = ast.SelectSetNode(
                set_operator=node.set_operator, select_query=cast(ast.SelectQuery, node_query)
            )
            transformed_subsequent.append(transformed_node)

        # Create a new SelectSetQuery with the transformed parts
        return ast.SelectSetQuery(
            initial_select_query=cast(ast.SelectQuery, transformed_initial),
            subsequent_select_queries=transformed_subsequent,
        )

    # From here on we're handling a regular SelectQuery
    state_query = cast(ast.SelectQuery, state_query)

    # Create the outer select list with merge functions
    outer_select: list[ast.Expr] = []
    all_field_aliases: set[str] = set()

    # First pass: collect all alias names
    for item in state_query.select:
        if isinstance(item, ast.Alias):
            alias_name = item.alias
            all_field_aliases.add(alias_name)

    # Second pass: build the outer select
    for item in state_query.select:
        if isinstance(item, ast.Alias):
            alias_name = item.alias
            if isinstance(item.expr, ast.Call) and item.expr.name in STATE_TO_MERGE_MAPPING:
                # Create a merge function call using the alias as its argument
                merge_func = STATE_TO_MERGE_MAPPING[item.expr.name]
                merge_call = ast.Call(name=merge_func, args=[ast.Field(chain=[alias_name])])
                outer_select.append(ast.Alias(alias=alias_name, expr=merge_call))
            elif isinstance(item.expr, ast.Tuple):
                outer_tuple_elements: list[ast.Expr] = []
                for i, tuple_element_expr in enumerate(item.expr.exprs):
                    # Access the i-th element (1-indexed) of the aliased tuple from the subquery
                    tuple_accessor = ast.Call(
                        name="tupleElement", args=[ast.Field(chain=[alias_name]), ast.Constant(value=i + 1)]
                    )
                    if isinstance(tuple_element_expr, ast.Call) and tuple_element_expr.name in STATE_TO_MERGE_MAPPING:
                        # If the tuple element is a state aggregation, wrap it in a merge function
                        merge_func_name = STATE_TO_MERGE_MAPPING[tuple_element_expr.name]
                        merged_element = ast.Call(name=merge_func_name, args=[tuple_accessor])
                        outer_tuple_elements.append(merged_element)
                    else:
                        # Otherwise, just access the tuple element
                        outer_tuple_elements.append(tuple_accessor)
                outer_select.append(ast.Alias(alias=alias_name, expr=ast.Tuple(exprs=outer_tuple_elements)))
            elif isinstance(item.expr, ast.Constant):
                # For constants statements like "NULL as xpto", pass through the constant directly
                # This ensures they don't need to be in GROUP BY
                outer_select.append(ast.Alias(alias=alias_name, expr=item.expr))
            else:
                # For non-agg functions, just reference the field directly without group by
                outer_select.append(ast.Alias(alias=alias_name, expr=ast.Field(chain=[alias_name])))
        elif isinstance(item, ast.Constant):
            # For direct constants (like NULL literals), just pass them through directly
            outer_select.append(item)
        else:
            # For non-alias items, just reference them directly
            outer_select.append(item)

    # Create the outer query with the inner query as a subquery
    outer_query = ast.SelectQuery(select=outer_select, select_from=ast.JoinExpr(table=state_query))

    # If the state query has a GROUP BY, preserve it in the outer query
    if state_query.group_by and len(state_query.group_by) > 0:
        outer_group_by: list[ast.Expr] = []

        # For each item in the original GROUP BY
        for group_item in state_query.group_by:
            if isinstance(group_item, ast.Alias):
                # Group by the alias name as a field
                outer_group_by.append(ast.Field(chain=[group_item.alias]))
            elif isinstance(group_item, ast.Field):
                # If it's a field, try to find a matching alias in the SELECT
                if len(group_item.chain) == 1:
                    # Simple field reference - check if it's in our aliases
                    field_name = group_item.chain[0]
                    if field_name in all_field_aliases:
                        outer_group_by.append(ast.Field(chain=[field_name]))
                    else:
                        # Field not aliased in SELECT, use it directly
                        outer_group_by.append(group_item)
                else:
                    # Complex field with a bigger chain. Let's also find a matching alias or use as is
                    found_alias = False
                    for select_item in state_query.select:
                        if (
                            isinstance(select_item, ast.Alias)
                            and isinstance(select_item.expr, ast.Field)
                            and select_item.expr.chain == group_item.chain
                        ):
                            outer_group_by.append(ast.Field(chain=[select_item.alias]))
                            found_alias = True
                            break
                    if not found_alias:
                        # No matching alias, use the field directly
                        outer_group_by.append(group_item)
            else:
                # For expressions, try to find a matching alias in the SELECT
                found_alias = False
                for select_item in state_query.select:
                    if isinstance(select_item, ast.Alias) and select_item.expr == group_item:
                        outer_group_by.append(ast.Field(chain=[select_item.alias]))
                        found_alias = True
                        break
                if not found_alias:
                    outer_group_by.append(group_item)

        if outer_group_by:
            outer_query.group_by = outer_group_by

    # Copy ORDER BY clause from inner to outer query if present
    if state_query.order_by and len(state_query.order_by) > 0:
        outer_order_by: list[ast.OrderExpr] = []

        for order_item in state_query.order_by:
            cloned_order = ast.OrderExpr(expr=order_item.expr, order=order_item.order)

            # If the order expression is a field, try to find a matching alias in the SELECT
            if isinstance(cloned_order.expr, ast.Field) and len(cloned_order.expr.chain) == 1:
                field_name = cloned_order.expr.chain[0]
                if field_name in all_field_aliases:
                    cloned_order.expr = ast.Field(chain=[field_name])

            outer_order_by.append(cloned_order)

        outer_query.order_by = outer_order_by

    # Copy LIMIT and OFFSET from inner to outer query if present
    if state_query.limit is not None:
        outer_query.limit = state_query.limit

    if state_query.offset is not None:
        outer_query.offset = state_query.offset

    return cast(QueryType, outer_query)


def combine_queries_with_state_and_merge(*query_strings: str) -> QueryType:
    """
    Utility function to combine multiple queries using the state + UNION ALL + merge pattern.

    This simulates the common pattern where you have:
    1. Pre-aggregated data (e.g., from materialized views or pre-aggregated tables)
    2. Real-time data that needs to be combined

    This is especially useful for PostHog's web analytics where we combine:
    - Historical data from materialized views (stats_table_preaggregated)
    - Real-time data from events table

    Args:
        *query_strings: Variable number of HogQL query strings to combine

    Returns:
        A wrapped query that combines all input queries with state/merge functions

    Example:
        >>> historical_query = "SELECT uniq(distinct_id) FROM events WHERE date < '2023-01-01'"
        >>> realtime_query = "SELECT uniq(distinct_id) FROM events WHERE date >= '2023-01-01'"
        >>> combined = combine_queries_with_state_and_merge(historical_query, realtime_query)
    """

    if len(query_strings) == 0:
        raise ValueError("At least one query string is required")

    if len(query_strings) == 1:
        query_ast = parse_select(query_strings[0])
        state_query_ast = transform_query_to_state_aggregations(query_ast)
        return wrap_state_query_in_merge_query(state_query_ast)

    state_queries = []
    for query_str in query_strings:
        query_ast = parse_select(query_str)
        state_query_ast = transform_query_to_state_aggregations(query_ast)
        state_queries.append(state_query_ast)

    select_set_query_ast = ast.SelectSetQuery(
        initial_select_query=state_queries[0],
        subsequent_select_queries=[
            ast.SelectSetNode(select_query=state_query, set_operator="UNION ALL") for state_query in state_queries[1:]
        ],
    )

    return wrap_state_query_in_merge_query(select_set_query_ast)
