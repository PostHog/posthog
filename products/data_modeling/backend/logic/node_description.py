"""Node descriptions live with the view or table that a node stands for.

Agents read the view and table annotations through `system.information_schema`, so the model page
reads and writes the same rows to show the same text.
"""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.llm.semantic_enrichment import upsert_user_edited_annotation

from products.data_modeling.backend.models.datawarehouse_saved_query_column_annotation import (
    DataWarehouseSavedQueryColumnAnnotation,
)
from products.data_modeling.backend.models.node import Node, NodeType
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataSchema,
    WarehouseColumnAnnotation,
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

    table_descriptions = _load_table_descriptions(team_id, table_ids) if table_ids else {}

    descriptions: dict[UUID, NodeDescription] = {}
    for node in nodes:
        if node.saved_query_id:
            description = view_descriptions.get(node.saved_query_id)
        else:
            table_id = warehouse_table_id(node)
            description = table_descriptions.get(table_id) if table_id else None
        if description:
            descriptions[node.id] = description
    return descriptions


def _load_table_descriptions(team_id: int, table_ids: set[UUID]) -> dict[UUID, NodeDescription]:
    # `TableDescriptions` uses the same order, so agents and the model page show the same table text.
    descriptions: dict[UUID, NodeDescription] = {
        table_id: NodeDescription(text=text)
        for table_id, text in ExternalDataSchema.objects.filter(team_id=team_id, table_id__in=table_ids, deleted=False)
        .exclude(description__isnull=True)
        .exclude(description="")
        .order_by("updated_at")
        .values_list("table_id", "description")
    }
    for table_id, text, source in (
        WarehouseColumnAnnotation.objects.for_team(team_id)
        .filter(table_id__in=table_ids, column_name=OBJECT_LEVEL_COLUMN)
        .values_list("table_id", "description", "description_source")
    ):
        descriptions[table_id] = NodeDescription(text=text, source=source)
    return descriptions


def get_describable_table(node: Node) -> DataWarehouseTable | None:
    table_id = warehouse_table_id(node)
    if table_id is None:
        return None
    return DataWarehouseTable.objects.filter(team_id=node.team_id, id=table_id).exclude(deleted=True).first()


def can_describe_node(node: Node) -> bool:
    return node.saved_query_id is not None or get_describable_table(node) is not None


def write_node_description(node: Node, description: str) -> None:
    """Store a user edit. An empty description deletes the row, as the view API does."""
    if node.saved_query is not None:
        _write_annotation(DataWarehouseSavedQueryColumnAnnotation, node, "saved_query", node.saved_query, description)
        return
    table = get_describable_table(node)
    if table is None:
        raise ValueError("This node has no view or warehouse table to describe.")
    _write_annotation(WarehouseColumnAnnotation, node, "table", table, description)


def _write_annotation(model: Any, node: Node, parent_field: str, parent: object, description: str) -> None:
    if description:
        upsert_user_edited_annotation(
            model,
            node.team_id,
            parent_field=parent_field,
            parent=parent,
            column_name=OBJECT_LEVEL_COLUMN,
            description=description,
        )
        return
    # nosemgrep: orm-field-injection -- parent_field is a hardcoded caller constant ("table"/"saved_query"), not user input
    model.objects.for_team(node.team_id).filter(**{parent_field: parent, "column_name": OBJECT_LEVEL_COLUMN}).delete()
