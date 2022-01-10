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

from django.db.models.query import QuerySet

from ee.clickhouse.client import sync_execute
from posthog.models import Entity, Filter, Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.group import Group
from posthog.models.person import Person


class EventInfoForRecording(TypedDict):
    uuid: uuid.UUID
    timestamp: datetime
    window_id: str


class MatchedRecording(TypedDict):
    session_id: str
    events: List[EventInfoForRecording]


class CommonAttributes(TypedDict, total=False):
    id: Union[uuid.UUID, str]
    created_at: Optional[str]
    properties: Dict[str, Any]
    matched_recordings: List[MatchedRecording]


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
        self,
        team: Team,
        filter: Union[Filter, StickinessFilter, RetentionFilter],
        entity: Optional[Entity] = None,
        **kwargs
    ):
        self._team = team
        self.entity = entity
        self._filter = filter
        self.include_recordings = kwargs.get("include_recordings", False)

    def actor_query(self, limit_actors: Optional[bool] = True) -> Tuple[str, Dict]:
        """ Implemented by subclasses. Must provide query and params. The query must return list of uuids. Can be group uuids (group_key) or person uuids """
        raise NotImplementedError()

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        """Override in child class with insight specific logic to determine group aggregation"""
        return False

    @cached_property
    def should_include_recordings(self) -> bool:
        # Note: include_recordings is not guaranteed to exist because this classes initialization
        # is not guaranteed run due to some of our classes not being setup for multiple-inheritance
        # but being used in multi-inheritance situations. Fixing this is a bit of a refactor.
        if hasattr(self, "include_recordings"):
            return self.include_recordings
        return False

    def get_actors(
        self,
    ) -> Tuple[Union[QuerySet[Person], QuerySet[Group]], Union[List[SerializedGroup], List[SerializedPerson]]]:
        """ Get actors in data model and dict formats. Builds query and executes """
        query, params = self.actor_query()
        raw_result = sync_execute(query, params)
        actors, serialized_actors = self.get_actors_from_result(raw_result)

        if self.should_include_recordings:
            serialized_actors = self.add_matched_recordings_to_serialized_actors(serialized_actors, raw_result)

        return actors, serialized_actors

    def query_for_session_ids_with_recordings(self, session_ids: Set[str]) -> Set[str]:
        """ Filters a list of session_ids to those that actually have recordings """
        query = """
        SELECT 
            distinct session_id
        FROM session_recording_events
        WHERE
            team_id = %(team_id)s
            and has_full_snapshot = 1
            and session_id in %(session_ids)s
        """
        params = {"team_id": self._team.pk, "session_ids": list(session_ids)}
        raw_result = sync_execute(query, params)
        return set([row[0] for row in raw_result])

    def add_matched_recordings_to_serialized_actors(
        self, serialized_actors: Union[List[SerializedGroup], List[SerializedPerson]], raw_result
    ) -> Union[List[SerializedGroup], List[SerializedPerson]]:
        all_session_ids = set()
        for row in raw_result:
            for event in row[1]:
                if event[2]:
                    all_session_ids.add(event[2])

        session_ids_with_recordings = self.query_for_session_ids_with_recordings(all_session_ids)

        matched_recordings_by_actor_id: Dict[Union[uuid.UUID, str], List[MatchedRecording]] = {}
        for row in raw_result:
            recording_events_by_session_id: Dict[str, List[EventInfoForRecording]] = {}
            for event in row[1]:
                event_session_id = event[2]
                if event_session_id and event_session_id in session_ids_with_recordings:
                    recording_events_by_session_id.setdefault(event_session_id, []).append(
                        EventInfoForRecording(uuid=event[0], timestamp=event[1], window_id=event[3])
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
