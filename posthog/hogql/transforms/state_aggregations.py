# mypy: disable-error-code="unreachable"
# mypy considers some of the expression copies unreachable because of the SelectSetNode not inheriting from AST/Expr.
from posthog.hogql import ast
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS
from posthog.hogql.visitor import TraversingVisitor, clone_expr
from typing import Union, Optional, cast

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
# Clickhouse allows many suffix combinations but we are trying to keep the number of transformations to just the ones we use now.
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
        return cast(ast.Field, clone_expr(node))

    def visit_constant(self, node: ast.Constant) -> ast.Constant:
        """Handle constants including NULL literals."""
        return cast(ast.Constant, clone_expr(node))

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        """Transform aggregations in SELECT queries."""
        # Clone the query to avoid modifying the original
        transformed_query = cast(ast.SelectQuery, clone_expr(node))

        # Track the query depth
        old_query_depth = self.query_depth
        old_in_top_level_select = self.in_top_level_select

        # Increment query depth for this query
        self.query_depth += 1

        # Set flag for top-level select list of the main query
        is_top_level = self.query_depth == 1

        # First handle the FROM clause and subqueries - before processing the select list
        if transformed_query.select_from is not None:
            transformed_query.select_from = cast(ast.JoinExpr, self.visit(transformed_query.select_from))

        # Handle WHERE clause
        if transformed_query.where is not None:
            transformed_query.where = cast(ast.Expr, self.visit(transformed_query.where))

        # Now process the SELECT list, with appropriate flag for top-level
        self.in_top_level_select = is_top_level
        new_select: list[ast.Expr] = []
        for item in transformed_query.select:
            if isinstance(item, ast.Alias):
                # Handle aliases
                cloned_item = cast(ast.Alias, clone_expr(item))
                visited_expr = self.visit(cloned_item.expr)
                if visited_expr is not None:
                    cloned_item.expr = cast(ast.Expr, visited_expr)
                new_select.append(cloned_item)
            else:
                # For non-alias items, apply resolver
                visited_item = self.visit(item)
                if visited_item is not None:
                    new_select.append(cast(ast.Expr, visited_item))

        transformed_query.select = new_select
        self.in_top_level_select = old_in_top_level_select

        # Handle GROUP BY
        if transformed_query.group_by is not None:
            new_group_by: list[ast.Expr] = []
            for item in transformed_query.group_by:
                visited_item = self.visit(item)
                if visited_item is not None:
                    new_group_by.append(cast(ast.Expr, visited_item))
            transformed_query.group_by = new_group_by

        # Handle HAVING
        if transformed_query.having is not None:
            transformed_query.having = cast(ast.Expr, self.visit(transformed_query.having))

        # Remove LIMIT and ORDER BY from inner queries as they could affect aggregation results
        if self.query_depth > 1:  # This is not a top-level query
            transformed_query.limit = None
            transformed_query.order_by = None

        # Restore query depth
        self.query_depth = old_query_depth

        return transformed_query

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        """Handle JOIN expressions and transform any subqueries in them."""
        cloned_node = cast(ast.JoinExpr, clone_expr(node))

        # Transform table if it's a subquery
        if isinstance(cloned_node.table, ast.SelectQuery):
            visited_table = self.visit(cloned_node.table)
            if visited_table is not None:
                cloned_node.table = cast(
                    Union[ast.SelectQuery, ast.SelectSetQuery, ast.Placeholder, ast.HogQLXTag, ast.Field],
                    visited_table,
                )

        # Transform the constraint if it exists
        if cloned_node.constraint is not None:
            visited_constraint = self.visit(cloned_node.constraint)
            if visited_constraint is not None:
                if isinstance(visited_constraint, ast.JoinConstraint):
                    cloned_node.constraint = visited_constraint
                else:
                    # If the visit returns an Expr but not JoinConstraint, we need to wrap it
                    expr = cast(ast.Expr, visited_constraint)
                    if isinstance(node.constraint, ast.JoinConstraint):
                        cloned_node.constraint = ast.JoinConstraint(
                            expr=expr, constraint_type=node.constraint.constraint_type
                        )

        return cloned_node

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation) -> ast.ArithmeticOperation:
        """Visit arithmetic operations to handle expressions in WHERE clauses."""
        cloned_node = cast(ast.ArithmeticOperation, clone_expr(node))
        visited_left = self.visit(cloned_node.left)
        if visited_left is not None:
            cloned_node.left = cast(ast.Expr, visited_left)
        visited_right = self.visit(cloned_node.right)
        if visited_right is not None:
            cloned_node.right = cast(ast.Expr, visited_right)
        return cloned_node

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.CompareOperation:
        """Visit compare operations to handle expressions in WHERE clauses."""
        cloned_node = cast(ast.CompareOperation, clone_expr(node))
        visited_left = self.visit(cloned_node.left)
        if visited_left is not None:
            cloned_node.left = cast(ast.Expr, visited_left)
        visited_right = self.visit(cloned_node.right)
        if visited_right is not None:
            cloned_node.right = cast(ast.Expr, visited_right)
        return cloned_node

    def visit_call(self, node: ast.Call) -> ast.Call:
        """Visit a function call and transform it to a State function if it's an aggregation function."""
        # First handle the arguments
        cloned_node = cast(ast.Call, clone_expr(node))

        # Process arguments
        for i, arg in enumerate(cloned_node.args):
            visited_arg = self.visit(arg)
            if visited_arg is not None:
                cloned_node.args[i] = cast(ast.Expr, visited_arg)
            # If visit returns None, we keep the original argument

        # Only transform aggregation functions in the top-level SELECT list or if explicitly requested
        if (
            self.in_top_level_select or self.transform_nested_aggregations
        ) and cloned_node.name in AGGREGATION_TO_STATE_MAPPING:
            # Transform to State function
            state_func_name = AGGREGATION_TO_STATE_MAPPING[cloned_node.name]
            cloned_node.name = state_func_name

        return cloned_node

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        """Transform UNION/UNION ALL/etc. queries."""
        # Clone the query to avoid modifying the original
        transformed_query = cast(ast.SelectSetQuery, clone_expr(node))

        # Transform the initial select query
        visited_initial = self.visit(transformed_query.initial_select_query)
        if visited_initial is not None:
            transformed_query.initial_select_query = cast(ast.SelectQuery, visited_initial)

        # Transform all subsequent select queries
        transformed_subsequent: list[ast.SelectSetNode] = []
        for _, subsequent_node in enumerate(transformed_query.subsequent_select_queries):
            # Instead of using clone_expr which has type variable issues with SelectSetNode,
            # manually create a new SelectSetNode
            visited_query = self.visit(subsequent_node.select_query)
            if visited_query is not None:
                select_query = cast(ast.SelectQuery, visited_query)
            else:
                select_query = subsequent_node.select_query

            transformed_subsequent.append(
                ast.SelectSetNode(set_operator=subsequent_node.set_operator, select_query=select_query)
            )

        transformed_query.subsequent_select_queries = transformed_subsequent

        return transformed_query

    def visit_select_set_node(self, node: ast.SelectSetNode) -> ast.SelectSetNode:
        """Transform a select set node (part of a UNION ALL)."""
        # Use a simplified approach since SelectSetNode doesn't inherit from AST/Expr
        # and doesn't have start/end attributes
        visited_query = self.visit(node.select_query)
        select_query = cast(ast.SelectQuery, visited_query) if visited_query is not None else node.select_query
        return ast.SelectSetNode(
            set_operator=node.set_operator,
            select_query=select_query,
        )


QueryType = Union[ast.SelectQuery, ast.SelectSetQuery]


def transform_query_to_state_aggregations(query: QueryType, transform_nested_aggregations=False) -> QueryType:
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

    # This is redundant now with the transformer handling removal of LIMIT and ORDER BY
    # but keeping it for backward compatibility and extra safety
    if isinstance(transformed_query, ast.SelectSetQuery):
        # Remove from initial query if present
        if hasattr(transformed_query.initial_select_query, "limit"):
            transformed_query.initial_select_query.limit = None
        if hasattr(transformed_query.initial_select_query, "order_by"):
            transformed_query.initial_select_query.order_by = None

        # Remove from subsequent queries if present
        for node in transformed_query.subsequent_select_queries:
            if hasattr(node.select_query, "limit"):
                node.select_query.limit = None
            if hasattr(node.select_query, "order_by"):
                node.select_query.order_by = None

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
            # Instead of using clone_expr which has type variable issues with SelectSetNode,
            # manually create a new SelectSetNode
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
            elif isinstance(item.expr, ast.Constant):
                # For constants statements like "NULL as xpto, pass through the constant directly
                # This ensures they don't need to be in GROUP BY
                outer_select.append(ast.Alias(alias=alias_name, expr=cast(ast.Expr, clone_expr(item.expr))))
            else:
                # For non-state functions, just reference the field directly without group by
                outer_select.append(ast.Alias(alias=alias_name, expr=ast.Field(chain=[alias_name])))
        elif isinstance(item, ast.Constant):
            # For direct constants (like NULL literals), just pass them through directly
            outer_select.append(cast(ast.Expr, clone_expr(item)))
        else:
            # For non-alias items, just reference them directly
            outer_select.append(cast(ast.Expr, clone_expr(item)))

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
                        outer_group_by.append(cast(ast.Expr, clone_expr(group_item)))
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
                        outer_group_by.append(cast(ast.Expr, clone_expr(group_item)))
            else:
                # For expressions, try to find a matching alias in the SELECT, if we can't lets just clone the expression
                found_alias = False
                for select_item in state_query.select:
                    if isinstance(select_item, ast.Alias) and select_item.expr == group_item:
                        outer_group_by.append(ast.Field(chain=[select_item.alias]))
                        found_alias = True
                        break
                if not found_alias:
                    outer_group_by.append(cast(ast.Expr, clone_expr(group_item)))

        if outer_group_by:
            outer_query.group_by = outer_group_by

    # Copy ORDER BY clause from inner to outer query if present
    if state_query.order_by and len(state_query.order_by) > 0:
        outer_order_by: list[ast.OrderExpr] = []

        for order_item in state_query.order_by:
            cloned_order = cast(ast.OrderExpr, clone_expr(order_item))

            # If the order expression is a field, try to find a matching alias in the SELECT
            if isinstance(cloned_order.expr, ast.Field) and len(cloned_order.expr.chain) == 1:
                field_name = cloned_order.expr.chain[0]
                if field_name in all_field_aliases:
                    cloned_order.expr = ast.Field(chain=[field_name])

            outer_order_by.append(cloned_order)

        outer_query.order_by = outer_order_by

    # Copy LIMIT from inner to outer query if present
    if state_query.limit is not None:
        outer_query.limit = cast(Optional[ast.Expr], clone_expr(state_query.limit))

    # Copy OFFSET from inner to outer query if present
    if state_query.offset is not None:
        outer_query.offset = cast(Optional[ast.Expr], clone_expr(state_query.offset))

    return cast(QueryType, outer_query)
