from posthog.test.base import APIBaseTest
from posthog.warehouse.api.lineage import topological_sort
from posthog.warehouse.models import DataWarehouseSavedQuery, DataWarehouseTable
from posthog.test.db_context_capturing import capture_db_queries


class TestLineage(APIBaseTest):
    def test_get_upstream_simple_chain(self):
        # Create a chain of saved queries
        base_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="base_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from postgres.supabase.users LIMIT 100",
            },
            external_tables=["postgres.supabase.users"],
        )

        intermediate_query = DataWarehouseSavedQuery.objects.create(
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

        # Test that we get the full upstream chain
        with capture_db_queries() as context:
            response = self.client.get(
                f"/api/environments/{self.team.id}/lineage/get_upstream/?model_id={final_query.id}"
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()

        # Should have 4 nodes: final_query, intermediate_query, base_query, and postgres.supabase.users
        self.assertEqual(len(data["nodes"]), 4)

        # Check nodes
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["final_query"]["type"], "view")
        self.assertEqual(nodes["intermediate_query"]["type"], "view")
        self.assertEqual(nodes["base_query"]["type"], "view")
        self.assertEqual(nodes["postgres.supabase.users"]["type"], "table")

        # Check edges
        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {
            ("intermediate_query", "final_query"),
            ("base_query", "intermediate_query"),
            ("postgres.supabase.users", "base_query"),
        }
        self.assertEqual(edges, expected_edges)

    def test_get_upstream_with_datawarehouse_table(self):
        # Create a data warehouse table
        table = DataWarehouseTable.objects.create(
            team=self.team,
            name="my_table",
            url_pattern="https://example.com/data",
            format="JSONEachRow",
        )

        # Create a saved query that references the table
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

        # Should have 2 nodes: the view and the table
        self.assertEqual(len(data["nodes"]), 2)

        # Check nodes
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["test_query"]["type"], "view")
        self.assertEqual(nodes["my_table"]["type"], "table")
        self.assertEqual(nodes["my_table"]["name"], "my_table")

        # Check edges
        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {("my_table", "test_query")}
        self.assertEqual(edges, expected_edges)

    def test_get_upstream_mixed_dependencies(self):
        # Create a saved query that depends on both another saved query and external tables
        base_query = DataWarehouseSavedQuery.objects.create(
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

        # Should have 4 nodes: mixed_query, base_query, postgres.supabase.users, postgres.supabase.events
        self.assertEqual(len(data["nodes"]), 4)

        # Check nodes
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["mixed_query"]["type"], "view")
        self.assertEqual(nodes["base_query"]["type"], "view")
        self.assertEqual(nodes["postgres.supabase.users"]["type"], "table")
        self.assertEqual(nodes["postgres.supabase.events"]["type"], "table")

        # Check edges
        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {
            ("base_query", "mixed_query"),
            ("postgres.supabase.events", "mixed_query"),
            ("postgres.supabase.users", "base_query"),
        }
        self.assertEqual(edges, expected_edges)
        # Create a saved query with only external tables
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

        # Should have 3 nodes: the view and 2 external tables
        self.assertEqual(len(data["nodes"]), 3)

        # Check nodes
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["test_query"]["type"], "view")
        self.assertEqual(nodes["postgres.supabase.users"]["type"], "table")
        self.assertEqual(nodes["postgres.supabase.events"]["type"], "table")

        # Check edges
        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {
            ("postgres.supabase.users", "test_query"),
            ("postgres.supabase.events", "test_query"),
        }
        self.assertEqual(edges, expected_edges)

    def test_get_upstream_no_external_tables(self):
        # Create a saved query with no external tables
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

        # Should have only 1 node: the view itself
        self.assertEqual(len(data["nodes"]), 1)
        self.assertEqual(len(data["edges"]), 0)

        # Check node
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
