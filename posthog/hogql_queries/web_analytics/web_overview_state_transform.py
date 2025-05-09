from typing import Dict, List, Optional
import logging

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor, clone_expr

logger = logging.getLogger(__name__)

# Mapping of regular aggregation functions to their State equivalents
AGGREGATION_TO_STATE_MAPPING = {
    "uniq": "uniqState",
    "count": "countState",
    "countIf": "countIfState",
    "sum": "sumState",
    "avg": "avgState",
    "min": "minState",
    "max": "maxState",
    "any": "anyState",
}

# Mapping of State aggregation functions to their Merge equivalents
STATE_TO_MERGE_MAPPING = {
    "uniqState": "uniqMerge",
    "countState": "countMerge",
    "countIfState": "countIfMerge",
    "sumState": "sumMerge",
    "avgState": "avgMerge",
    "minState": "minMerge",
    "maxState": "maxMerge",
    "anyState": "anyMerge",
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
        
    def visit_call(self, node: ast.Call) -> ast.Call:
        """Visit a function call and transform it to a State function if it's an aggregation function."""
        # Traverse the arguments first
        for i, arg in enumerate(node.args):
            node.args[i] = self.visit(arg)
        
        # Check if this is an aggregation function that needs to be transformed
        func_name = node.name
        if func_name in AGGREGATION_TO_STATE_MAPPING:
            # Transform to State function
            state_func_name = AGGREGATION_TO_STATE_MAPPING[func_name]
            # Track the transformation
            self.transformed_functions[func_name] = state_func_name
            return ast.Call(name=state_func_name, args=node.args)
        
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
        if isinstance(item, ast.Alias) and isinstance(item.expr, ast.Call) and item.expr.name in AGGREGATION_TO_STATE_MAPPING:
            # Apply the transformer to the expression
            transformed_expr = transformer.visit(item.expr)
            
            # Keep the original alias
            new_select.append(ast.Alias(alias=item.alias, expr=transformed_expr))
        else:
            # Apply transformer in case there are nested aggregation functions
            if isinstance(item, ast.Alias):
                transformed_expr = transformer.visit(item.expr)
                new_select.append(ast.Alias(alias=item.alias, expr=transformed_expr))
            else:
                # For non-alias items like fields, just keep them as is
                new_select.append(item)
    
    # Replace the select list with the new one
    transformed_query.select = new_select
    
    return transformed_query


def state_functions_to_merge_functions(query: ast.SelectQuery) -> ast.SelectQuery:
    """
    Transform a query with State aggregation functions to use Merge aggregation functions.
    
    Args:
        query: A query with State aggregation functions
        
    Returns:
        A new query that uses Merge aggregation functions
    """
    # Clone the query to avoid modifying the original
    transformed_query = clone_expr(query)
    
    # Process each select item individually
    new_select = []
    for item in transformed_query.select:
        if isinstance(item, ast.Alias) and isinstance(item.expr, ast.Call) and item.expr.name in STATE_TO_MERGE_MAPPING:
            # Replace with the Merge function
            merge_func_name = STATE_TO_MERGE_MAPPING[item.expr.name]
            merge_expr = ast.Call(name=merge_func_name, args=item.expr.args)
            
            # Keep the original alias
            new_select.append(ast.Alias(alias=item.alias, expr=merge_expr))
        else:
            # Keep the item as is
            new_select.append(item)
    
    # Replace the select list with the new one
    transformed_query.select = new_select
    
    return transformed_query 