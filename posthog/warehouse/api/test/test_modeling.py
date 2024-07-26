import uuid

from posthog.test.base import APIBaseTest
from posthog.warehouse.models import DataWarehouseModelPath


class TestSavedQuery(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_models/",
            {
                "name": "test_model_table",
                "materialization": "Incremental",
                "unique_key": ["uuid"],
                "incremental_key": ["timestamp"],
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select events.event, persons.properties from events left join persons on events.person_id = persons.id where events.event = 'login' and person.pdi != 'some_distinct_id'",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        model = response.json()
        self.assertEqual(model["name"], "test_model_table")
        self.assertEqual(model["materialization"], "Incremental")
        self.assertEqual(model["unique_key"], ["uuid"])
        self.assertEqual(model["incremental_key"], ["timestamp"])

        paths = list(model_path.path for model_path in DataWarehouseModelPath.objects.all())
        paths.sort(key=lambda p: p[0])
        model_uuid = uuid.UUID(model["id"])
        self.assertEqual(paths, [["events", model_uuid.hex], ["persons", model_uuid.hex]])
