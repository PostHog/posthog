import uuid

from posthog.test.base import APIBaseTest
from posthog.warehouse.models import DataWarehouseModelPath


class TestSavedQuery(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        saved_query = response.json()
        self.assertEqual(saved_query["name"], "event_view")
        self.assertEqual(
            saved_query["columns"],
            [
                {
                    "key": "event",
                    "name": "event",
                    "type": "string",
                    "schema_valid": True,
                    "fields": None,
                    "table": None,
                    "chain": None,
                }
            ],
        )

    def test_create_name_overlap_error(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "events",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_saved_query_doesnt_exist(self):
        saved_query_1_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(saved_query_1_response.status_code, 400, saved_query_1_response.content)

    def test_view_updated(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        saved_query_1_response = response.json()
        saved_query_1_response = self.client.patch(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/" + saved_query_1_response["id"],
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select distinct_id as distinct_id from events LIMIT 100",
                },
            },
        )

        self.assertEqual(saved_query_1_response.status_code, 200, saved_query_1_response.content)
        view_1 = saved_query_1_response.json()
        self.assertEqual(view_1["name"], "event_view")
        self.assertEqual(
            view_1["columns"],
            [
                {
                    "key": "distinct_id",
                    "name": "distinct_id",
                    "type": "string",
                    "schema_valid": True,
                    "fields": None,
                    "table": None,
                    "chain": None,
                }
            ],
        )

    def test_nested_view(self):
        saved_query_1_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(saved_query_1_response.status_code, 201, saved_query_1_response.content)

        saved_view_2_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "outer_event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event from event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(saved_view_2_response.status_code, 400, saved_view_2_response.content)

    def test_create_with_saved_query(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events",
                },
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        saved_query_id = response.json()["id"]
        paths = list(DataWarehouseModelPath.objects.filter(saved_query_id=saved_query_id).all())
        self.assertEqual(len(paths), 1)
        self.assertEqual(["events", uuid.UUID(saved_query_id).hex], paths[0].path)

    def test_create_with_nested_saved_query(self):
        response_1 = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events",
                },
            },
        )
        self.assertEqual(response_1.status_code, 201, response_1.content)

        response_2 = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view_2",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from event_view",
                },
            },
        )
        self.assertEqual(response_2.status_code, 201, response_1.content)

        saved_query_id_hex_1 = uuid.UUID(response_1.json()["id"]).hex
        saved_query_id_hex_2 = uuid.UUID(response_2.json()["id"]).hex

        paths = [model_path.path for model_path in DataWarehouseModelPath.objects.all()]
        self.assertEqual(len(paths), 3)
        self.assertIn(["events"], paths)
        self.assertIn(["events", saved_query_id_hex_1], paths)
        self.assertIn(["events", saved_query_id_hex_1, saved_query_id_hex_2], paths)

    def test_ancestors(self):
        query = """\
          select
            e.event as event,
            p.properties as properties
          from events as e
          left join persons as p on e.person_id = p.id
          where e.event = 'login'
        """

        response_parent = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": query,
                },
            },
        )

        response_child = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view_2",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from event_view",
                },
            },
        )

        self.assertEqual(response_parent.status_code, 201, response_parent.content)
        self.assertEqual(response_child.status_code, 201, response_child.content)

        saved_query_parent_id = response_parent.json()["id"]
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_parent_id}/ancestors",
        )

        self.assertEqual(response.status_code, 200, response.content)
        parent_ancestors = response.json()["ancestors"]
        parent_ancestors.sort()
        self.assertEqual(parent_ancestors, ["events", "persons"])

        saved_query_child_id = response_child.json()["id"]
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/ancestors",
        )

        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors = response.json()["ancestors"]
        child_ancestors.sort()
        self.assertEqual(child_ancestors, sorted([uuid.UUID(saved_query_parent_id).hex, "events", "persons"]))

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/ancestors", {"level": 1}
        )

        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors_level_1 = response.json()["ancestors"]
        child_ancestors_level_1.sort()
        self.assertEqual(child_ancestors_level_1, [uuid.UUID(saved_query_parent_id).hex])

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/ancestors", {"level": 2}
        )
        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors_level_2 = response.json()["ancestors"]
        child_ancestors_level_2.sort()
        self.assertEqual(child_ancestors_level_2, sorted([uuid.UUID(saved_query_parent_id).hex, "events", "persons"]))

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/ancestors", {"level": 10}
        )
        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors_level_10 = response.json()["ancestors"]
        child_ancestors_level_10.sort()
        self.assertEqual(child_ancestors_level_2, sorted([uuid.UUID(saved_query_parent_id).hex, "events", "persons"]))

    def test_descendants(self):
        query = """\
          select
            e.event as event,
            p.properties as properties
          from events as e
          left join persons as p on e.person_id = p.id
          where e.event = 'login'
        """

        response_parent = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": query,
                },
            },
        )

        response_child = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view_2",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from event_view",
                },
            },
        )

        response_grand_child = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view_3",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from event_view_2",
                },
            },
        )

        self.assertEqual(response_parent.status_code, 201, response_parent.content)
        self.assertEqual(response_child.status_code, 201, response_child.content)
        self.assertEqual(response_grand_child.status_code, 201, response_grand_child.content)

        saved_query_parent_id = response_parent.json()["id"]
        saved_query_child_id = response_child.json()["id"]
        saved_query_grand_child_id = response_grand_child.json()["id"]
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_parent_id}/descendants",
        )

        self.assertEqual(response.status_code, 200, response.content)
        parent_descendants = response.json()["descendants"]
        self.assertEqual(
            sorted(parent_descendants),
            sorted([uuid.UUID(saved_query_child_id).hex, uuid.UUID(saved_query_grand_child_id).hex]),
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_parent_id}/descendants", {"level": 1}
        )

        self.assertEqual(response.status_code, 200, response.content)
        parent_descendants_level_1 = response.json()["descendants"]
        self.assertEqual(
            parent_descendants_level_1,
            [uuid.UUID(saved_query_child_id).hex],
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_parent_id}/descendants", {"level": 2}
        )

        self.assertEqual(response.status_code, 200, response.content)
        parent_descendants_level_2 = response.json()["descendants"]
        self.assertEqual(
            sorted(parent_descendants_level_2),
            sorted([uuid.UUID(saved_query_child_id).hex, uuid.UUID(saved_query_grand_child_id).hex]),
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/descendants",
        )

        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors = response.json()["descendants"]
        self.assertEqual(child_ancestors, [uuid.UUID(saved_query_grand_child_id).hex])

        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query_grand_child_id}/descendants",
        )

        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors = response.json()["descendants"]
        self.assertEqual(child_ancestors, [])
