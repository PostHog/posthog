from posthog.test.base import APIBaseTest

from posthog.warehouse.models import DataWarehouseModelPath, DataWarehouseSavedQuery


class TestDag(APIBaseTest):
    def test_get_dag(self):
        parent_query = """\
          select
            events.event,
            persons.properties
          from events
          left join persons on events.person_id = persons.id
          where events.event = 'login' and person.pdi != 'some_distinct_id'
        """
        parent_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": parent_query},
        )
        child_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model_child",
            query={"query": "select * from my_model as my_other_model"},
        )
        DataWarehouseModelPath.objects.create_from_saved_query(parent_saved_query)
        DataWarehouseModelPath.objects.create_from_saved_query(child_saved_query)

        response = self.client.get(
            f"/api/projects/{self.team.id}/warehouse_dag",
        )
        self.assertEqual(response.status_code, 200, response.content)
        dag = response.json()

        self.assertIn([parent_saved_query.id.hex, child_saved_query.id.hex], dag["edges"])
        self.assertIn(["events", parent_saved_query.id.hex], dag["edges"])
        self.assertIn(["persons", parent_saved_query.id.hex], dag["edges"])
        self.assertEqual(len(dag["edges"]), 3)

        self.assertIn([child_saved_query.id.hex, "SavedQuery"], dag["nodes"])
        self.assertIn([parent_saved_query.id.hex, "SavedQuery"], dag["nodes"])
        self.assertIn(["events", "PostHog"], dag["nodes"])
        self.assertIn(["persons", "PostHog"], dag["nodes"])
        self.assertEqual(len(dag["nodes"]), 4)
