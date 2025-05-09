from typing import Dict, List, Optional
import logging

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor, clone_expr

logger = logging.getLogger(__name__)

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

# Mapping of regular aggregation functions to their State equivalents
AGGREGATION_TO_STATE_MAPPING = {
    "uniq": "uniqState",
    "uniqIf": "uniqStateIf",
    "count": "countState",
    "countIf": "countStateIf",
    "sum": "sumState",
    "avg": "avgState",
}

# Mapping of State aggregation functions to their Merge equivalents
STATE_TO_MERGE_MAPPING = {
    "uniqState": "uniqMerge",
    "uniqStateIf": "uniqMergeIf",
    "countState": "countMerge",
    "countStateIf": "countMergeIf",
    "sumState": "sumMerge",
    "avgState": "avgMerge",
}


class AggregationToStateTransformer(TraversingVisitor):
    """
    Transforms standard aggregation functions (uniq, count, sum, etc) to their State equivalents
    (uniqState, countState, sumState, etc).
    
    This is used to transform regular ClickHouse queries to be able to combine them
    with pre-aggregated data using the corresponding Merge functions.
    """
    
    def __init__(self):
        super().__init__()
        # Keep track of all transformed functions
        self.transformed_functions: Dict[str, str] = {}
    
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

            # Special case for count() - countState() needs at least one argument
            if func_name == "count" and (not node.args or len(node.args) == 0):
                # Add a literal 1 as an argument for countState
                cloned_node.args = [ast.Constant(value=1)]
            
            # Track the transformation
            self.transformed_functions[func_name] = state_func_name
            # Update only the name in the cloned node
            cloned_node.name = state_func_name
            return cloned_node
        
        return node


def transform_query_to_state(query: ast.SelectQuery) -> ast.SelectQuery:
    """
    Transform a regular query to use State aggregation functions.
    
    Args:
        query: The original query with regular aggregation functions
        
    Returns:
        A new query that uses State aggregation functions
    """
    # Clone the query to avoid modifying the original
    transformed_query = clone_expr(query)
    
    # Create a transformer to transform aggregation functions
    transformer = AggregationToStateTransformer()
    
    # Process each select item individually 
    new_select = []
    for item in transformed_query.select:
        if isinstance(item, ast.Alias):
            # Handle aliases (most common case)
            # Create a copy of the item to avoid modifying the original
            cloned_item = clone_expr(item)
            
            # Apply transformer to the expression within the alias
            cloned_item.expr = transformer.visit(cloned_item.expr)
            new_select.append(cloned_item)
        else:
            # For non-alias items, apply transformer and add to new select list
            new_select.append(transformer.visit(item))
    
    # Replace the select list with the new one
    transformed_query.select = new_select
    
    return transformed_query


def create_merge_wrapper_query(state_query: ast.SelectQuery) -> ast.SelectQuery:
    """
    Wrap a state query in an outer merge query.
    
    Example:
    Input: SELECT uniqState(x) AS a, countState() AS b FROM table
    Output: SELECT uniqMerge(a), countMerge(b) FROM (SELECT uniqState(x) AS a, countState() AS b FROM table)
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
    return ast.SelectQuery(
        select=outer_select,
        select_from=ast.JoinExpr(table=state_query)
    ) 