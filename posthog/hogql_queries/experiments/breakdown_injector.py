"""
Breakdown column injection for experiment queries.

Handles injecting breakdown columns into various metric type queries (funnel, mean, ratio, retention).
Breakdown columns are used to segment experiment results by property values.
"""

from typing import Union

from posthog.schema import (
    Breakdown,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

# Constant for representing NULL breakdown values
BREAKDOWN_NULL_STRING_LABEL = "$$_posthog_breakdown_null_$$"


class BreakdownInjector:
    """
    Handles injection of breakdown columns into experiment query AST.

    Breakdown columns are added to intermediate CTEs and final SELECT/GROUP BY clauses
    to enable segmentation of experiment results by property values.
    """

    def __init__(
        self,
        breakdowns: list[Breakdown],
        metric: Union[ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentRatioMetric, ExperimentRetentionMetric],
    ):
        self.breakdowns = breakdowns
        self.metric = metric

    def _has_breakdown(self) -> bool:
        """Returns True if any breakdowns are configured"""
        return len(self.breakdowns) > 0

    def _get_breakdown_count(self) -> int:
        """Returns the number of breakdowns configured"""
        return len(self.breakdowns)

    def _get_breakdown_aliases(self) -> list[str]:
        """Returns list of breakdown aliases: ['breakdown_value_1', 'breakdown_value_2', ...]"""
        return [f"breakdown_value_{i + 1}" for i in range(len(self.breakdowns))]

    def build_breakdown_exprs(self, table_alias: str = "events") -> list[tuple[str, ast.Expr]]:
        """
        Returns list of (alias, expression) tuples for extracting breakdown properties from events.
        Handles NULL values by replacing with BREAKDOWN_NULL_STRING_LABEL.
        Returns empty list if no breakdowns configured.

        This is a public method used by exposure query building in ExperimentQueryBuilder.
        """
        if not self._has_breakdown():
            return []

        result = []
        for i, breakdown in enumerate(self.breakdowns):
            # Build the property chain - if table_alias is empty, just use properties.breakdown
            if table_alias:
                property_expr = ast.Field(chain=[table_alias, "properties", breakdown.property])
            else:
                property_expr = ast.Field(chain=["properties", breakdown.property])

            expr = parse_expr(
                "coalesce(toString({property_expr}), {null_label})",
                placeholders={
                    "property_expr": property_expr,
                    "null_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                },
            )
            alias = f"breakdown_value_{i + 1}"
            result.append((alias, expr))

        return result

    def inject_funnel_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """
        Injects breakdown columns into funnel query AST.
        Modifies query in-place.
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()
        breakdown_exprs = self.build_breakdown_exprs(table_alias="")

        # Inject into metric_events CTE SELECT
        if query.ctes and "metric_events" in query.ctes:
            metric_events_cte = query.ctes["metric_events"]
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    metric_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        # Inject into entity_metrics CTE SELECT (attribution - extract from exposure events only)
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                # Check if this is an unordered funnel (has exposures CTE with LEFT JOIN)
                # In that case, breakdown comes from exposures, not metric_events
                has_exposures = "exposures" in query.ctes if query.ctes else False

                for alias in aliases:
                    if has_exposures:
                        # Unordered funnel: get breakdown from exposures (already attributed)
                        entity_metrics_cte.expr.select.append(
                            ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias]))
                        )
                    else:
                        # Ordered funnel: use argMinIf to attribute from first exposure in metric_events
                        # Qualify the field reference to avoid ambiguity
                        entity_metrics_cte.expr.select.append(
                            ast.Alias(
                                alias=alias,
                                expr=ast.Call(
                                    name="argMinIf",
                                    args=[
                                        ast.Field(chain=["metric_events", alias]),
                                        ast.Field(chain=["timestamp"]),
                                        ast.CompareOperation(
                                            op=ast.CompareOperationOp.Eq,
                                            left=ast.Field(chain=["step_0"]),
                                            right=ast.Constant(value=1),
                                        ),
                                    ],
                                ),
                            )
                        )

                # For unordered funnels, also add breakdown to entity_metrics GROUP BY
                if has_exposures:
                    if entity_metrics_cte.expr.group_by is None:
                        entity_metrics_cte.expr.group_by = []
                    for alias in aliases:
                        entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        # Inject into final SELECT - breakdown columns must come right after variant
        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])),
            )

        # Inject into final GROUP BY
        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))

    def inject_mean_breakdown_columns(self, query: ast.SelectQuery, final_cte_name: str = "entity_metrics") -> None:
        """
        Injects breakdown columns into mean query AST.
        Modifies query in-place.

        Args:
            query: The parsed SelectQuery AST
            final_cte_name: Name of the final CTE before main SELECT ('entity_metrics' or 'winsorized_entity_metrics')
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()

        # Get table name for metric_events based on metric source
        assert isinstance(self.metric, ExperimentMeanMetric)
        is_dw = isinstance(self.metric.source, ExperimentDataWarehouseNode)

        breakdown_exprs = self.build_breakdown_exprs(table_alias="metric_events" if is_dw else "events")

        # Inject into metric_events CTE SELECT
        if query.ctes and "metric_events" in query.ctes:
            metric_events_cte = query.ctes["metric_events"]
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    metric_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        # Inject into entity_metrics CTE SELECT and GROUP BY
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias]))
                    )
                # Also add to GROUP BY
                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        # Inject into percentiles CTE (only for winsorization queries)
        if query.ctes and "percentiles" in query.ctes:
            percentiles_cte = query.ctes["percentiles"]
            if isinstance(percentiles_cte, ast.CTE) and isinstance(percentiles_cte.expr, ast.SelectQuery):
                # Add breakdown columns to SELECT
                for alias in aliases:
                    percentiles_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias]))
                    )
                # Initialize and populate GROUP BY for per-breakdown percentiles
                if percentiles_cte.expr.group_by is None:
                    percentiles_cte.expr.group_by = []
                for alias in aliases:
                    percentiles_cte.expr.group_by.append(ast.Field(chain=["entity_metrics", alias]))

        # Inject into winsorized_entity_metrics CTE (only when final_cte_name is winsorized_entity_metrics)
        if query.ctes and final_cte_name == "winsorized_entity_metrics":
            winsorized_cte = query.ctes["winsorized_entity_metrics"]
            if isinstance(winsorized_cte, ast.CTE) and isinstance(winsorized_cte.expr, ast.SelectQuery):
                # Add breakdown columns to SELECT
                for alias in aliases:
                    winsorized_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias]))
                    )
                # Convert CROSS JOIN to proper JOIN with breakdown conditions
                if winsorized_cte.expr.select_from:
                    join_expr = winsorized_cte.expr.select_from.next_join
                    if join_expr and isinstance(join_expr, ast.JoinExpr):
                        # Change from CROSS JOIN to INNER JOIN
                        join_expr.join_type = "JOIN"
                        # Build join condition: percentiles.bd1 = entity_metrics.bd1 AND ...
                        join_conditions = []
                        for alias in aliases:
                            join_conditions.append(
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["percentiles", alias]),
                                    right=ast.Field(chain=["entity_metrics", alias]),
                                )
                            )
                        # Combine conditions with AND
                        condition_expr: ast.Expr
                        if len(join_conditions) == 1:
                            condition_expr = join_conditions[0]
                        else:
                            combined: ast.Expr = join_conditions[0]
                            for condition in join_conditions[1:]:
                                combined = ast.And(exprs=[combined, condition])
                            condition_expr = combined
                        # Wrap in JoinConstraint with ON clause
                        join_expr.constraint = ast.JoinConstraint(expr=condition_expr, constraint_type="ON")

        # Inject into final SELECT - breakdown columns must come right after variant
        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=[final_cte_name, alias])),
            )

        # Inject into final GROUP BY
        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=[final_cte_name, alias]))

    def inject_ratio_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """
        Injects breakdown columns into ratio query AST.
        Modifies query in-place.

        With the combined_events structure, breakdowns are simpler:
        - Breakdowns are attributed from exposures (not from numerator/denominator events)
        - entity_metrics gets breakdown columns directly from exposures
        - No need for breakdown join conditions since there's only one join to combined_events
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()

        # Inject into entity_metrics CTE SELECT and GROUP BY (from exposures)
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias]))
                    )
                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        # Inject into final SELECT - breakdown columns must come right after variant
        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])),
            )

        # Inject into final GROUP BY
        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))

    def inject_retention_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """
        Injects breakdown columns into retention query AST.
        Modifies query in-place.

        Retention breakdown injection is simpler than ratio because:
        - Only entity_metrics CTE needs modification
        - No JOIN conditions require breakdown columns
        - Breakdowns come from exposures only
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()

        # Inject into entity_metrics CTE SELECT and GROUP BY (carry breakdown from exposures)
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                # Add breakdown columns to SELECT (after entity_id and variant)
                for i, alias in enumerate(aliases):
                    entity_metrics_cte.expr.select.insert(
                        2 + i,  # After entity_id (0), variant (1)
                        ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias])),
                    )

                # Add breakdown columns to GROUP BY
                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        # Inject into final SELECT - breakdown columns must come right after variant
        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])),
            )

        # Inject into final GROUP BY
        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))
