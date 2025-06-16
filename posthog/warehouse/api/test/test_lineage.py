from posthog.test.base import APIBaseTest
from posthog.warehouse.api.lineage import join_components_greedily, topological_sort
from posthog.warehouse.models import DataWarehouseModelPath, DataWarehouseSavedQuery
from posthog.test.db_context_capturing import capture_db_queries


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

        # Test that we only make 2 total queries realted to paths and saved queries
        with capture_db_queries() as context:
            response = self.client.get(
                f"/api/environments/{self.team.id}/lineage/get_upstream/?model_id={final_query.id}"
            )
            self.assertEqual(response.status_code, 200)

            # Measure only the queries that are path of the upstream workflow - we get some extra queries from our auth/session system
            view_queries = [
                q
                for q in context.captured_queries
                if "datawarehousemodelpath" in q["sql"].lower() or "datawarehousesavedquery" in q["sql"].lower()
            ]
            self.assertEqual(
                len(view_queries), 2, "Expected exactly 2 queries: one for paths and one for saved queries"
            )
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

    def test_get_upstream_no_paths(self):
        # Create a saved query with external tables but no paths
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

        # Should have 2 edges: from each external table to the view
        self.assertEqual(len(data["edges"]), 2)

        # Check nodes
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes[str(saved_query.id)]["type"], "view")
        self.assertEqual(nodes[str(saved_query.id)]["name"], "test_query")
        self.assertEqual(nodes["postgres.supabase.users"]["type"], "table")
        self.assertEqual(nodes["postgres.supabase.events"]["type"], "table")

        # Check edges
        edges = {(edge["source"], edge["target"]) for edge in data["edges"]}
        expected_edges = {
            ("postgres.supabase.users", str(saved_query.id)),
            ("postgres.supabase.events", str(saved_query.id)),
        }
        self.assertEqual(edges, expected_edges)

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
