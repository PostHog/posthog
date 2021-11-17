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
from posthog.models.group import Group
from posthog.models.person import Person


class SerializedPerson(TypedDict):
    type: Literal["person"]
    id: str
    created_at: Optional[str]
    properties: Dict[str, Any]
    is_identified: Optional[bool]
    name: str
    distinct_ids: List[str]


class SerializedGroup(TypedDict):
    type: Literal["group"]
    group_key: str
    created_at: Optional[str]
    properties: Dict[str, Any]


SerializedActor = Union[SerializedPerson, SerializedGroup]
Actor = Union[Person, Group]


class ActorBaseQuery:
    aggregating_by_groups = False

    def __init__(self, team: Team, filter: Filter, entity: Optional[Entity] = None):
        self.team = team
        self.entity = entity
        self.filter = filter

        if self.entity and self.entity.math == "unique_group":
            self.aggregating_by_groups = True

    def groups_query(self) -> Tuple[str, Dict]:
        """ Implemented by subclasses. Must return list of group uuids """
        raise NotImplementedError()

    def people_query(self) -> Tuple[str, Dict]:
        """ Implemented by subclasses. Must return list of person uuids """
        raise NotImplementedError()

    def get_actor_query(self) -> Tuple[str, Dict]:
        if self.aggregating_by_groups:
            query, params = self.groups_query()
            return query, params
        else:
            query, params = self.people_query()
            return query, params

    def get_actors(self) -> Tuple[QuerySet[Actor], List[SerializedActor]]:
        """ Get actors in data model and dict formats. Builds query and executes """
        query, params = self.get_actor_query()
        raw_result = sync_execute(query, params)
        actors: QuerySet[Actor]
        serialized_actors: List[SerializedActor] = []
        if self.aggregating_by_groups:
            actors, serialized_actors = self._get_groups(raw_result)
        else:
            actors, serialized_actors = self._get_people(raw_result)
        return actors, serialized_actors

    def _get_groups(self, results) -> Tuple[QuerySet[Actor], List[SerializedActor]]:
        """ Get groups from raw SQL results in data model and dict formats """
        groups: QuerySet[Actor] = Group.objects.filter(team_id=self.team.pk, group_key__in=[val[0] for val in results])
        return groups, self._serialize_groups(groups)

    def _get_people(self, results) -> Tuple[QuerySet[Actor], List[SerializedActor]]:
        """ Get people from raw SQL results in data model and dict formats """
        persons: QuerySet[Actor] = Person.objects.filter(team_id=self.team.pk, uuid__in=[val[0] for val in results])
        return persons, self._serialize_people(persons)

    def _serialize_people(self, data: QuerySet[Actor]) -> List[SerializedActor]:
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
            if isinstance(person, Person)
        ]

    def _serialize_groups(self, data: QuerySet[Actor]) -> List[SerializedActor]:
        return [
            SerializedGroup(
                type="group", group_key=group.group_key, created_at=group.created_at, properties=group.group_properties
            )
            for group in data
            if isinstance(group, Group)
        ]
