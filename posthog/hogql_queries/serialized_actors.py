import uuid
from datetime import datetime
from typing import Any, Literal, Optional, TypedDict, Union

from django.db.models.query import QuerySet

import structlog

from posthog.schema import ActorsQuery

from posthog.hogql_queries.actor_strategies import PersonStrategy
from posthog.hogql_queries.paginators import HogQLHasMorePaginator
from posthog.models import Team
from posthog.models.group import Group

logger = structlog.get_logger(__name__)


class EventInfoForRecording(TypedDict):
    uuid: uuid.UUID
    timestamp: datetime
    window_id: str


class MatchedRecording(TypedDict):
    session_id: str
    events: list[EventInfoForRecording]


class CommonActor(TypedDict):
    id: Union[uuid.UUID, str]
    created_at: Optional[datetime]
    properties: dict[str, Any]
    matched_recordings: list[MatchedRecording]
    value_at_data_point: Optional[float]


class SerializedPerson(CommonActor):
    type: Literal["person"]
    last_seen_at: Optional[datetime]
    uuid: Union[uuid.UUID, str]
    is_identified: Optional[bool]
    name: str
    distinct_ids: list[str]


class SerializedGroup(CommonActor):
    type: Literal["group"]
    group_key: str
    group_type_index: int


SerializedActor = Union[SerializedGroup, SerializedPerson]


def get_groups(
    team_id: int,
    group_type_index: int,
    group_ids: list[Any],
    value_per_actor_id: Optional[dict[str, float]] = None,
) -> tuple[list[Group], list[SerializedGroup]]:
    """Get groups from raw SQL results in data model and dict formats"""
    from posthog.models.group.util import get_groups_by_identifiers

    groups = get_groups_by_identifiers(team_id, group_type_index, [str(gid) for gid in group_ids])
    return groups, serialize_groups(groups, value_per_actor_id)


# Serializes people straight from the actors query, without loading Person model objects
def get_serialized_people(
    team: Team,
    people_ids: list[Any],
    value_per_actor_id: Optional[dict[str, float]] = None,
    distinct_id_limit: int | None = 1000,
) -> list[SerializedPerson]:
    persons_dict = PersonStrategy(team, ActorsQuery(), HogQLHasMorePaginator()).get_actors(
        people_ids, sort_by_created_at_descending=True, limit_per_person=distinct_id_limit
    )
    from posthog.api.person import get_person_name_helper

    return [
        SerializedPerson(
            type="person",
            id=uuid,
            uuid=uuid,
            created_at=person_dict["created_at"],
            last_seen_at=person_dict["last_seen_at"],
            properties=person_dict["properties"],
            is_identified=person_dict["is_identified"],
            name=get_person_name_helper(
                person_dict["id"], person_dict["properties"], person_dict["distinct_ids"], team
            ),
            distinct_ids=person_dict["distinct_ids"]
            if distinct_id_limit is None
            else person_dict["distinct_ids"][:distinct_id_limit],
            matched_recordings=[],
            value_at_data_point=value_per_actor_id[str(uuid)] if value_per_actor_id else None,
        )
        for uuid, person_dict in persons_dict.items()
    ]


def serialize_groups(
    data: QuerySet[Group] | list[Group], value_per_actor_id: Optional[dict[str, float]]
) -> list[SerializedGroup]:
    return [
        SerializedGroup(
            id=group.group_key,
            type="group",
            group_type_index=group.group_type_index,
            group_key=group.group_key,
            created_at=group.created_at,
            matched_recordings=[],
            properties=group.group_properties,
            value_at_data_point=value_per_actor_id[group.group_key] if value_per_actor_id else None,
        )
        for group in data
    ]
