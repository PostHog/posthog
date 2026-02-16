from typing import Any

import pytest
from posthog.test.base import NonAtomicTestMigrations

# skipped in prod because slow. passes locally. to run this test comment this out
pytestmark = pytest.mark.skip("historical migration tests slow overall test run")


class BackfillNodesEdgesMigrationTest(NonAtomicTestMigrations):
    migrate_from = "0005_remove_node_name_unique_within_team_dag_and_more"
    migrate_to = "0006_backfill_nodes_edges_from_saved_queries"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "data_modeling"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        DataWarehouseSavedQuery = apps.get_model("data_warehouse", "DataWarehouseSavedQuery")
        Node = apps.get_model("data_modeling", "Node")

        org = Organization.objects.create(name="Test Organization")
        proj = Project.objects.create(id=999999, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=proj, name="Test Team")
        self.team_id = team.id
        # case 1: saved query without node → SHOULD be backfilled
        self.new_saved_query = DataWarehouseSavedQuery.objects.create(
            team=team,
            name="new_view",
            query={"kind": "HogQLQuery", "query": "SELECT 1"},
            deleted=False,
        )
        # case 2: saved query with existing node → should NOT be backfilled (already handled)
        self.existing_saved_query = DataWarehouseSavedQuery.objects.create(
            team=team,
            name="existing_view",
            query={"kind": "HogQLQuery", "query": "SELECT 2"},
            deleted=False,
        )
        Node.objects.create(
            team=team,
            saved_query=self.existing_saved_query,
            name="existing_view",
            dag_id=f"posthog_{team.id}",
            type="view",
            properties={},
        )
        # case 3: deleted saved query → should NOT be backfilled
        self.deleted_saved_query = DataWarehouseSavedQuery.objects.create(
            team=team,
            name="deleted_view",
            query={"kind": "HogQLQuery", "query": "SELECT 3"},
            deleted=True,
        )
        # case 4: saved query with dependency → should create node with edge
        self.dependent_saved_query = DataWarehouseSavedQuery.objects.create(
            team=team,
            name="dependent_view",
            query={"kind": "HogQLQuery", "query": "SELECT * FROM new_view"},
            deleted=False,
        )

    def test_migration(self) -> None:
        assert self.apps is not None

        Node = self.apps.get_model("data_modeling", "Node")
        Edge = self.apps.get_model("data_modeling", "Edge")

        # case 1: new saved query without existing node → backfilled
        new_node = Node.objects.filter(saved_query_id=self.new_saved_query.id).first()
        self.assertIsNotNone(new_node)
        self.assertEqual(new_node.name, "new_view")
        self.assertTrue(new_node.properties.get("backfilled"))
        # case 2: existing saved query with node → NOT backfilled (node exists but no backfilled property)
        existing_node = Node.objects.filter(saved_query_id=self.existing_saved_query.id).first()
        self.assertIsNotNone(existing_node)
        self.assertFalse(existing_node.properties.get("backfilled"))
        # case 3: deleted saved query → NOT backfilled
        deleted_node = Node.objects.filter(saved_query_id=self.deleted_saved_query.id).first()
        self.assertIsNone(deleted_node)
        # case 4: dependent saved query → backfilled with edge
        dependent_node = Node.objects.filter(saved_query_id=self.dependent_saved_query.id).first()
        self.assertIsNotNone(dependent_node)
        self.assertEqual(dependent_node.name, "dependent_view")
        self.assertTrue(dependent_node.properties.get("backfilled"))
        # edge from new_view to dependent_view
        edge = Edge.objects.filter(source=new_node, target=dependent_node).first()
        self.assertIsNotNone(edge)
        self.assertTrue(edge.properties.get("backfilled"))
        # total: 3 nodes (new_view backfilled, existing_view pre-existing, dependent_view backfilled)
        self.assertEqual(Node.objects.filter(team_id=self.team_id).count(), 3)
