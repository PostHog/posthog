import uuid
from datetime import datetime
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    TypedDict,
    Union,
    cast,
)

from django.db.models import OuterRef, Subquery
from django.db.models.query import Prefetch, QuerySet

from posthog.constants import INSIGHT_FUNNELS, INSIGHT_PATHS, INSIGHT_TRENDS
from posthog.models import Entity, Filter, PersonDistinctId, Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.group import Group
from posthog.models.person import Person
from posthog.queries.insight import insight_sync_execute


class EventInfoForRecording(TypedDict):
    uuid: uuid.UUID
    timestamp: datetime
    window_id: str


class MatchedRecording(TypedDict):
    session_id: str
    events: List[EventInfoForRecording]


class CommonActor(TypedDict):
    id: Union[uuid.UUID, str]
    created_at: Optional[str]
    properties: Dict[str, Any]
    matched_recordings: List[MatchedRecording]
    value_at_data_point: Optional[float]


class SerializedPerson(CommonActor):
    type: Literal["person"]
    uuid: Union[uuid.UUID, str]
    is_identified: Optional[bool]
    name: str
    distinct_ids: List[str]


class SerializedGroup(CommonActor):
    type: Literal["group"]
    group_key: str
    group_type_index: int


SerializedActor = Union[SerializedGroup, SerializedPerson]


class ActorBaseQuery:
    # Whether actor values are included as the second column of the actors query
    ACTOR_VALUES_INCLUDED = False
    # What query type to report
    QUERY_TYPE = "actors"

    entity: Optional[Entity] = None

    def __init__(
        self,
        team: Team,
        filter: Union[Filter, StickinessFilter, RetentionFilter],
        entity: Optional[Entity] = None,
        **kwargs,
    ):
        self._team = team
        self.entity = entity
        self._filter = filter

    def actor_query(self, limit_actors: Optional[bool] = True) -> Tuple[str, Dict]:
        """Implemented by subclasses. Must provide query and params. The query must return list of uuids. Can be group uuids (group_key) or person uuids"""
        raise NotImplementedError()

    @cached_property
    def aggregation_group_type_index(self) -> Optional[int]:
        """Override in child class with insight specific logic to determine group aggregation"""
        return None

    @property
    def is_aggregating_by_groups(self) -> bool:
        return self.aggregation_group_type_index is not None

    def get_actors(
        self,
    ) -> Tuple[Union[QuerySet[Person], QuerySet[Group]], Union[List[SerializedGroup], List[SerializedPerson]], int]:
        """Get actors in data model and dict formats. Builds query and executes"""
        query, params = self.actor_query()
        raw_result = insight_sync_execute(query, params, query_type=self.QUERY_TYPE, filter=self._filter)
        actors, serialized_actors = self.get_actors_from_result(raw_result)

        if hasattr(self._filter, "include_recordings") and self._filter.include_recordings and self._filter.insight in [INSIGHT_PATHS, INSIGHT_TRENDS, INSIGHT_FUNNELS]:  # type: ignore
            serialized_actors = self.add_matched_recordings_to_serialized_actors(serialized_actors, raw_result)

        return actors, serialized_actors, len(raw_result)

    def query_for_session_ids_with_recordings(self, session_ids: Set[str]) -> Set[str]:
        """Filters a list of session_ids to those that actually have recordings"""
        query = """
        SELECT DISTINCT session_id
        FROM session_recording_events
        WHERE
            team_id = %(team_id)s
            and has_full_snapshot = 1
            and session_id in %(session_ids)s
        """
        params = {"team_id": self._team.pk, "session_ids": list(session_ids)}
        raw_result = insight_sync_execute(query, params, query_type="actors_session_ids_with_recordings")
        return {row[0] for row in raw_result}

    def add_matched_recordings_to_serialized_actors(
        self, serialized_actors: Union[List[SerializedGroup], List[SerializedPerson]], raw_result
    ) -> Union[List[SerializedGroup], List[SerializedPerson]]:
        all_session_ids = set()

        session_events_column_index = 2 if self.ACTOR_VALUES_INCLUDED else 1
        for row in raw_result:
            if len(row) > session_events_column_index:  # Session events are in the last column
                for event in row[session_events_column_index]:
                    if event[2]:
                        all_session_ids.add(event[2])

        session_ids_with_recordings = self.query_for_session_ids_with_recordings(all_session_ids)

        matched_recordings_by_actor_id: Dict[Union[uuid.UUID, str], List[MatchedRecording]] = {}
        for row in raw_result:
            recording_events_by_session_id: Dict[str, List[EventInfoForRecording]] = {}
            if len(row) > session_events_column_index - 1:
                for event in row[session_events_column_index]:
                    event_session_id = event[2]
                    if event_session_id and event_session_id in session_ids_with_recordings:
                        recording_events_by_session_id.setdefault(event_session_id, []).append(
                            EventInfoForRecording(timestamp=event[0], uuid=event[1], window_id=event[3])
                        )
            recordings = [
                MatchedRecording(session_id=session_id, events=events)
                for session_id, events in recording_events_by_session_id.items()
            ]

            matched_recordings_by_actor_id[row[0]] = recordings

        # Casting Union[SerializedActor, SerializedGroup] as SerializedPerson because mypy yells
        # when you do an indexed assignment on a Union even if all items in the Union support it
        serialized_actors = cast(List[SerializedPerson], serialized_actors)
        serialized_actors_with_recordings = []
        for actor in serialized_actors:
            actor["matched_recordings"] = matched_recordings_by_actor_id[actor["id"]]
            serialized_actors_with_recordings.append(actor)

        return serialized_actors_with_recordings

    def get_actors_from_result(
        self, raw_result
    ) -> Tuple[Union[QuerySet[Person], QuerySet[Group]], Union[List[SerializedGroup], List[SerializedPerson]]]:
        actors: Union[QuerySet[Person], QuerySet[Group]]
        serialized_actors: Union[List[SerializedGroup], List[SerializedPerson]]

        actor_ids = [row[0] for row in raw_result]
        value_per_actor_id = {str(row[0]): row[1] for row in raw_result} if self.ACTOR_VALUES_INCLUDED else None

        if self.is_aggregating_by_groups:
            actors, serialized_actors = get_groups(
                self._team.pk, cast(int, self.aggregation_group_type_index), actor_ids, value_per_actor_id
            )
        else:
            actors, serialized_actors = get_people(self._team.pk, actor_ids, value_per_actor_id)

        if self.ACTOR_VALUES_INCLUDED:
            # We fetched actors from Postgres in get_groups/get_people, so `ORDER BY actor_value DESC` no longer holds
            # We need .sort() to restore this order
            serialized_actors.sort(key=lambda actor: cast(float, actor["value_at_data_point"]), reverse=True)

        return actors, serialized_actors


def get_groups(
    team_id: int, group_type_index: int, group_ids: List[Any], value_per_actor_id: Optional[Dict[str, float]] = None
) -> Tuple[QuerySet[Group], List[SerializedGroup]]:
    """Get groups from raw SQL results in data model and dict formats"""
    groups: QuerySet[Group] = Group.objects.filter(
        team_id=team_id, group_type_index=group_type_index, group_key__in=group_ids
    )
    return groups, serialize_groups(groups, value_per_actor_id)


def get_people(
    team_id: int, people_ids: List[Any], value_per_actor_id: Optional[Dict[str, float]] = None, distinct_id_limit=None
) -> Tuple[QuerySet[Person], List[SerializedPerson]]:
    """Get people from raw SQL results in data model and dict formats"""
    distinct_id_subquery = Subquery(
        PersonDistinctId.objects.filter(person_id=OuterRef("person_id")).values_list("id", flat=True)[
            :distinct_id_limit
        ]
    )
    persons: QuerySet[Person] = (
        Person.objects.filter(team_id=team_id, uuid__in=people_ids)
        .prefetch_related(
            Prefetch(
                "persondistinctid_set",
                to_attr="distinct_ids_cache",
                queryset=PersonDistinctId.objects.filter(id__in=distinct_id_subquery),
            )
        )
        .order_by("-created_at", "uuid")
        .only("id", "is_identified", "created_at", "properties", "uuid")
    )
    return persons, serialize_people(persons, value_per_actor_id)


def serialize_people(data: QuerySet[Person], value_per_actor_id: Optional[Dict[str, float]]) -> List[SerializedPerson]:
    from posthog.api.person import get_person_name

    return [
        SerializedPerson(
            type="person",
            id=person.uuid,
            uuid=person.uuid,
            created_at=person.created_at,
            properties=person.properties,
            is_identified=person.is_identified,
            name=get_person_name(person),
            distinct_ids=person.distinct_ids,
            matched_recordings=[],
            value_at_data_point=value_per_actor_id[str(person.uuid)] if value_per_actor_id else None,
        )
        for person in data
    ]


def serialize_groups(data: QuerySet[Group], value_per_actor_id: Optional[Dict[str, float]]) -> List[SerializedGroup]:
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
