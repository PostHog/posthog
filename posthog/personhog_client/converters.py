from __future__ import annotations

import json
import uuid as uuid_mod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from posthog.models.group.group import Group
    from posthog.models.person import Person
    from posthog.personhog_client.proto.generated.personhog.types.v1 import group_pb2, person_pb2


def proto_group_type_mapping_to_dict(mapping: group_pb2.GroupTypeMapping) -> dict[str, Any]:
    """Convert a proto GroupTypeMapping to the same dict shape as
    Django's GroupTypeMapping.objects.values(*GROUP_TYPE_MAPPING_SERIALIZER_FIELDS).

    Django .values("detail_dashboard") on a ForeignKey produces key "detail_dashboard_id".
    """
    default_columns: list[str] | None = None
    if mapping.default_columns:
        default_columns = json.loads(mapping.default_columns)

    created_at: datetime | None = None
    if mapping.created_at:
        created_at = datetime.fromtimestamp(mapping.created_at / 1000, tz=UTC)

    return {
        "group_type": mapping.group_type or None,
        "group_type_index": mapping.group_type_index,
        "name_singular": mapping.name_singular or None,
        "name_plural": mapping.name_plural or None,
        "detail_dashboard_id": mapping.detail_dashboard_id or None,
        "default_columns": default_columns,
        "created_at": created_at,
    }


@dataclass(frozen=True)
class GroupTypeMappingResult:
    """Lightweight read-only result for viewset lookups that only need group_type and group_type_index."""

    group_type: str
    group_type_index: int


def proto_group_type_mapping_to_result(mapping: group_pb2.GroupTypeMapping) -> GroupTypeMappingResult:
    return GroupTypeMappingResult(
        group_type=mapping.group_type,
        group_type_index=mapping.group_type_index,
    )


def proto_person_to_model(
    person: person_pb2.Person,
    distinct_ids: list[str] | None = None,
) -> Person:
    """Convert a proto Person to a Django Person model instance (unsaved).

    The instance is NOT saved to the database.  It carries data in memory
    so that existing serializers and property accessors work without modification.
    """
    from posthog.models.person import Person as PersonModel

    obj = PersonModel(
        id=person.id,
        uuid=uuid_mod.UUID(person.uuid) if person.uuid else None,
        team_id=person.team_id,
        properties=json.loads(person.properties) if person.properties else {},
        is_identified=person.is_identified,
        created_at=datetime.fromtimestamp(person.created_at / 1000, tz=UTC) if person.created_at else datetime.now(UTC),
        last_seen_at=datetime.fromtimestamp(person.last_seen_at / 1000, tz=UTC) if person.last_seen_at else None,
        version=person.version if person.version is not None else 0,
    )
    if distinct_ids is not None:
        obj._distinct_ids = distinct_ids
    return obj


def proto_group_to_model(group: group_pb2.Group) -> Group:
    """Convert a proto Group to a Django Group model instance (unsaved)."""
    from posthog.models.group.group import Group as GroupModel

    return GroupModel(
        id=group.id,
        team_id=group.team_id,
        group_type_index=group.group_type_index,
        group_key=group.group_key,
        group_properties=json.loads(group.group_properties) if group.group_properties else {},
        created_at=datetime.fromtimestamp(group.created_at / 1000, tz=UTC) if group.created_at else datetime.now(UTC),
        properties_last_updated_at=json.loads(group.properties_last_updated_at)
        if group.properties_last_updated_at
        else {},
        properties_last_operation=json.loads(group.properties_last_operation)
        if group.properties_last_operation
        else {},
        version=group.version,
    )


def fetch_group_type_mapping_result(project_id: int, group_type_index: int) -> GroupTypeMappingResult | None:
    """Fetch a single GroupTypeMappingResult via the personhog gRPC client.

    Raises RuntimeError if the client is not configured (so callers fall back
    to ORM, consistent with ``_fetch_group_types_via_personhog``).
    Returns None if the mapping is not found.
    """
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import GetGroupTypeMappingsByProjectIdRequest

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    resp = client.get_group_type_mappings_by_project_id(GetGroupTypeMappingsByProjectIdRequest(project_id=project_id))
    for m in resp.mappings:
        if m.group_type_index == group_type_index:
            return proto_group_type_mapping_to_result(m)
    return None
