from typing import Any

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    flush_persons_and_events,
    snapshot_postgres_queries,
)

from posthog.models import Group, Person
from posthog.queries.actor_base_query import (
    get_groups,
    get_people,
    get_serialized_people,
    serialize_groups,
    serialize_people,
)


class TestActorsBaseQuery(ClickhouseTestMixin, APIBaseTest):
    @snapshot_postgres_queries
    def test_serialize_people_basic(self):
        person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={
                "name": "p1",
                "email": "test@posthog.com",
            },
        )
        flush_persons_and_events()

        persons = Person.objects.filter(uuid=person.uuid)
        result = serialize_people(self.team, persons)

        assert len(result) == 1
        assert result[0]["uuid"] == person.uuid
        assert result[0]["properties"]["email"] == "test@posthog.com"

    @snapshot_postgres_queries
    def test_get_people_with_prefetch(self):
        person1 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1", "p1_alias"],
            properties={"name": "Person 1", "email": "p1@test.com"},
        )
        person2 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["p2", "p2_alias", "p2_another"],
            properties={"name": "Person 2", "email": "p2@test.com"},
        )
        flush_persons_and_events()

        people_ids = [person1.uuid, person2.uuid]
        persons_queryset, serialized = get_people(self.team, people_ids)

        assert len(serialized) == 2
        assert persons_queryset.count() == 2

    @snapshot_postgres_queries
    def test_get_people_with_value_per_actor(self):
        person1 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["p1"],
            properties={"name": "High Value"},
        )
        person2 = _create_person(
            team_id=self.team.pk,
            distinct_ids=["p2"],
            properties={"name": "Low Value"},
        )
        flush_persons_and_events()

        people_ids = [person1.uuid, person2.uuid]
        value_per_actor_id = {
            str(person1.uuid): 100.5,
            str(person2.uuid): 25.3,
        }

        _, serialized = get_people(self.team, people_ids, value_per_actor_id)

        assert len(serialized) == 2
        values = [s["value_at_data_point"] for s in serialized]
        assert set(values) == {100.5, 25.3}

    @snapshot_postgres_queries
    def test_get_people_with_distinct_id_limit(self):
        person = _create_person(
            team_id=self.team.pk,
            distinct_ids=["id1", "id2", "id3", "id4", "id5"],
            properties={"name": "Many IDs"},
        )
        flush_persons_and_events()

        _, serialized = get_people(self.team, [person.uuid], distinct_id_limit=3)

        assert len(serialized) == 1
        assert len(serialized[0]["distinct_ids"]) <= 3

    @snapshot_postgres_queries
    def test_get_serialized_people_empty(self):
        people_ids: list[Any] = []
        get_serialized_people(self.team, people_ids)

    @snapshot_postgres_queries
    def test_get_groups(self):
        Group.objects.create(
            team=self.team,
            group_type_index=0,
            group_key="org_1",
            group_properties={"name": "Organization 1", "industry": "Tech"},
            version=1,
        )
        Group.objects.create(
            team=self.team,
            group_type_index=0,
            group_key="org_2",
            group_properties={"name": "Organization 2", "industry": "Finance"},
            version=1,
        )

        group_ids = ["org_1", "org_2"]
        groups_queryset, serialized = get_groups(self.team.pk, 0, group_ids)

        assert len(serialized) == 2
        assert serialized[0]["group_key"] in group_ids
        assert serialized[1]["group_key"] in group_ids

    @snapshot_postgres_queries
    def test_serialize_groups_with_values(self):
        Group.objects.create(
            team=self.team,
            group_type_index=1,
            group_key="company_a",
            group_properties={"name": "Company A"},
            version=1,
        )
        Group.objects.create(
            team=self.team,
            group_type_index=1,
            group_key="company_b",
            group_properties={"name": "Company B"},
            version=1,
        )

        groups = Group.objects.filter(group_key__in=["company_a", "company_b"])
        value_per_actor_id = {
            "company_a": 500.0,
            "company_b": 300.0,
        }

        serialized = serialize_groups(groups, value_per_actor_id)

        assert len(serialized) == 2
        assert serialized[0]["value_at_data_point"] in [500.0, 300.0]
