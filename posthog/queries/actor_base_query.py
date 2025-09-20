import uuid
from datetime import datetime, timedelta
from typing import Any, Literal, Optional, TypedDict, Union, cast

from django.db.models import OuterRef, Subquery
from django.db.models.query import Prefetch, QuerySet

from posthog.schema import ActorsQuery

from posthog.constants import INSIGHT_FUNNELS, INSIGHT_PATHS, INSIGHT_TRENDS
from posthog.hogql_queries.actor_strategies import PersonStrategy
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Entity, Filter, PersonDistinctId, SessionRecording, Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.group import Group
from posthog.models.person import Person
from posthog.models.person.person import READ_DB_FOR_PERSONS
from posthog.queries.insight import insight_sync_execute


class EventInfoForRecording(TypedDict):
    uuid: uuid.UUID
    timestamp: datetime
    window_id: str


class MatchedRecording(TypedDict):
    session_id: str
    events: list[EventInfoForRecording]


class CommonActor(TypedDict):
    id: Union[uuid.UUID, str]
    created_at: Optional[str]
    properties: dict[str, Any]
    matched_recordings: list[MatchedRecording]
    value_at_data_point: Optional[float]


class SerializedPerson(CommonActor):
    type: Literal["person"]
    uuid: Union[uuid.UUID, str]
    is_identified: Optional[bool]
    name: str
    distinct_ids: list[str]


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

    def actor_query(self, limit_actors: Optional[bool] = True) -> tuple[str, dict]:
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
    ) -> tuple[
        Union[QuerySet[Person], QuerySet[Group]],
        Union[list[SerializedGroup], list[SerializedPerson]],
        int,
    ]:
        """Get actors in data model and dict formats. Builds query and executes"""
        self._filter.team = self._team
        query, params = self.actor_query()
        raw_result = insight_sync_execute(
            query,
            {**params, **self._filter.hogql_context.values},
            query_type=self.QUERY_TYPE,
            filter=self._filter,
            team_id=self._team.pk,
            settings={"allow_experimental_analyzer": 0},
        )
        actors, serialized_actors = self.get_actors_from_result(raw_result)

        if (
            hasattr(self._filter, "include_recordings")
            and self._filter.include_recordings
            and self._filter.insight in [INSIGHT_PATHS, INSIGHT_TRENDS, INSIGHT_FUNNELS]
        ):
            serialized_actors = self.add_matched_recordings_to_serialized_actors(serialized_actors, raw_result)

        return actors, serialized_actors, len(raw_result)

    def query_for_session_ids_with_recordings(
        self,
        session_ids: set[str],
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> set[str]:
        """Filters a list of session_ids to those that actually have recordings"""
        query = """
        SELECT DISTINCT session_id
        FROM session_replay_events
        WHERE
            team_id = %(team_id)s
            and session_id in %(session_ids)s
        """

        # constrain by date range to help limit the work ClickHouse has to do scanning these tables
        # really we should constrain by TTL too
        # but, we're already not doing that, and this adds the benefit without needing too much change
        if date_from:
            query += " AND min_first_timestamp >= %(date_from)s"

        if date_to:
            query += " AND max_last_timestamp <= %(date_to)s"

        params = {
            "team_id": self._team.pk,
            "session_ids": sorted(session_ids),  # Sort for stable queries
            # widen the date range a little
            # we don't want to exclude sessions that start or end within a
            # reasonable time of the query date range
            "date_from": date_from - timedelta(days=1) if date_from else None,
            "date_to": date_to + timedelta(days=1) if date_to else None,
        }
        raw_result = insight_sync_execute(
            query,
            params,
            query_type="actors_session_ids_with_recordings",
            filter=self._filter,
            team_id=self._team.pk,
        )
        return {row[0] for row in raw_result}

    def add_matched_recordings_to_serialized_actors(
        self,
        serialized_actors: Union[list[SerializedGroup], list[SerializedPerson]],
        raw_result,
    ) -> Union[list[SerializedGroup], list[SerializedPerson]]:
        all_session_ids = set()

        session_events_column_index = 2 if self.ACTOR_VALUES_INCLUDED else 1
        for row in raw_result:
            if len(row) > session_events_column_index:  # Session events are in the last column
                for event in row[session_events_column_index]:
                    if event[2]:
                        all_session_ids.add(event[2])

        session_ids_with_all_recordings = self.query_for_session_ids_with_recordings(
            all_session_ids, self._filter.date_from, self._filter.date_to
        )

        # Prune out deleted recordings
        session_ids_with_deleted_recordings = set(
            SessionRecording.objects.filter(
                team=self._team,
                session_id__in=session_ids_with_all_recordings,
                deleted=True,
            ).values_list("session_id", flat=True)
        )
        session_ids_with_recordings = session_ids_with_all_recordings.difference(session_ids_with_deleted_recordings)

        matched_recordings_by_actor_id: dict[Union[uuid.UUID, str], list[MatchedRecording]] = {}
        for row in raw_result:
            recording_events_by_session_id: dict[str, list[EventInfoForRecording]] = {}
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
        serialized_actors = cast(list[SerializedPerson], serialized_actors)
        serialized_actors_with_recordings = []
        for actor in serialized_actors:
            actor["matched_recordings"] = matched_recordings_by_actor_id[actor["id"]]
            serialized_actors_with_recordings.append(actor)

        return serialized_actors_with_recordings

    def get_actors_from_result(
        self, raw_result
    ) -> tuple[
        Union[QuerySet[Person], QuerySet[Group]],
        Union[list[SerializedGroup], list[SerializedPerson]],
    ]:
        actors: Union[QuerySet[Person], QuerySet[Group]]
        serialized_actors: Union[list[SerializedGroup], list[SerializedPerson]]

        actor_ids = [row[0] for row in raw_result]
        value_per_actor_id = {str(row[0]): row[1] for row in raw_result} if self.ACTOR_VALUES_INCLUDED else None

        if self.is_aggregating_by_groups:
            actors, serialized_actors = get_groups(
                self._team.pk,
                cast(int, self.aggregation_group_type_index),
                actor_ids,
                value_per_actor_id,
            )
        else:
            actors, serialized_actors = get_people(self._team, actor_ids, value_per_actor_id)

        if self.ACTOR_VALUES_INCLUDED:
            # We fetched actors from Postgres in get_groups/get_people, so `ORDER BY actor_value DESC` no longer holds
            # We need .sort() to restore this order
            serialized_actors.sort(
                key=lambda actor: cast(float, actor["value_at_data_point"]),
                reverse=True,
            )

        return actors, serialized_actors


def get_groups(
    team_id: int,
    group_type_index: int,
    group_ids: list[Any],
    value_per_actor_id: Optional[dict[str, float]] = None,
) -> tuple[QuerySet[Group], list[SerializedGroup]]:
    """Get groups from raw SQL results in data model and dict formats"""
    groups: QuerySet[Group] = Group.objects.filter(
        team_id=team_id, group_type_index=group_type_index, group_key__in=group_ids
    )
    return groups, serialize_groups(groups, value_per_actor_id)


def get_people(
    team: Team,
    people_ids: list[Any],
    value_per_actor_id: Optional[dict[str, float]] = None,
    distinct_id_limit=1000,
) -> tuple[QuerySet[Person], list[SerializedPerson]]:
    """Get people from raw SQL results in data model and dict formats"""
    distinct_id_subquery = Subquery(
        PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
        .filter(person_id=OuterRef("person_id"))
        .values_list("id", flat=True)[:distinct_id_limit]
    )
    persons: QuerySet[Person] = (
        Person.objects.db_manager(READ_DB_FOR_PERSONS)
        .filter(team_id=team.pk, uuid__in=people_ids)
        .prefetch_related(
            Prefetch(
                "persondistinctid_set",
                to_attr="distinct_ids_cache",
                queryset=PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS).filter(id__in=distinct_id_subquery),
            )
        )
        .order_by("-created_at", "uuid")
        .only("id", "is_identified", "created_at", "properties", "uuid")
    )
    return persons, serialize_people(team, persons, value_per_actor_id)


# A faster get_people if you don't need the Person objects
def get_serialized_people(
    team: Team, people_ids: list[Any], value_per_actor_id: Optional[dict[str, float]] = None, distinct_id_limit=1000
) -> list[SerializedPerson]:
    persons_dict = PersonStrategy(team, ActorsQuery(), HogQLHasMorePaginator()).get_actors(
        people_ids, order_by="created_at DESC, uuid"
    )
    from posthog.api.person import get_person_name_helper

    return [
        SerializedPerson(
            type="person",
            id=uuid,
            uuid=uuid,
            created_at=person_dict["created_at"],
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


def serialize_people(
    team: Team,
    data: Union[QuerySet[Person], list[Person]],
    value_per_actor_id: Optional[dict[str, float]] = None,
) -> list[SerializedPerson]:
    from posthog.api.person import get_person_name

    return [
        SerializedPerson(
            type="person",
            id=person.uuid,
            uuid=person.uuid,
            created_at=person.created_at,
            properties=person.properties,
            is_identified=person.is_identified,
            name=get_person_name(team, person),
            distinct_ids=person.distinct_ids,
            matched_recordings=[],
            value_at_data_point=value_per_actor_id[str(person.uuid)] if value_per_actor_id else None,
        )
        for person in data
    ]


def serialize_groups(data: QuerySet[Group], value_per_actor_id: Optional[dict[str, float]]) -> list[SerializedGroup]:
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
