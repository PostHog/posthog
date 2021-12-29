import uuid
from datetime import datetime
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    TypedDict,
    Union,
    cast,
)

from django.db.models.query import QuerySet

from ee.clickhouse.client import sync_execute
from posthog.models import Entity, Filter, Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.group import Group
from posthog.models.person import Person


class EventInfoForRecording(TypedDict):
    timestamp: datetime
    window_id: str
    session_id: str


class CommonAttributes(TypedDict, total=False):
    id: Union[uuid.UUID, str]
    created_at: Optional[str]
    properties: Dict[str, Any]
    matching_events_for_recording: List[EventInfoForRecording]


class SerializedPerson(CommonAttributes):
    type: Literal["person"]
    is_identified: Optional[bool]
    name: str
    distinct_ids: List[str]


class SerializedGroup(CommonAttributes):
    type: Literal["group"]
    group_key: str
    group_type_index: int


SerializedActor = Union[SerializedGroup, SerializedPerson]


class ActorBaseQuery:
    aggregating_by_groups = False
    entity: Optional[Entity] = None

    def __init__(
        self, team: Team, filter: Union[Filter, StickinessFilter, RetentionFilter], entity: Optional[Entity] = None,
    ):
        self._team = team
        self.entity = entity
        self._filter = filter

    def actor_query(self) -> Tuple[str, Dict]:
        """ Implemented by subclasses. Must provide query and params. The query must return list of uuids. Can be group uuids (group_key) or person uuids """
        raise NotImplementedError()

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        """Override in child class with insight specific logic to determine group aggregation"""
        return False

    @cached_property
    def should_include_matching_events_for_recordings(self) -> bool:
        """Override in child class with insight specific logic to determine when to include events for recordings"""
        return False

    def get_actors(
        self,
    ) -> Tuple[Union[QuerySet[Person], QuerySet[Group]], Union[List[SerializedGroup], List[SerializedPerson]]]:
        """ Get actors in data model and dict formats. Builds query and executes """
        query, params = self.actor_query()
        raw_result = sync_execute(query, params)
        actors, serialized_actors = self.get_actors_from_result(raw_result)

        if self.should_include_matching_events_for_recordings:
            serialized_actors = self.add_matching_events_to_serialized_actors(serialized_actors, raw_result)

        return actors, serialized_actors

    @staticmethod
    def add_matching_events_to_serialized_actors(
        serialized_actors: Union[List[SerializedGroup], List[SerializedPerson]], raw_result
    ) -> Union[List[SerializedGroup], List[SerializedPerson]]:
        matching_events_by_actor_id = {}
        for row in raw_result:
            matching_events_by_actor_id[row[0]] = [
                EventInfoForRecording(timestamp=event[0], session_id=event[1], window_id=event[2]) for event in row[1]
            ]

        # Casting Union[SerializedActor, SerializedGroup] as SerializedPerson because mypy yells
        # when you do an indexed assignment on a Union even if all items in the Union support it
        serialized_actors = cast(List[SerializedPerson], serialized_actors)
        serialized_actors_with_events = []
        for actor in serialized_actors:
            actor["matching_events_for_recording"] = matching_events_by_actor_id[actor["id"]]
            serialized_actors_with_events.append(actor)

        return serialized_actors_with_events

    def get_actors_from_result(
        self, raw_result
    ) -> Tuple[Union[QuerySet[Person], QuerySet[Group]], Union[List[SerializedGroup], List[SerializedPerson]]]:
        actors: Union[QuerySet[Person], QuerySet[Group]]
        serialized_actors: Union[List[SerializedGroup], List[SerializedPerson]]

        actor_ids = [row[0] for row in raw_result]

        if self.is_aggregating_by_groups:
            actors, serialized_actors = self._get_groups(actor_ids)
        else:
            actors, serialized_actors = self._get_people(actor_ids)

        return actors, serialized_actors

    def _get_groups(self, group_ids) -> Tuple[QuerySet[Group], List[SerializedGroup]]:
        """ Get groups from raw SQL results in data model and dict formats """
        groups: QuerySet[Group] = Group.objects.filter(team_id=self._team.pk, group_key__in=group_ids)
        return groups, self._serialize_groups(groups)

    def _get_people(self, people_ids) -> Tuple[QuerySet[Person], List[SerializedPerson]]:
        """ Get people from raw SQL results in data model and dict formats """
        persons: QuerySet[Person] = Person.objects.filter(team_id=self._team.pk, uuid__in=people_ids)
        return persons, self._serialize_people(persons)

    def _serialize_people(self, data: QuerySet[Person]) -> List[SerializedPerson]:
        from posthog.api.person import get_person_name

        return [
            SerializedPerson(
                type="person",
                id=person.uuid,
                created_at=person.created_at,
                properties=person.properties,
                is_identified=person.is_identified,
                name=get_person_name(person),
                distinct_ids=person.distinct_ids,
            )
            for person in data
        ]

    def _serialize_groups(self, data: QuerySet[Group]) -> List[SerializedGroup]:
        return [
            SerializedGroup(
                id=group.group_key,
                type="group",
                group_type_index=group.group_type_index,
                group_key=group.group_key,
                created_at=group.created_at,
                properties=group.group_properties,
            )
            for group in data
        ]
