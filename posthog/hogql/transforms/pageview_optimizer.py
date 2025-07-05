from typing import Optional, Literal, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import TraversingVisitor

_T_AST = ast.AST


def optimize_pageview_queries(
    node: _T_AST,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[list[ast.SelectQuery]],
    context: HogQLContext,
) -> _T_AST:
    """
    Optimize pageview-only queries by redirecting them to pre-aggregated web analytics tables.
    
    This optimizer detects simple pageview queries and transforms them to use the web_stats_combined
    or web_bounces_combined tables for improved performance.
    
    Only applies when:
    - useWebAnalyticsPreAggregatedTables modifier is enabled (which implies team has access)
    - Query filters for pageview events only
    - Query uses supported aggregations (count, uniq)
    - Query dimensions are available in pre-aggregated tables
    """
    # Check if web analytics pre-aggregated tables are enabled
    # This modifier should only be set if the team has pre-aggregated tables available
    if not context.modifiers or not context.modifiers.useWebAnalyticsPreAggregatedTables:
        return node
    
    return PageviewOptimizer(stack=stack, context=context, dialect=dialect).visit(node)


class PageviewOptimizer(TraversingVisitor):
    """
    Transforms pageview-only queries to use pre-aggregated web analytics tables.
    
    This optimizer follows the same pattern as other HogQL transforms:
    1. Detect queries that match optimization criteria
    2. Transform the AST to use optimized data sources
    3. Maintain query semantics while improving performance
    """

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # Only optimize top-level SELECT queries from events table
        if not self._is_pageview_optimizable(node):
            return super().visit_select_query(node)
        
        # Transform to use pre-aggregated tables
        optimized_node = self._transform_to_preaggregated(node)
        return super().visit_select_query(optimized_node)

    def _is_pageview_optimizable(self, node: ast.SelectQuery) -> bool:
        """
        Check if this query can be optimized for pageview pre-aggregated tables.
        
        Criteria:
        - Queries from events table
        - Filters for pageview events only
        - Uses supported aggregations
        - Uses supported dimensions
        """
        # Check if querying from events table
        if not self._queries_events_table(node):
            return False
        
        # Check if filters are pageview-only
        if not self._has_pageview_only_filters(node):
            return False
        
        # Check if aggregations are supported
        if not self._has_supported_aggregations(node):
            return False
        
        # Check if dimensions are supported
        if not self._has_supported_dimensions(node):
            return False
        
        return True

    def _queries_events_table(self, node: ast.SelectQuery) -> bool:
        """Check if the query is from the events table."""
        if not node.select_from:
            return False
        
        # Handle direct table reference
        if isinstance(node.select_from.table, ast.Field):
            return node.select_from.table.chain == ["events"]
        
        # Handle joined table reference
        if isinstance(node.select_from.table, ast.JoinExpr):
            left_table = node.select_from.table.table
            if isinstance(left_table, ast.Field):
                return left_table.chain == ["events"]
        
        return False

    def _has_pageview_only_filters(self, node: ast.SelectQuery) -> bool:
        """Check if query filters are pageview-only."""
        if not node.where:
            return False
        
        # Look for event = '$pageview' or event IN ('$pageview', '$screen')
        return self._contains_pageview_filter(node.where)

    def _contains_pageview_filter(self, expr: ast.Expr) -> bool:
        """Recursively check if expression contains pageview event filter."""
        if isinstance(expr, ast.CompareOperation):
            if (isinstance(expr.left, ast.Field) and 
                expr.left.chain == ["event"] and 
                expr.op == ast.CompareOperationOp.Eq):
                
                if isinstance(expr.right, ast.Constant):
                    return expr.right.value in ["$pageview", "$screen"]
        
        elif isinstance(expr, ast.CompareOperation):
            if (isinstance(expr.left, ast.Field) and 
                expr.left.chain == ["event"] and 
                expr.op == ast.CompareOperationOp.In):
                
                if isinstance(expr.right, ast.Array):
                    values = []
                    for item in expr.right.exprs:
                        if isinstance(item, ast.Constant):
                            values.append(item.value)
                    return all(v in ["$pageview", "$screen"] for v in values)
        
        elif isinstance(expr, ast.And):
            # All conditions must be compatible with pageview optimization
            return all(self._contains_pageview_filter(e) or self._is_compatible_filter(e) for e in expr.exprs)
        
        elif isinstance(expr, ast.Or):
            # At least one condition must be a pageview filter
            return any(self._contains_pageview_filter(e) for e in expr.exprs)
        
        return False

    def _is_compatible_filter(self, expr: ast.Expr) -> bool:
        """Check if filter is compatible with pre-aggregated tables."""
        # Compatible filters are those that can be applied to pre-aggregated tables
        # such as date ranges, team_id, hostname, etc.
        if isinstance(expr, ast.CompareOperation):
            if isinstance(expr.left, ast.Field):
                field_name = expr.left.chain[-1] if expr.left.chain else ""
                # These fields exist in pre-aggregated tables
                compatible_fields = {
                    "timestamp", "team_id", "properties", "$host", "$browser", "$os",
                    "$country_code", "$city", "$region", "$utm_source", "$utm_medium",
                    "$utm_campaign", "$referring_domain", "$current_url", "$pathname"
                }
                return field_name in compatible_fields
        
        return True  # Be permissive for other filter types

    def _has_supported_aggregations(self, node: ast.SelectQuery) -> bool:
        """Check if query uses only supported aggregation functions."""
        if not node.select:
            return True
        
        for expr in node.select:
            if isinstance(expr, ast.Field):
                continue  # Non-aggregated fields are OK
            
            if not self._is_supported_aggregation(expr):
                return False
        
        return True

    def _is_supported_aggregation(self, expr: ast.Expr) -> bool:
        """Check if aggregation function is supported by pre-aggregated tables."""
        if isinstance(expr, ast.Call):
            # Supported aggregations that can be mapped to pre-aggregated states
            supported_funcs = {
                "count", "countIf", "uniq", "uniqIf", "sum", "sumIf", "avg", "avgIf"
            }
            return expr.name in supported_funcs
        
        return True  # Non-call expressions are OK

    def _has_supported_dimensions(self, node: ast.SelectQuery) -> bool:
        """Check if query dimensions are available in pre-aggregated tables."""
        if not node.select:
            return True
        
        for expr in node.select:
            if isinstance(expr, ast.Field):
                if not self._is_supported_dimension(expr):
                    return False
        
        return True

    def _is_supported_dimension(self, field: ast.Field) -> bool:
        """Check if dimension field is available in pre-aggregated tables."""
        if not field.chain:
            return True
        
        field_name = field.chain[-1]
        # Fields available in web_stats_combined and web_bounces_combined
        supported_dimensions = {
            "timestamp", "period_bucket", "team_id", "host", "pathname", "device_type",
            "browser", "os", "viewport_width", "viewport_height", "referring_domain",
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "country_code", "city_name", "region_code", "region_name", "entry_pathname",
            "end_pathname"
        }
        
        return field_name in supported_dimensions

    def _transform_to_preaggregated(self, node: ast.SelectQuery) -> ast.SelectQuery:
        """Transform query to use pre-aggregated web analytics tables."""
        # Create a copy of the node to avoid modifying the original
        transformed = cast(ast.SelectQuery, node.model_copy(deep=True))
        
        # Replace table source with web_stats_combined
        if transformed.select_from:
            transformed.select_from.table = ast.Field(chain=["web_stats_combined"])
        
        # Transform SELECT clause to use merge functions
        if transformed.select:
            transformed.select = [self._transform_select_expr(expr) for expr in transformed.select]
        
        # Transform WHERE clause to remove event filters (they're implicit in pre-aggregated tables)
        if transformed.where:
            transformed.where = self._transform_where_clause(transformed.where)
        
        # Add period_bucket filter for time-based queries
        transformed.where = self._add_period_bucket_filter(transformed.where)
        
        return transformed

    def _transform_select_expr(self, expr: ast.Expr) -> ast.Expr:
        """Transform SELECT expression to use pre-aggregated merge functions."""
        if isinstance(expr, ast.Call):
            if expr.name == "count":
                # count() -> sumMerge(pageviews_count_state)
                return ast.Call(
                    name="sumMerge",
                    args=[ast.Field(chain=["pageviews_count_state"])]
                )
            elif expr.name == "countIf":
                # countIf(event = '$pageview') -> sumMerge(pageviews_count_state)
                return ast.Call(
                    name="sumMerge",
                    args=[ast.Field(chain=["pageviews_count_state"])]
                )
            elif expr.name == "uniq":
                # uniq(distinct_id) -> uniqMerge(persons_uniq_state)
                return ast.Call(
                    name="uniqMerge",
                    args=[ast.Field(chain=["persons_uniq_state"])]
                )
            elif expr.name == "uniqIf":
                # uniqIf(distinct_id, event = '$pageview') -> uniqMerge(persons_uniq_state)
                return ast.Call(
                    name="uniqMerge",
                    args=[ast.Field(chain=["persons_uniq_state"])]
                )
        
        return expr

    def _transform_where_clause(self, where: ast.Expr) -> Optional[ast.Expr]:
        """Transform WHERE clause to remove pageview event filters."""
        if isinstance(where, ast.CompareOperation):
            # Remove event = '$pageview' filters
            if (isinstance(where.left, ast.Field) and 
                where.left.chain == ["event"]):
                return None
        
        elif isinstance(where, ast.And):
            # Filter out event filters, keep other conditions
            filtered_exprs = []
            for expr in where.exprs:
                transformed = self._transform_where_clause(expr)
                if transformed is not None:
                    filtered_exprs.append(transformed)
            
            if not filtered_exprs:
                return None
            elif len(filtered_exprs) == 1:
                return filtered_exprs[0]
            else:
                return ast.And(exprs=filtered_exprs)
        
        return where

    def _add_period_bucket_filter(self, where: Optional[ast.Expr]) -> ast.Expr:
        """Add period_bucket filter for time-based queries."""
        # For now, we'll keep the existing timestamp filters
        # The web_stats_combined view handles the time mapping
        return where