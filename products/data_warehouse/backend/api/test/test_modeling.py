from posthog.test.base import APIBaseTest

from products.data_warehouse.backend.models import DataWarehouseModelPath, DataWarehouseSavedQuery


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
        assert response.status_code == 200, response.content
        dag = response.json()

        assert [parent_saved_query.id.hex, child_saved_query.id.hex] in dag["edges"]
        assert ["events", parent_saved_query.id.hex] in dag["edges"]
        assert ["persons", parent_saved_query.id.hex] in dag["edges"]
        assert len(dag["edges"]) == 3

        assert [child_saved_query.id.hex, "SavedQuery"] in dag["nodes"]
        assert [parent_saved_query.id.hex, "SavedQuery"] in dag["nodes"]
        assert ["events", "PostHog"] in dag["nodes"]
        assert ["persons", "PostHog"] in dag["nodes"]
        assert len(dag["nodes"]) == 4
