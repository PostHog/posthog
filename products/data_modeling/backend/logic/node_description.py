"""Node descriptions live with the view or table that a node stands for.

Agents read the view and table annotations through `system.information_schema`, so the model page
reads and writes the same rows to show the same text.
"""

from collections.abc import Iterable
from uuid import UUID

from products.data_modeling.backend.facade.contracts import NodeDescription, NodeDescriptionTarget
from products.data_modeling.backend.models.datawarehouse_saved_query_column_annotation import (
    DataWarehouseSavedQueryColumnAnnotation,
)
from products.warehouse_sources.backend.facade.api import (
    live_table_exists,
    table_level_descriptions,
    write_table_level_description,
)
from products.warehouse_sources.backend.facade.types import WarehouseColumnAnnotationDescriptionSource

# An annotation with an empty column name describes the whole view or table.
OBJECT_LEVEL_COLUMN = ""


def load_node_descriptions(team_id: int, targets: Iterable[NodeDescriptionTarget]) -> dict[UUID, NodeDescription]:
    targets = list(targets)
    view_ids = {target.saved_query_id for target in targets if target.saved_query_id}
    table_ids = {target.warehouse_table_id for target in targets if target.warehouse_table_id}

    view_descriptions: dict[UUID, NodeDescription] = {}
    if view_ids:
        view_descriptions = {
            saved_query_id: NodeDescription(text=text, source=WarehouseColumnAnnotationDescriptionSource(source))
            for saved_query_id, text, source in DataWarehouseSavedQueryColumnAnnotation.objects.for_team(team_id)
            .filter(saved_query_id__in=view_ids, column_name=OBJECT_LEVEL_COLUMN)
            .values_list("saved_query_id", "description", "description_source")
        }
    table_descriptions = table_level_descriptions(team_id, table_ids) if table_ids else {}

    descriptions: dict[UUID, NodeDescription] = {}
    for target in targets:
        if target.saved_query_id:
            description = view_descriptions.get(target.saved_query_id)
            if description:
                descriptions[target.node_id] = description
        elif target.warehouse_table_id and (table_description := table_descriptions.get(target.warehouse_table_id)):
            descriptions[target.node_id] = NodeDescription(text=table_description.text, source=table_description.source)
    return descriptions


def can_describe_node(team_id: int, target: NodeDescriptionTarget) -> bool:
    if target.saved_query_id:
        return True
    return target.warehouse_table_id is not None and live_table_exists(team_id, target.warehouse_table_id)


def write_node_description(team_id: int, target: NodeDescriptionTarget, description: str) -> None:
    """Store a user edit. An empty description deletes the row, as the view API does."""
    if target.saved_query_id is None:
        if target.warehouse_table_id is None:
            raise ValueError("This node has no view or warehouse table to describe.")
        write_table_level_description(team_id, target.warehouse_table_id, description)
        return
    annotations = DataWarehouseSavedQueryColumnAnnotation.objects.for_team(team_id)
    if not description:
        annotations.filter(saved_query_id=target.saved_query_id, column_name=OBJECT_LEVEL_COLUMN).delete()
        return
    user_edited = DataWarehouseSavedQueryColumnAnnotation.DescriptionSource.USER_EDITED
    annotation, created = annotations.get_or_create(
        saved_query_id=target.saved_query_id,
        column_name=OBJECT_LEVEL_COLUMN,
        defaults={
            "team_id": team_id,
            "description": description,
            "description_source": user_edited,
            "is_user_edited": True,
        },
    )
    if not created:
        annotation.description = description
        annotation.description_source = user_edited
        annotation.is_user_edited = True
        annotation.save(update_fields=["description", "description_source", "is_user_edited", "updated_at"])
