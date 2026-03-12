"""
Funnel step column builder for experiment queries.

This module provides utilities for building step column expressions used in
funnel metric queries, supporting both boolean columns (for events-only queries)
and constant columns (for UNION ALL queries with datawarehouse sources).
"""

from typing import Union

from posthog.schema import ActionsNode, EventsNode, ExperimentDataWarehouseNode

from posthog.hogql import ast

from posthog.hogql_queries.experiments.base_query_utils import event_or_action_to_filter
from posthog.models.team.team import Team


class FunnelStepBuilder:
    """
    Builds step column expressions for funnel queries.

    This class separates step column generation logic from query building,
    supporting two distinct patterns:

    1. **Boolean columns**: For events-only funnels where all steps are evaluated
       in a single query against the events table. Each step is a boolean expression.

    2. **Constant columns**: For UNION ALL queries with heterogeneous sources
       (events + datawarehouse). Each subquery represents one step, with the
       active step set to 1 and all others set to 0.

    Attributes:
        series: List of funnel step sources (EventsNode, ActionsNode, or ExperimentDataWarehouseNode)
        team: Team context for filtering and entity resolution
        num_steps: Total number of steps in the funnel (including exposure step_0)
    """

    def __init__(
        self,
        series: list[Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]],
        team: Team,
    ):
        """
        Initialize FunnelStepBuilder.

        Args:
            series: List of funnel step sources
            team: Team context
        """
        self.series = series
        self.team = team
        # num_steps includes step_0 (exposure) + all metric steps
        self.num_steps = len(series) + 1

    def build_boolean_columns(self, exposure_filter: ast.Expr) -> list[ast.Alias]:
        """
        Build step columns as boolean expressions for events table queries.

        Used when all funnel steps come from the events table (no UNION needed).
        Each row in the events table is evaluated against all step conditions,
        producing boolean columns [step_0, step_1, ..., step_N].

        Args:
            exposure_filter: AST expression for exposure condition (becomes step_0)

        Returns:
            List of AST Alias nodes for step columns, each evaluating to 0 or 1

        Example:
            >>> builder = FunnelStepBuilder([
            ...     EventsNode(event="pageview"),
            ...     EventsNode(event="purchase")
            ... ], team)
            >>> exposure_filter = parse_expr("event = '$feature_flag_called'")
            >>> columns = builder.build_boolean_columns(exposure_filter)
            >>> [col.alias for col in columns]
            ['step_0', 'step_1', 'step_2']
        """
        columns = []

        # Step 0: Exposure
        columns.append(
            ast.Alias(
                alias="step_0",
                expr=exposure_filter,
            )
        )

        # Steps 1..N: Metric steps
        for step_index, step_source in enumerate(self.series, start=1):
            step_filter = self._build_step_filter(step_source)
            columns.append(
                ast.Alias(
                    alias=f"step_{step_index}",
                    expr=ast.Call(name="if", args=[step_filter, ast.Constant(value=1), ast.Constant(value=0)]),
                )
            )

        return columns

    def build_constant_columns(self, active_step_index: int) -> list[ast.Alias]:
        """
        Build step columns as constants for DW subquery.

        Used in UNION ALL queries where each subquery represents one step.
        The active step has value 1, all other steps have value 0.

        This pattern is necessary when combining events and datawarehouse sources
        because each source requires a separate subquery with different table
        references and field structures.

        Args:
            active_step_index: The step number that should be set to 1 (0-based)

        Returns:
            List of AST Alias nodes for step columns as constants

        Example:
            >>> builder = FunnelStepBuilder([...], team)
            >>> # For DW step 2 subquery:
            >>> columns = builder.build_constant_columns(active_step_index=2)
            >>> # Results in: step_0=0, step_1=0, step_2=1
        """
        columns = []

        for step_index in range(self.num_steps):
            value = 1 if step_index == active_step_index else 0
            columns.append(
                ast.Alias(
                    alias=f"step_{step_index}",
                    expr=ast.Constant(value=value),
                )
            )

        return columns

    def _build_step_filter(self, step_source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]) -> ast.Expr:
        """
        Build boolean filter expression for a funnel step.

        For events-only queries, this generates the condition that determines
        if a given event row matches the step criteria.

        Args:
            step_source: The step source definition

        Returns:
            AST expression evaluating to boolean (will be 0 or 1 in ClickHouse)

        Note:
            Uses event_or_action_to_filter() for proper event/action handling.
            For ExperimentDataWarehouseNode: Not used in boolean column context
        """
        if isinstance(step_source, ExperimentDataWarehouseNode):
            # ExperimentDataWarehouseNode - should not be used in boolean columns
            # This is a programming error if reached
            raise ValueError(
                f"Cannot build boolean filter for {type(step_source).__name__}. "
                "Use constant columns for UNION ALL queries with datawarehouse sources."
            )

        # Use the standard event/action filter utility
        return event_or_action_to_filter(self.team, step_source)
