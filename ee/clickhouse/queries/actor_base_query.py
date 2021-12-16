import uuid
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    TypedDict,
    Union,
)

from django.db.models.query import QuerySet

from ee.clickhouse.client import sync_execute
from posthog.models import Entity, Filter, Team
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.group import Group
from posthog.models.person import Person


class SerializedActor(TypedDict):
    type: Literal["person", "group"]
    id: Union[uuid.UUID, str]
    created_at: Optional[str]
    properties: Dict[str, Any]


class SerializedPerson(SerializedActor):
    is_identified: Optional[bool]
    name: str
    distinct_ids: List[str]


class SerializedGroup(SerializedActor):
    group_key: str
    group_type_index: int


class ActorBaseQuery:
    aggregating_by_groups = False
    entity: Optional[Entity] = None
    _no_person_limit = False

    def __init__(
        self,
        team: Team,
        filter: Union[Filter, StickinessFilter],
        entity: Optional[Entity] = None,
        no_person_limit: Optional[bool] = False,
    ):
        self._team = team
        self.entity = entity
        self._filter = filter
        self._no_person_limit = no_person_limit

    def actor_query(self) -> Tuple[str, Dict]:
        """ Implemented by subclasses. Must provide query and params. The query must return list of uuids. Can be group uuids (group_key) or person uuids """
        raise NotImplementedError()

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        """Override in child class with insight specific logic to determine group aggregation"""
        return False

    def get_actors(
        self,
    ) -> Tuple[Union[QuerySet[Person], QuerySet[Group]], Union[List[SerializedGroup], List[SerializedPerson]]]:
        """ Get actors in data model and dict formats. Builds query and executes """
        query, params = self.actor_query()
        raw_result = sync_execute(query, params)
        actors: Union[QuerySet[Person], QuerySet[Group]]
        serialized_actors: Union[List[SerializedGroup], List[SerializedPerson]]
        if self.is_aggregating_by_groups:
            actors, serialized_actors = self._get_groups(raw_result)
        else:
            actors, serialized_actors = self._get_people(raw_result)
        return actors, serialized_actors

    def _get_groups(self, results) -> Tuple[QuerySet[Group], List[SerializedGroup]]:
        """ Get groups from raw SQL results in data model and dict formats """
        groups: QuerySet[Group] = Group.objects.filter(team_id=self._team.pk, group_key__in=[val[0] for val in results])
        return groups, self._serialize_groups(groups)

    def _get_people(self, results) -> Tuple[QuerySet[Person], List[SerializedPerson]]:
        """ Get people from raw SQL results in data model and dict formats """
        persons: QuerySet[Person] = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])
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
