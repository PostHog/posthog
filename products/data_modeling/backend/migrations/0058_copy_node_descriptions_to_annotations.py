from collections.abc import Iterable
from typing import Any
from uuid import UUID

from django.db import migrations
from django.utils import timezone

OBJECT_LEVEL_COLUMN = ""
USER_EDITED = "user_edited"


def _copy(annotation_model: Any, alias: str, parent_field: str, descriptions: Iterable[tuple[int, Any, str]]) -> None:
    manager = annotation_model._base_manager.using(alias)
    for team_id, parent_id, description in descriptions:
        # nosemgrep: orm-field-injection -- parent_field is a hardcoded constant in this module, not user input
        lookup = {f"{parent_field}_id": parent_id, "column_name": OBJECT_LEVEL_COLUMN}
        annotation = manager.filter(**lookup).first()
        if annotation is None:
            manager.create(
                team_id=team_id,
                description=description,
                description_source=USER_EDITED,
                is_user_edited=True,
                **lookup,
            )
        elif not annotation.is_user_edited:
            # A person typed the node text, so it replaces AI or built-in text. A user-edited annotation stays,
            # because agents already read it.
            manager.filter(pk=annotation.pk, is_user_edited=False).update(
                description=description,
                description_source=USER_EDITED,
                ai_model=None,
                is_user_edited=True,
                updated_at=timezone.now(),
            )


def copy_node_descriptions(apps: Any, schema_editor: Any) -> None:
    alias = schema_editor.connection.alias
    Node = apps.get_model("data_modeling", "Node")

    view_descriptions: dict[Any, tuple[int, Any, str]] = {}
    table_descriptions: dict[UUID, tuple[int, UUID, str]] = {}
    # Several DAGs can hold a node for one view, and the most recent edit wins.
    for team_id, saved_query_id, deleted, properties, description in (
        Node._base_manager.using(alias)
        .exclude(description="")
        .order_by("updated_at")
        .values_list("team_id", "saved_query_id", "saved_query__deleted", "properties", "description")
        .iterator()
    ):
        if saved_query_id is not None:
            if not deleted:
                view_descriptions[saved_query_id] = (team_id, saved_query_id, description)
            continue
        table_id = properties.get("warehouse_table_id") if isinstance(properties, dict) else None
        try:
            parsed_table_id = UUID(table_id) if table_id else None
        except ValueError:
            parsed_table_id = None
        if parsed_table_id is not None:
            table_descriptions[parsed_table_id] = (team_id, parsed_table_id, description)

    Table = apps.get_model("warehouse_sources", "DataWarehouseTable")
    live_table_ids = set(
        Table._base_manager.using(alias)
        .filter(id__in=table_descriptions)
        .exclude(deleted=True)
        .values_list("id", flat=True)
    )
    _copy(
        apps.get_model("data_modeling", "DataWarehouseSavedQueryColumnAnnotation"),
        alias,
        "saved_query",
        view_descriptions.values(),
    )
    _copy(
        apps.get_model("warehouse_sources", "WarehouseColumnAnnotation"),
        alias,
        "table",
        (row for table_id, row in table_descriptions.items() if table_id in live_table_ids),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0057_datamodelingjob_drop_bytes_read_column"),
        ("warehouse_sources", "0196_externaldataschema_masked_columns"),
    ]

    operations = [
        migrations.RunPython(copy_node_descriptions, migrations.RunPython.noop),
    ]
