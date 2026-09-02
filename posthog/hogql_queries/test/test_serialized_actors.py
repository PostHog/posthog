from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_postgres_queries

from posthog.hogql_queries.serialized_actors import get_groups, get_serialized_people, serialize_groups
from posthog.test.persons import create_group


class TestSerializedActors(ClickhouseTestMixin, APIBaseTest):
    @snapshot_postgres_queries
    def test_get_serialized_people_empty(self):
        people_ids: list[Any] = []
        get_serialized_people(self.team, people_ids)

    @snapshot_postgres_queries
    def test_get_groups(self):
        create_group(
            team=self.team,
            group_type_index=0,
            group_key="org_1",
            group_properties={"name": "Organization 1", "industry": "Tech"},
            version=1,
        )
        create_group(
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
        create_group(
            team=self.team,
            group_type_index=1,
            group_key="company_a",
            group_properties={"name": "Company A"},
            version=1,
        )
        create_group(
            team=self.team,
            group_type_index=1,
            group_key="company_b",
            group_properties={"name": "Company B"},
            version=1,
        )

        groups, _ = get_groups(self.team.pk, 1, ["company_a", "company_b"])
        value_per_actor_id = {
            "company_a": 500.0,
            "company_b": 300.0,
        }

        serialized = serialize_groups(groups, value_per_actor_id)

        assert len(serialized) == 2
        assert serialized[0]["value_at_data_point"] in [500.0, 300.0]
