from typing import Dict

from posthog.hogql import ast
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS
from posthog.hogql.visitor import TraversingVisitor, clone_expr

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

# Mapping of regular aggregation functions to their State/Merge equivalents.
# These should be present in posthog/hogql/functions/mapping.py clickhouse allows many suffix combinations but
# we are trying to keep the number of transformations minimal for now as State fields are binary data so this
# is only really usefeul internally without the merge wrappers.
SUPPORTED_FUNCTIONS = ["uniq", "uniqIf", "count", "countIf", "sum", "avg"]
HOGQL_AGGREGATIONS_KEYS_SET = set(HOGQL_AGGREGATIONS.keys())
assert set(SUPPORTED_FUNCTIONS).issubset(
    HOGQL_AGGREGATIONS_KEYS_SET
), "All supported aggregation functions must be in HOGQL_AGGREGATIONS"

AGGREGATION_TO_STATE_MAPPING = {
    func: f"{func[:-2]}State{func[-2:]}" if func.endswith("If") else f"{func}State" for func in SUPPORTED_FUNCTIONS
}
assert set(AGGREGATION_TO_STATE_MAPPING.values()).issubset(
    HOGQL_AGGREGATIONS_KEYS_SET
), f"All supported state aggregation functions must be in HOGQL_AGGREGATIONS. Missing: {set(AGGREGATION_TO_STATE_MAPPING.values()) - HOGQL_AGGREGATIONS_KEYS_SET}"

STATE_TO_MERGE_MAPPING = {state: state.replace("State", "Merge") for state in AGGREGATION_TO_STATE_MAPPING.values()}
assert set(STATE_TO_MERGE_MAPPING.keys()).issubset(
    HOGQL_AGGREGATIONS_KEYS_SET
), "All supported aggregation merge functions must be in HOGQL_AGGREGATIONS"


class AggregationStateTransformer(TraversingVisitor):
    """
    Transforms standard aggregation functions (uniq, count, sum, etc) to their State equivalents
    (uniqState, countState, sumState, etc).

    This is used to transform regular ClickHouse queries to be able to combine them
    with pre-aggregated data using the corresponding Merge functions.
    """

    def __init__(self):
        super().__init__()

    def visit_field(self, node: ast.Field) -> ast.Field:
        """Ensure fields are properly cloned and returned."""
        # For Field nodes, just return a clone to ensure we don't lose any properties
        return clone_expr(node)

    def visit_call(self, node: ast.Call) -> ast.Call:
        """Visit a function call and transform it to a State function if it's an aggregation function."""
        # Traverse the arguments first - this replaces the arguments with their transformed versions
        args = []
        for arg in node.args:
            transformed_arg = self.visit(arg)
            # Only add non-None arguments
            if transformed_arg is not None:
                args.append(transformed_arg)
            else:
                # If the transformed arg is None, keep the original argument
                args.append(clone_expr(arg))

        # Update the args in case they were transformed
        node.args = args

        # Check if this is an aggregation function that needs to be transformed
        func_name = node.name
        if func_name in AGGREGATION_TO_STATE_MAPPING:
            # Transform to State function using clone_expr to preserve all properties
            cloned_node = clone_expr(node)
            state_func_name = AGGREGATION_TO_STATE_MAPPING[func_name]

            # Update only the name in the cloned node
            cloned_node.name = state_func_name
            return cloned_node

        return node


def transform_query_to_state_aggregations(query: ast.SelectQuery) -> ast.SelectQuery:
    """
    Transforms a regular query to use State aggregation functions.
    """
    # Clone the query to avoid modifying the original
    transformed_query = clone_expr(query)
    transformer = AggregationStateTransformer()

    new_select = []
    for item in transformed_query.select:
        if isinstance(item, ast.Alias):
            # Handle aliases (most common case)
            cloned_item = clone_expr(item)

            # Apply resolver to the expression within the alias
            cloned_item.expr = transformer.visit(cloned_item.expr)
            new_select.append(cloned_item)
        else:
            # For non-alias items, apply resolver and add to new select list
            new_select.append(transformer.visit(item))

    # Replace the select list with the new one
    transformed_query.select = new_select

    return transformed_query


def wrap_state_query_in_merge_query(state_query: ast.SelectQuery) -> ast.SelectQuery:
    """
    Wrap a state query in an outer merge query so we can get the final results out of it.
    This is useful for testing and combining state queries into a literal result instead of the condensed intermediate state.

    Example:
    Input: SELECT uniqState(x) AS a, countState() AS b FROM table GROUP BY z
    Output: SELECT uniqMerge(a), countMerge(b) FROM (SELECT uniqState(x) AS a, countState() AS b FROM table GROUP BY z) GROUP BY z
    """
    # Create the outer select list with merge functions
    outer_select = []
    for item in state_query.select:
        if isinstance(item, ast.Alias):
            alias_name = item.alias
            if isinstance(item.expr, ast.Call) and item.expr.name in STATE_TO_MERGE_MAPPING:
                # Create a merge function call using the alias as its argument
                merge_func = STATE_TO_MERGE_MAPPING[item.expr.name]
                merge_call = ast.Call(name=merge_func, args=[ast.Field(chain=[alias_name])])
                outer_select.append(ast.Alias(alias=alias_name, expr=merge_call))
            else:
                # For non-state functions, just reference the field
                outer_select.append(ast.Field(chain=[alias_name]))

    # Create the outer query with the inner query as a subquery
    outer_query = ast.SelectQuery(select=outer_select, select_from=ast.JoinExpr(table=state_query))
    
    # If the state query has a GROUP BY, preserve it in the outer query
    if state_query.group_by and len(state_query.group_by) > 0:
        outer_query.group_by = []
        for group_item in state_query.group_by:
            if isinstance(group_item, ast.Alias):
                # If it's an alias, use the alias name as a field reference
                outer_query.group_by.append(ast.Field(chain=[group_item.alias]))
            elif isinstance(group_item, ast.Field):
                # If it's already a field, use it directly if it's a simple field
                if len(group_item.chain) == 1:
                    outer_query.group_by.append(ast.Field(chain=[group_item.chain[0]]))
                else:
                    # For complex fields, we need to reference it in the outer query by its position
                    # in the SELECT clause or its alias if it has one
                    for select_item in state_query.select:
                        if (isinstance(select_item, ast.Alias) and 
                            isinstance(select_item.expr, ast.Field) and 
                            select_item.expr.chain == group_item.chain):
                            outer_query.group_by.append(ast.Field(chain=[select_item.alias]))
                            break
            else:
                # For other expressions, try to find a matching alias in the SELECT
                for select_item in state_query.select:
                    if isinstance(select_item, ast.Alias) and select_item.expr == group_item:
                        outer_query.group_by.append(ast.Field(chain=[select_item.alias]))
                        break

    return outer_query
