from django.test import override_settings
from freezegun import freeze_time
from posthog.hogql_queries.groups.groups_query_runner import GroupsQueryRunner
from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.schema import GroupsQuery
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
)


@override_settings(IN_UNIT_TESTING=True)
class TestGroupsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def create_standard_test_groups(self):
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="project", group_type_index=1
        )

        for i in range(3):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org{i}",
                properties={"name": f"org{i}.inc", "arr": f"${i*150}"},
            )

        for i in range(5):
            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key=f"proj{i}",
                properties={"name": f"proj{i}.inc"},
            )

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_groups_query_runner(self):
        self.create_standard_test_groups()

        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
        )
        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), 3)
        self.assertEqual(result.columns, ["group_name", "key"])
        self.assertEqual(result.results[0][0], "org0.inc")
        self.assertEqual(result.results[1][0], "org1.inc")
        self.assertEqual(result.results[2][0], "org2.inc")

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_groups_query_runner_with_offset(self):
        self.create_standard_test_groups()
        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=2,
        )

        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.columns, ["group_name", "key"])
        self.assertEqual(result.results[0][0], "org2.inc")

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_groups_query_runner_with_property_columns(self):
        self.create_standard_test_groups()
        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            select=["properties.arr"],
        )

        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), 3)
        self.assertEqual(result.columns, ["group_name", "key", "properties.arr"])
        self.assertEqual(result.results[0][0], "org0.inc")
        self.assertEqual(result.results[0][2], "$0")
        self.assertEqual(result.results[1][2], "$150")
        self.assertEqual(result.results[2][2], "$300")
