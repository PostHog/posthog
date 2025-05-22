from posthog.test.base import APIBaseTest
from posthog.warehouse.api.lineage import join_components_greedily
from posthog.warehouse.models import DataWarehouseModelPath, DataWarehouseSavedQuery


class TestLineage(APIBaseTest):
    def test_join_components_greedily(self):
        components = ["table1", "column1", "123e4567-e89b-12d3-a456-426614174000", "table2"]
        result = join_components_greedily(components)
        self.assertEqual(result, ["table1.column1", "123e4567-e89b-12d3-a456-426614174000", "table2"])

        components = ["postgres", "supabase", "users"]
        result = join_components_greedily(components)
        self.assertEqual(result, ["postgres.supabase.users"])

        components = ["123e4567-e89b-12d3-a456-426614174000", "987fcdeb-51a2-43d7-b654-987654321000"]
        result = join_components_greedily(components)
        self.assertEqual(result, ["123e4567-e89b-12d3-a456-426614174000", "987fcdeb-51a2-43d7-b654-987654321000"])

        components = []
        result = join_components_greedily(components)
        self.assertEqual(result, [])

        components = [
            "schema",
            "table1",
            "123e4567-e89b-12d3-a456-426614174000",
            "column1",
            "987fcdeb-51a2-43d7-b654-987654321000",
            "table2",
        ]
        result = join_components_greedily(components)
        self.assertEqual(
            result,
            [
                "schema.table1",
                "123e4567-e89b-12d3-a456-426614174000",
                "column1",
                "987fcdeb-51a2-43d7-b654-987654321000",
                "table2",
            ],
        )

    def test_get_upstream(self):
        base_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="base_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
        )

        intermediate_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="intermediate_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from base_query LIMIT 100",
            },
        )

        final_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="final_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from intermediate_query LIMIT 100",
            },
        )

        DataWarehouseModelPath.objects.create(
            team=self.team,
            path=["postgres", "supabase", "users"],
            saved_query=None,
        )

        DataWarehouseModelPath.objects.create(
            team=self.team,
            path=["postgres", "supabase", "users", base_query.id.hex],
            saved_query=base_query,
        )

        DataWarehouseModelPath.objects.create(
            team=self.team,
            path=["postgres", "supabase", "users", base_query.id.hex, intermediate_query.id.hex],
            saved_query=intermediate_query,
        )

        DataWarehouseModelPath.objects.create(
            team=self.team,
            path=["postgres", "supabase", "users", base_query.id.hex, intermediate_query.id.hex, final_query.id.hex],
            saved_query=final_query,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/lineage/get_upstream/?model_id={final_query.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(len(nodes), 4)

        self.assertEqual(nodes["postgres.supabase.users"]["type"], "table")
        self.assertEqual(nodes[base_query.id.hex]["type"], "view")
        self.assertEqual(nodes[intermediate_query.id.hex]["type"], "view")
        self.assertEqual(nodes[final_query.id.hex]["type"], "view")

        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {
            ("postgres.supabase.users", base_query.id.hex),
            (base_query.id.hex, intermediate_query.id.hex),
            (intermediate_query.id.hex, final_query.id.hex),
        }
        self.assertEqual(edges, expected_edges)

        response = self.client.get(
            f"/api/environments/{self.team.id}/lineage/get_upstream/?model_id={intermediate_query.id}"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(len(nodes), 3)

        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {
            ("postgres.supabase.users", base_query.id.hex),
            (base_query.id.hex, intermediate_query.id.hex),
        }
        self.assertEqual(edges, expected_edges)
