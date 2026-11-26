from typing import Any

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.events import EventsPersonSubTable, EventsTable
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.restricted_properties import (
    key_read_overlaps_restriction,
    restricted_feature_flag_names,
    restricted_property_keys_for_table_type,
)

from posthog.models.property import Property
from posthog.models.user import User

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team


def can_access_clustering_filters(team_id: int, user: User, filters: list[dict[str, Any]]) -> bool:
    if not isinstance(filters, list) or any(not isinstance(event_filter, dict) for event_filter in filters):
        return False
    restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team_id)
    if not restrictions:
        return True
    context = HogQLContext(
        team_id=team_id,
        restricted_properties=restrictions,
        # Saved filters must remain safe when the project moves to native JSON.
        use_new_events_schema=True,
    )
    property_tables = {
        "event": ast.TableType(table=EventsTable()),
        "person": ast.TableType(table=EventsPersonSubTable()),
        "group": ast.TableType(table=GroupsTable()),
    }
    for event_filter in filters:
        key = event_filter.get("key")
        # Empty keys read whole property blobs; virtual fields can read hidden dependencies.
        if not isinstance(key, str) or not key or key.startswith("$virt_"):
            return False
        try:
            prop = Property(**event_filter)
        except (TypeError, ValueError, ValidationError):
            return False
        table_type = property_tables.get(prop.type)
        # Cohort and HogQL predicates can reference properties indirectly.
        if table_type is None:
            return False
        restricted_keys = restricted_property_keys_for_table_type(
            table_type, context, group_type_index=prop.group_type_index
        )
        if key_read_overlaps_restriction(prop.key, restricted_keys):
            return False
        if (
            prop.type == "event"
            and key_read_overlaps_restriction(prop.key, {"$active_feature_flags", "$feature_flags"})
            and (
                restricted_feature_flag_names(restricted_keys)
                or key_read_overlaps_restriction("$feature_flags", restricted_keys)
            )
        ):
            return False
        if (
            prop.type == "event"
            and prop.key.startswith("$feature/")
            and key_read_overlaps_restriction("$feature_flags", restricted_keys)
        ):
            return False
    return True


def validate_clustering_filters(team_id: int, user: User, filters: list[dict[str, Any]]) -> None:
    if not can_access_clustering_filters(team_id, user, filters):
        raise PermissionDenied("These clustering filters require property access you don't have. Choose other filters.")
