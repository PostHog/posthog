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

    def build_select_fields(self, convert_entity_id_to_string: bool = False) -> list[ast.Alias]:
        """
        Build normalized SELECT fields for this source type.

        Returns standardized fields that work in UNION queries:
        - entity_id (optionally converted to String for UNION compatibility)
        - timestamp
        - uuid (real or placeholder)
        - session_id (real or placeholder)

        Args:
            convert_entity_id_to_string: If True, wraps entity_key with toString()
                for UNION ALL compatibility between events (UUID) and DW (String)

        Returns:
            List of AST Alias nodes for SELECT clause

        Example:
            >>> info = MetricSourceInfo.from_source(dw_node, team)
            >>> fields = info.build_select_fields(convert_entity_id_to_string=True)
            >>> [f.alias for f in fields]
            ['entity_id', 'timestamp', 'uuid', 'session_id']
        """
        fields = []

        # Entity ID - optionally convert to String for UNION compatibility
        entity_id_expr: ast.Expr
        if convert_entity_id_to_string:
            entity_id_expr = ast.Call(name="toString", args=[self.entity_key])
        else:
            entity_id_expr = self.entity_key

        fields.append(ast.Alias(alias="entity_id", expr=entity_id_expr))

        # Timestamp - use appropriate field based on source type
        timestamp_expr: ast.Field
        if self.kind == "datawarehouse":
            # For DW, use table.field format
            timestamp_expr = ast.Field(chain=[self.table_name, self.timestamp_field])
        else:
            # For events/actions, just use timestamp field
            timestamp_expr = ast.Field(chain=[self.timestamp_field])

        fields.append(ast.Alias(alias="timestamp", expr=timestamp_expr))

        # UUID - real for events/actions, placeholder for DW
        uuid_expr: ast.Expr
        if self.has_uuid:
            uuid_expr = ast.Field(chain=["uuid"])
        else:
            # Use placeholder UUID for DW sources (required by funnel UDF)
            # All-zeros UUID ensures type compatibility without affecting results
            uuid_expr = ast.Call(name="toUUID", args=[ast.Constant(value="00000000-0000-0000-0000-000000000000")])

        fields.append(ast.Alias(alias="uuid", expr=uuid_expr))

        # Session ID - real for events/actions, placeholder for DW
        session_id_expr: ast.Expr
        if self.has_session_id:
            session_id_expr = ast.Field(chain=["properties", "$session_id"])
        else:
            # Empty string placeholder for DW sources
            session_id_expr = ast.Constant(value="")

        fields.append(ast.Alias(alias="session_id", expr=session_id_expr))

        return fields

    def get_timestamp_field_expr(self) -> ast.Field:
        """
        Get the AST expression for the timestamp field.

        Returns fully qualified field reference appropriate for WHERE clauses.

        Returns:
            AST Field node for timestamp access

        Example:
            >>> info = MetricSourceInfo.from_source(dw_node, team)
            >>> field = info.get_timestamp_field_expr()
            >>> field.chain
            ['revenue_table', 'purchase_date']
        """
        if self.kind == "datawarehouse":
            return ast.Field(chain=[self.table_name, self.timestamp_field])
        else:
            return ast.Field(chain=["events", self.timestamp_field])
