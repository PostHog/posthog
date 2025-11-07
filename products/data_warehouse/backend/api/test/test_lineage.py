from posthog.test.base import APIBaseTest

from posthog.test.db_context_capturing import capture_db_queries

from products.data_warehouse.backend.api.lineage import topological_sort
from products.data_warehouse.backend.models import DataWarehouseSavedQuery, DataWarehouseTable


class TestLineage(APIBaseTest):
    def test_get_upstream_simple_chain(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="base_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from postgres.supabase.users LIMIT 100",
            },
            external_tables=["postgres.supabase.users"],
        )

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="intermediate_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from base_query LIMIT 100",
            },
            external_tables=["base_query"],
        )

        final_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="final_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from intermediate_query LIMIT 100",
            },
            external_tables=["intermediate_query"],
        )

        with capture_db_queries() as context:
            response = self.client.get(
                f"/api/environments/{self.team.id}/lineage/get_upstream/?model_id={final_query.id}"
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()

        self.assertEqual(len(data["nodes"]), 4)

        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["final_query"]["type"], "view")
        self.assertEqual(nodes["intermediate_query"]["type"], "view")
        self.assertEqual(nodes["base_query"]["type"], "view")
        self.assertEqual(nodes["postgres.supabase.users"]["type"], "table")

        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {
            ("intermediate_query", "final_query"),
            ("base_query", "intermediate_query"),
            ("postgres.supabase.users", "base_query"),
        }
        self.assertEqual(edges, expected_edges)

        view_queries = [
            q
            for q in context.captured_queries
            if "datawarehousesavedquery" in q["sql"].lower() or "datawarehousetable" in q["sql"].lower()
        ]
        self.assertLessEqual(len(view_queries), 7, f"Expected 7 queries, got {len(view_queries)}")

    def test_get_upstream_with_datawarehouse_table(self):
        DataWarehouseTable.objects.create(
            team=self.team,
            name="my_table",
            url_pattern="https://example.com/data",
            format="JSONEachRow",
        )

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_query",
            query={
                "kind": "HogQLQuery",
                "query": "select * from my_table",
            },
            external_tables=["my_table"],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/lineage/get_upstream/?model_id={saved_query.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(len(data["nodes"]), 2)

        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["test_query"]["type"], "view")
        self.assertEqual(nodes["my_table"]["type"], "table")
        self.assertEqual(nodes["my_table"]["name"], "my_table")

        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {("my_table", "test_query")}
        self.assertEqual(edges, expected_edges)

    def test_get_upstream_mixed_dependencies(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="base_query",
            query={
                "kind": "HogQLQuery",
                "query": "select * from postgres.supabase.users",
            },
            external_tables=["postgres.supabase.users"],
        )

        mixed_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="mixed_query",
            query={
                "kind": "HogQLQuery",
                "query": "select * from base_query join postgres.supabase.events",
            },
            external_tables=["base_query", "postgres.supabase.events"],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/lineage/get_upstream/?model_id={mixed_query.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(len(data["nodes"]), 4)

        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["mixed_query"]["type"], "view")
        self.assertEqual(nodes["base_query"]["type"], "view")
        self.assertEqual(nodes["postgres.supabase.users"]["type"], "table")
        self.assertEqual(nodes["postgres.supabase.events"]["type"], "table")

        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {
            ("base_query", "mixed_query"),
            ("postgres.supabase.events", "mixed_query"),
            ("postgres.supabase.users", "base_query"),
        }
        self.assertEqual(edges, expected_edges)

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_query",
            query={
                "kind": "HogQLQuery",
                "query": "select * from postgres.supabase.users",
            },
            external_tables=["postgres.supabase.users", "postgres.supabase.events"],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/lineage/get_upstream/?model_id={saved_query.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(len(data["nodes"]), 3)

        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["test_query"]["type"], "view")
        self.assertEqual(nodes["postgres.supabase.users"]["type"], "table")
        self.assertEqual(nodes["postgres.supabase.events"]["type"], "table")

        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {
            ("postgres.supabase.users", "test_query"),
            ("postgres.supabase.events", "test_query"),
        }
        self.assertEqual(edges, expected_edges)

    def test_get_upstream_no_external_tables(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_query",
            query={
                "kind": "HogQLQuery",
                "query": "select 1 as value",
            },
            external_tables=[],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/lineage/get_upstream/?model_id={saved_query.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(len(data["nodes"]), 1)
        self.assertEqual(len(data["edges"]), 0)

        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["test_query"]["type"], "view")

    def test_topological_sort(self):
        nodes = ["A", "B", "C"]
        edges = [{"source": "A", "target": "B"}, {"source": "B", "target": "C"}]
        result = topological_sort(nodes, edges)
        self.assertEqual(result, ["A", "B", "C"])

        # Test DAG with multiple paths and random order
        nodes = ["E", "D", "C", "B", "A"]
        edges = [
            {"source": "D", "target": "E"},
            {"source": "C", "target": "D"},
            {"source": "B", "target": "D"},
            {"source": "A", "target": "C"},
            {"source": "A", "target": "B"},
        ]
        result = topological_sort(nodes, edges)
        # A must come before B and C, B and C must come before D, D must come before E
        self.assertEqual(result[0], "A")
        self.assertEqual(result[-1], "E")
        self.assertIn(result[1], ["B", "C"])
        self.assertIn(result[2], ["B", "C"])
        self.assertEqual(result[3], "D")

        nodes = ["A", "B", "C", "D"]
        edges = [{"source": "A", "target": "B"}, {"source": "C", "target": "D"}]
        result = topological_sort(nodes, edges)
        # A must come before B, C must come before D
        self.assertLess(result.index("A"), result.index("B"))
        self.assertLess(result.index("C"), result.index("D"))
