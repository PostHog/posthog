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
# These should be present in posthog/hogql/functions/mapping.py
#
# Clickhouse allows many suffix combinations but we are trying to keep the number of transformations minimal
# for now as State fields are binary data so this is only really usefeul internally without the merge wrappers.
SUPPORTED_FUNCTIONS = ["uniq", "uniqIf", "count", "countIf", "sum", "avg", "sumIf", "avgIf"]
HOGQL_AGGREGATIONS_KEYS_SET = set(HOGQL_AGGREGATIONS.keys())
assert set(SUPPORTED_FUNCTIONS).issubset(
    HOGQL_AGGREGATIONS_KEYS_SET
), "All supported aggregation functions must be in HOGQL_AGGREGATIONS"

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


class AggregationStateTransformer(TraversingVisitor):
    """
    Transforms standard aggregation functions (uniq, count, sum, etc) to their State equivalents
    (uniqState, countState, sumState, etc).

    This is mostly used to transform regular ClickHouse queries so we're able to combine them
    with pre-aggregated data using the corresponding Merge functions but can also be used to create
    intermediate aggregation states for other transformations.
    """

    def __init__(self, transform_nested_aggregations=False):
        super().__init__()
        # Flag to control whether nested aggregations should be transformed
        self.transform_nested_aggregations = transform_nested_aggregations
        # Tracks depth of queries to identify top-level vs nested
        self.query_depth = 0
        # Tracks whether we're in a top-level SELECT list
        self.in_top_level_select = False

    def visit_field(self, node: ast.Field) -> ast.Field:
        """Ensure fields are properly cloned and returned."""
        # For Field nodes, just return a clone to ensure we don't lose any properties
        return clone_expr(node)

    def visit_constant(self, node: ast.Constant) -> ast.Constant:
        """Handle constants including NULL literals."""
        return clone_expr(node)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        """Transform aggregations in SELECT queries."""
        # Clone the query to avoid modifying the original
        transformed_query = clone_expr(node)

        # Track the query depth
        old_query_depth = self.query_depth
        old_in_top_level_select = self.in_top_level_select

        # Increment query depth for this query
        self.query_depth += 1

        # Set flag for top-level select list of the main query
        is_top_level = self.query_depth == 1

        # First handle the FROM clause and subqueries - before processing the select list
        if transformed_query.select_from is not None:
            transformed_query.select_from = self.visit(transformed_query.select_from)

        # Handle WHERE clause
        if transformed_query.where is not None:
            transformed_query.where = self.visit(transformed_query.where)

        # Now process the SELECT list, with appropriate flag for top-level
        self.in_top_level_select = is_top_level
        new_select = []
        for item in transformed_query.select:
            if isinstance(item, ast.Alias):
                # Handle aliases
                cloned_item = clone_expr(item)
                cloned_item.expr = self.visit(cloned_item.expr)
                new_select.append(cloned_item)
            else:
                # For non-alias items, apply resolver
                new_select.append(self.visit(item))

        transformed_query.select = new_select
        self.in_top_level_select = old_in_top_level_select

        # Handle GROUP BY
        if transformed_query.group_by is not None:
            new_group_by = []
            for item in transformed_query.group_by:
                new_group_by.append(self.visit(item))
            transformed_query.group_by = new_group_by

        # Handle HAVING
        if transformed_query.having is not None:
            transformed_query.having = self.visit(transformed_query.having)

        # Restore query depth
        self.query_depth = old_query_depth

        return transformed_query

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        """Handle JOIN expressions and transform any subqueries in them."""
        cloned_node = clone_expr(node)

        # Transform table if it's a subquery
        if isinstance(cloned_node.table, ast.SelectQuery):
            cloned_node.table = self.visit(cloned_node.table)

        # Transform the constraint if it exists
        if cloned_node.constraint is not None:
            cloned_node.constraint = self.visit(cloned_node.constraint)

        return cloned_node

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> ast.ArithmeticOperation:
        """Visit arithmetic operations to handle expressions in WHERE clauses."""
        cloned_node = clone_expr(node)
        cloned_node.left = self.visit(cloned_node.left)
        cloned_node.right = self.visit(cloned_node.right)
        return cloned_node

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.CompareOperation:
        """Visit compare operations to handle expressions in WHERE clauses."""
        cloned_node = clone_expr(node)
        cloned_node.left = self.visit(cloned_node.left)
        cloned_node.right = self.visit(cloned_node.right)
        return cloned_node

    def visit_call(self, node: ast.Call) -> ast.Call:
        """Visit a function call and transform it to a State function if it's an aggregation function."""
        # First handle the arguments
        cloned_node = clone_expr(node)

        # Process arguments
        for i, arg in enumerate(cloned_node.args):
            visited_arg = self.visit(arg)
            if visited_arg is not None:
                cloned_node.args[i] = visited_arg
            # If visit returns None, we keep the original argument

        # Only transform aggregation functions in the top-level SELECT list or if explicitly requested
        if (
            self.in_top_level_select or self.transform_nested_aggregations
        ) and cloned_node.name in AGGREGATION_TO_STATE_MAPPING:
            # Transform to State function
            state_func_name = AGGREGATION_TO_STATE_MAPPING[cloned_node.name]
            cloned_node.name = state_func_name

        return cloned_node


def transform_query_to_state_aggregations(
    query: ast.SelectQuery, transform_nested_aggregations=False
) -> ast.SelectQuery:
    """
    Transforms a regular query to use State aggregation functions.
    This will transform only the top-level aggregation functions by default.

    Args:
        query: The HogQL query AST to transform
        transform_nested_aggregations: Whether to transform nested aggregations (default: False)
    """
    # Use the transformer to recursively transform all levels of the query
    transformer = AggregationStateTransformer(transform_nested_aggregations=transform_nested_aggregations)
    transformed_query = transformer.visit(query)

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
    # Track which fields need to be in GROUP BY (those used by aggregation functions)
    agg_fields = set()
    # Track aliased fields
    all_field_aliases = set()

    # First pass: collect all alias names and identify which ones are used in aggregations
    for item in state_query.select:
        if isinstance(item, ast.Alias):
            alias_name = item.alias
            all_field_aliases.add(alias_name)
            # Check if the expression is an aggregation state function
            if isinstance(item.expr, ast.Call) and item.expr.name in STATE_TO_MERGE_MAPPING:
                agg_fields.add(alias_name)

    # Second pass: build the outer select
    for item in state_query.select:
        if isinstance(item, ast.Alias):
            alias_name = item.alias
            if isinstance(item.expr, ast.Call) and item.expr.name in STATE_TO_MERGE_MAPPING:
                # Create a merge function call using the alias as its argument
                merge_func = STATE_TO_MERGE_MAPPING[item.expr.name]
                merge_call = ast.Call(name=merge_func, args=[ast.Field(chain=[alias_name])])
                outer_select.append(ast.Alias(alias=alias_name, expr=merge_call))
            elif isinstance(item.expr, ast.Constant):
                # For constants statements like "NULL as xpto, pass through the constant directly
                # This ensures they don't need to be in GROUP BY
                outer_select.append(ast.Alias(alias=alias_name, expr=clone_expr(item.expr)))
            else:
                # For non-state functions, just reference the field directly without group by
                outer_select.append(ast.Alias(alias=alias_name, expr=ast.Field(chain=[alias_name])))
        elif isinstance(item, ast.Constant):
            # For direct constants (like NULL literals), just pass them through directly
            outer_select.append(clone_expr(item))
        else:
            # For non-alias items, just reference them directly
            outer_select.append(clone_expr(item))

    # Create the outer query with the inner query as a subquery
    outer_query = ast.SelectQuery(select=outer_select, select_from=ast.JoinExpr(table=state_query))

    # If the state query has a GROUP BY, preserve it in the outer query
    if state_query.group_by and len(state_query.group_by) > 0:
        outer_group_by = []

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
                        outer_group_by.append(clone_expr(group_item))
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
                        outer_group_by.append(clone_expr(group_item))
            else:
                # For expressions, try to find a matching alias in the SELECT, if we can't lets just clone the expression
                found_alias = False
                for select_item in state_query.select:
                    if isinstance(select_item, ast.Alias) and select_item.expr == group_item:
                        outer_group_by.append(ast.Field(chain=[select_item.alias]))
                        found_alias = True
                        break
                if not found_alias:
                    outer_group_by.append(clone_expr(group_item))

        if outer_group_by:
            outer_query.group_by = outer_group_by

    # Copy ORDER BY clause from inner to outer query if present
    if state_query.order_by and len(state_query.order_by) > 0:
        outer_order_by = []

        for order_item in state_query.order_by:
            cloned_order = clone_expr(order_item)

            # If the order expression is a field, try to find a matching alias in the SELECT
            if isinstance(cloned_order.expr, ast.Field) and len(cloned_order.expr.chain) == 1:
                field_name = cloned_order.expr.chain[0]
                if field_name in all_field_aliases:
                    cloned_order.expr = ast.Field(chain=[field_name])

            outer_order_by.append(cloned_order)

        outer_query.order_by = outer_order_by

    # Copy LIMIT from inner to outer query if present
    if state_query.limit is not None:
        outer_query.limit = clone_expr(state_query.limit)

    # Copy OFFSET from inner to outer query if present
    if state_query.offset is not None:
        outer_query.offset = clone_expr(state_query.offset)

    return outer_query
