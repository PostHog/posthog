"""
Metric source abstraction for experiment queries.

This module provides a unified interface for handling different metric source types
(EventsNode, ActionsNode, ExperimentDataWarehouseNode) in experiment queries.
"""

from dataclasses import dataclass
from typing import Union

from posthog.schema import ActionsNode, EventsNode, ExperimentDataWarehouseNode

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr


@dataclass
class MetricSourceInfo:
    """
    Encapsulates metadata about a metric source for query building.

    This abstraction allows experiment queries to handle heterogeneous sources
    (events, actions, datawarehouse) uniformly, particularly important for
    funnel queries that may combine multiple source types.

    Attributes:
        kind: Source type - "events", "actions", or "datawarehouse"
        table_name: Physical table name ("events" or DW table name)
        entity_key: AST expression for extracting entity_id
        timestamp_field: Field name containing timestamp
        has_uuid: Whether source has UUID field (events/actions do, DW doesn't)
        has_session_id: Whether source has session_id field (events/actions do, DW doesn't)
    """

    kind: str
    table_name: str
    entity_key: ast.Expr
    timestamp_field: str
    has_uuid: bool
    has_session_id: bool

    @classmethod
    def from_source(
        cls,
        source: Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode],
        entity_key: str | None = None,
    ) -> "MetricSourceInfo":
        """
        Factory method to create MetricSourceInfo from any source type.

        This provides a uniform interface for working with different source types,
        abstracting away the differences in their structure.

        Args:
            source: The metric source (EventsNode, ActionsNode, or ExperimentDataWarehouseNode)
            entity_key: Entity key from experiment context (e.g., "person_id" or "$group_0").
                       Required for events/actions sources to support group aggregation.
                       Ignored for datawarehouse sources (uses data_warehouse_join_key instead).

        Returns:
            MetricSourceInfo with appropriate metadata for the source type

        Raises:
            ValueError: If entity_key is not provided for events/actions sources

        Example:
            >>> source = EventsNode(event="purchase")
            >>> info = MetricSourceInfo.from_source(source, entity_key="person_id")
            >>> info.kind
            'events'
            >>> info.has_uuid
            True
        """
        if isinstance(source, ExperimentDataWarehouseNode):
            # Datawarehouse sources always use their own join key, ignore entity_key parameter
            return cls(
                kind="datawarehouse",
                table_name=source.table_name,
                entity_key=parse_expr(source.data_warehouse_join_key),
                timestamp_field=source.timestamp_field,
                has_uuid=False,
                has_session_id=False,
            )
        elif isinstance(source, ActionsNode):
            # Events/actions sources require entity_key for group aggregation support
            if entity_key is None:
                raise ValueError("entity_key is required for ActionsNode sources to support group aggregation")
            return cls(
                kind="actions",
                table_name="events",
                entity_key=parse_expr(entity_key),
                timestamp_field="timestamp",
                has_uuid=True,
                has_session_id=True,
            )
        else:  # EventsNode
            # Events/actions sources require entity_key for group aggregation support
            if entity_key is None:
                raise ValueError("entity_key is required for EventsNode sources to support group aggregation")
            return cls(
                kind="events",
                table_name="events",
                entity_key=parse_expr(entity_key),
                timestamp_field="timestamp",
                has_uuid=True,
                has_session_id=True,
            )
