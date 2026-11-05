"""Node descriptions live with the view or table that a node stands for.

Agents read the view and table annotations through `system.information_schema`, so the model page
reads and writes the same rows to show the same text.
"""

from collections.abc import Iterable
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.llm.semantic_enrichment import upsert_user_edited_annotation

from products.data_modeling.backend.models.datawarehouse_saved_query_column_annotation import (
    DataWarehouseSavedQueryColumnAnnotation,
)
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.api import (
    live_table_exists,
    table_level_descriptions,
    write_table_level_description,
)

# An annotation with an empty column name describes the whole view or table.
OBJECT_LEVEL_COLUMN = ""


@frozen
class NodeDescription:
    text: str = ""
    source: str | None = None


def warehouse_table_id(node: Node) -> UUID | None:
    if node.type != NodeType.TABLE or not isinstance(node.properties, dict):
        return None
    table_id = node.properties.get("warehouse_table_id")
    try:
        return UUID(table_id) if table_id else None
    except ValueError:
        return None


def load_node_descriptions(team_id: int, nodes: Iterable[Node]) -> dict[UUID, NodeDescription]:
    nodes = list(nodes)
    view_ids = {node.saved_query_id for node in nodes if node.saved_query_id}
    table_ids = {table_id for node in nodes if (table_id := warehouse_table_id(node))}

    view_descriptions: dict[object, NodeDescription] = {}
    if view_ids:
        view_descriptions = {
            saved_query_id: NodeDescription(text=text, source=source)
            for saved_query_id, text, source in DataWarehouseSavedQueryColumnAnnotation.objects.for_team(team_id)
            .filter(saved_query_id__in=view_ids, column_name=OBJECT_LEVEL_COLUMN)
            .values_list("saved_query_id", "description", "description_source")
        }

    table_descriptions = table_level_descriptions(team_id, table_ids) if table_ids else {}

    descriptions: dict[UUID, NodeDescription] = {}
    for node in nodes:
        if node.saved_query_id:
            description = view_descriptions.get(node.saved_query_id)
        else:
            table_id = warehouse_table_id(node)
            table_description = table_descriptions.get(table_id) if table_id else None
            description = (
                NodeDescription(text=table_description.text, source=table_description.source)
                if table_description
                else None
            )
        if description:
            descriptions[node.id] = description
    return descriptions


def can_describe_node(node: Node) -> bool:
    if node.saved_query_id is not None:
        return True
    table_id = warehouse_table_id(node)
    return table_id is not None and live_table_exists(node.team_id, table_id)


def write_node_description(node: Node, description: str) -> None:
    """Store a user edit. An empty description deletes the row, as the view API does."""
    if node.saved_query is None:
        table_id = warehouse_table_id(node)
        if table_id is None:
            raise ValueError("This node has no view or warehouse table to describe.")
        write_table_level_description(node.team_id, table_id, description)
        return
    if description:
        upsert_user_edited_annotation(
            DataWarehouseSavedQueryColumnAnnotation,
            node.team_id,
            parent_field="saved_query",
            parent=node.saved_query,
            column_name=OBJECT_LEVEL_COLUMN,
            description=description,
        )
        return
    DataWarehouseSavedQueryColumnAnnotation.objects.for_team(node.team_id).filter(
        saved_query=node.saved_query, column_name=OBJECT_LEVEL_COLUMN
    ).delete()
