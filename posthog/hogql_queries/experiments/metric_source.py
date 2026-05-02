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

    def build_select_fields(self) -> list[ast.Alias]:
        """
        Build normalized SELECT fields for UNION compatibility.

        All sources must return the same columns for UNION ALL:
        - entity_id (String type for all sources)
        - variant (empty string '' for DW sources)
        - timestamp
        - uuid (placeholder UUID for DW sources)
        - session_id (empty string '' for DW sources)

        Returns:
            List of aliased column expressions compatible across all source types

        Example:
            >>> info = MetricSourceInfo.from_source(EventsNode(event="purchase"), entity_key="person_id")
            >>> fields = info.build_select_fields()
            >>> [f.alias for f in fields]
            ['entity_id', 'variant', 'timestamp', 'uuid', 'session_id']
        """
        # All sources need these base fields
        fields = [
            # entity_id: String type for consistency
            ast.Alias(
                alias="entity_id",
                expr=ast.Call(
                    name="toString",
                    args=[self.entity_key],
                ),
            ),
            # variant: empty for DW (variant comes from exposure join)
            ast.Alias(
                alias="variant",
                expr=ast.Constant(value=""),
            ),
            # timestamp
            # For DW sources, use unqualified field name to avoid issues with dotted table names
            # (e.g., "schema.table" would become "schema.table.timestamp" if qualified).
            # For events table, qualification is safe and conventional.
            ast.Alias(
                alias="timestamp",
                expr=ast.Field(
                    chain=[self.timestamp_field]
                    if self.kind == "datawarehouse"
                    else [self.table_name, self.timestamp_field]
                ),
            ),
        ]

        # uuid: placeholder for DW sources (no UUID field)
        uuid_expr: ast.Expr
        if self.has_uuid:
            uuid_expr = ast.Field(chain=["uuid"])
        else:
            # Placeholder UUID for DW: 00000000-0000-0000-0000-000000000000
            uuid_expr = ast.Call(
                name="toUUID",
                args=[ast.Constant(value="00000000-0000-0000-0000-000000000000")],
            )

        fields.append(ast.Alias(alias="uuid", expr=uuid_expr))

        # session_id: placeholder for DW sources (no session_id field)
        session_id_expr: ast.Expr
        if self.has_session_id:
            session_id_expr = ast.Field(chain=["properties", "$session_id"])
        else:
            # Empty string for DW sources
            session_id_expr = ast.Constant(value="")

        fields.append(ast.Alias(alias="session_id", expr=session_id_expr))

        return fields
