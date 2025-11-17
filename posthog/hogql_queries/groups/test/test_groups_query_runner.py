import datetime
from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from django.test import override_settings
from django.utils import timezone

from posthog.schema import GroupPropertyFilter, GroupsQuery, PropertyOperator

from posthog.hogql_queries.groups.groups_query_runner import GroupsQueryRunner
from posthog.models import GroupTypeMapping
from posthog.models.group.util import create_group, raw_create_group_ch
from posthog.models.property_definition import PropertyDefinition, PropertyType
from posthog.test.test_utils import create_group_type_mapping_without_created_at


@override_settings(IN_UNIT_TESTING=True)
class TestGroupsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def create_standard_test_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="project", group_type_index=1
        )

        PropertyDefinition.objects.create(
            team=self.team,
            name="arr",
            property_type=PropertyType.Numeric,
            is_numerical=True,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=0,
        )

        for i in range(3):
            arr = [150, 0, 300]
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org{i}",
                properties={"name": f"org{i}.inc", "arr": arr[i]},
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
        self.assertEqual(result.results[0][2], 150)
        self.assertEqual(result.results[1][2], 0)
        self.assertEqual(result.results[2][2], 300)

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_search(self):
        self.create_standard_test_groups()
        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            search="org2",
        )
        query_runner = GroupsQueryRunner(query=query, team=self.team)

        result = query_runner.calculate()

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.columns, ["group_name", "key"])
        self.assertEqual(result.results[0][0], "org2.inc")

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_search_ranking(self):
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        test_groups = [
            {"key": "prefix2", "name": "testable", "ts": datetime.datetime(2025, 11, 3, 17, 16)},
            {"key": "contains", "name": "my_test_group", "ts": datetime.datetime(2025, 11, 3, 17, 15)},
            {"key": "prefix", "name": "testing", "ts": datetime.datetime(2025, 11, 3, 17, 14)},
            {"key": "exact", "name": "test", "ts": datetime.datetime(2025, 11, 3, 17, 17)},
            {"key": "contains2", "name": "best_test_ever", "ts": datetime.datetime(2025, 11, 3, 17, 18)},
        ]
        for group in test_groups:
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=group["key"],  # type: ignore[arg-type]
                properties={"name": group["name"]},
                timestamp=group["ts"],  # type: ignore[arg-type]
            )

        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            search="test",
        )

        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), len(test_groups), "Should match all groups")
        self.assertEqual(result.columns, ["group_name", "key"])
        self.assertEqual(result.results[0][0], "test")
        self.assertEqual(result.results[0][1], "exact")
        self.assertEqual(result.results[1][0], "testable")
        self.assertEqual(result.results[1][1], "prefix2")
        self.assertEqual(result.results[2][0], "testing")
        self.assertEqual(result.results[2][1], "prefix")
        self.assertEqual(result.results[3][0], "best_test_ever")
        self.assertEqual(result.results[3][1], "contains2")
        self.assertEqual(result.results[4][0], "my_test_group")
        self.assertEqual(result.results[4][1], "contains")

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_search_ranking_with_key_fallback(self):
        """Test search ranking when groups don't have name property and fall back to key"""
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        test_groups = [
            {"key": "api_v2", "name": None},
            {"key": "api", "name": None},
            {"key": "legacy_api", "name": None},
        ]
        for group in test_groups:
            props = {"name": group["name"]} if group["name"] else {}
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=str(group["key"]),
                properties=props,
            )

        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            search="api",
        )

        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), len(test_groups), "Should match all groups")
        self.assertEqual(result.results[0][1], "api", "Exact match ranked first")
        self.assertEqual(result.results[1][1], "api_v2", "Prefix match ranked second")
        self.assertEqual(result.results[2][1], "legacy_api", "Contains match ranked last")

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_search_ordering_with_user_orderby(self):
        """Test that similarity ordering comes after user-specified orderBy, not after default created_at DESC"""
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        test_groups = [
            {"key": "exact", "name": "test", "arr": 200},
            {"key": "prefix", "name": "testing", "arr": 100},
            {"key": "contains", "name": "my_test_group", "arr": 300},
        ]
        for group in test_groups:
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=str(group["key"]),
                properties={"name": group["name"], "arr": group["arr"]},
            )

        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            search="test",
            select=["properties.arr"],
            orderBy=["properties.arr DESC"],  # User-specified ordering
        )

        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()
        self.assertEqual(len(result.results), len(test_groups), "Should match all groups")
        self.assertEqual(result.results[0][0], "my_test_group", "Contains match ranked first, highest arr")
        self.assertEqual(result.results[0][2], "300")
        self.assertEqual(result.results[1][0], "test", "Exact match ranked second, mid arr")
        self.assertEqual(result.results[1][2], "200")
        self.assertEqual(result.results[2][0], "testing", "Prefix match ranked last, lowest arr")
        self.assertEqual(result.results[2][2], "100")

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_groups_query_runner_with_order_by(self):
        self.create_standard_test_groups()

        # DESC
        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            select=["properties.arr"],
            orderBy=["properties.arr DESC"],
        )

        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), 3)
        self.assertEqual(result.columns, ["group_name", "key", "properties.arr"])
        self.assertEqual(result.results[0][2], 300)
        self.assertEqual(result.results[1][2], 150)
        self.assertEqual(result.results[2][2], 0)

        # Default to ASC
        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            select=["properties.arr"],
            orderBy=["properties.arr"],
        )

        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), 3)
        self.assertEqual(result.columns, ["group_name", "key", "properties.arr"])
        self.assertEqual(result.results[0][2], 0)
        self.assertEqual(result.results[1][2], 150)
        self.assertEqual(result.results[2][2], 300)

        # group_name has special case behavior
        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            orderBy=["group_name DESC"],
        )

        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), 3)
        self.assertEqual(result.columns, ["group_name", "key"])
        self.assertEqual(result.results[0][0], "org2.inc")
        self.assertEqual(result.results[1][0], "org1.inc")
        self.assertEqual(result.results[2][0], "org0.inc")

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_groups_query_runner_with_string_property(self):
        self.create_standard_test_groups()

        # DESC
        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            properties=[
                GroupPropertyFilter(
                    key="name",
                    type="group",
                    operator=PropertyOperator.EXACT,
                    value="org0.inc",
                    group_type_index=0,
                )
            ],
        )
        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.columns, ["group_name", "key"])
        self.assertEqual(result.results[0][0], "org0.inc")

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_groups_query_runner_with_numeric_property(self):
        self.create_standard_test_groups()

        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            properties=[
                GroupPropertyFilter(
                    key="arr",
                    type="group",
                    operator=PropertyOperator.GT,
                    value=100,
                    group_type_index=0,
                )
            ],
            select=["properties.arr"],
        )
        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), 2)
        self.assertEqual(result.columns, ["group_name", "key", "properties.arr"])
        self.assertEqual(result.results[0][2], 150)
        self.assertEqual(result.results[1][2], 300)

    @freeze_time("2025-01-01")
    @snapshot_clickhouse_queries
    def test_groups_query_runner_normalize_multiple_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        PropertyDefinition.objects.create(
            team=self.team,
            name="arr",
            property_type=PropertyType.Numeric,
            is_numerical=True,
            type=PropertyDefinition.Type.GROUP,
            group_type_index=0,
        )

        group = create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org0",
            properties={"name": "org0.inc", "arr": 100},
        )
        # Saving in Postgres won't update ClickHouse
        group.group_properties["arr"] = 200
        group.save()
        # ... so we need to update ClickHouse too.
        raw_create_group_ch(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org0",
            properties={"name": "org0.inc", "arr": 200},
            created_at=timezone.now() + timedelta(days=1),
            timestamp=timezone.now() + timedelta(days=1),
        )

        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            properties=[
                GroupPropertyFilter(
                    key="name",
                    type="group",
                    operator=PropertyOperator.EXACT,
                    value="org0.inc",
                )
            ],
            select=["properties.arr"],
        )
        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.columns, ["group_name", "key", "properties.arr"])
        self.assertEqual(result.results[0][0], "org0.inc")
        self.assertEqual(result.results[0][2], 200)

    @snapshot_clickhouse_queries
    def test_select_property_name_with_whitespaces(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="myorg",
            properties={"name": "myorg.inc", "arr": 150, "prop with whitespace": True},
        )
        query = GroupsQuery(
            group_type_index=0,
            limit=10,
            offset=0,
            select=['properties."prop with whitespace"'],
        )

        query_runner = GroupsQueryRunner(query=query, team=self.team)
        result = query_runner.calculate()

        group = result.results[0]
        self.assertEqual(group[0], "myorg.inc")
        self.assertEqual(group[1], "myorg")
        self.assertEqual(group[2], "true")
