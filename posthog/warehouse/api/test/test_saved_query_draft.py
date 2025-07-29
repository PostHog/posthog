from posthog.test.base import APIBaseTest
from posthog.warehouse.models.datawarehouse_saved_query_draft import DataWarehouseSavedQueryDraft
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class TestDataWarehouseSavedQueryDraft(APIBaseTest):
    def test_create_draft(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/warehouse_saved_query_drafts/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
                "name": "test_draft",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        draft = response.json()
        self.assertEqual(
            draft["query"],
            {
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
        )
        self.assertEqual(draft["name"], "test_draft")

    def test_update_draft(self):
        draft = DataWarehouseSavedQueryDraft.objects.create(
            team=self.team,
            created_by=self.user,
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/warehouse_saved_query_drafts/{draft.id}/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as updated from events LIMIT 100",
                },
                "name": "updated_draft",
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        draft.refresh_from_db()
        self.assertEqual(
            draft.query,
            {
                "kind": "HogQLQuery",
                "query": "select event as updated from events LIMIT 100",
            },
        )
        self.assertEqual(draft.name, "updated_draft")

    def test_delete_draft(self):
        draft = DataWarehouseSavedQueryDraft.objects.create(
            team=self.team,
            created_by=self.user,
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
            name="test_draft",
        )

        response = self.client.delete(
            f"/api/environments/{self.team.pk}/warehouse_saved_query_drafts/{draft.id}/",
        )

        self.assertEqual(response.status_code, 204, response.content)
        self.assertFalse(DataWarehouseSavedQueryDraft.objects.filter(id=draft.id).exists())

    def test_list_drafts(self):
        draft = DataWarehouseSavedQueryDraft.objects.create(
            team=self.team,
            created_by=self.user,
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
            name="test_draft",
        )
        DataWarehouseSavedQueryDraft.objects.create(
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
            name="test_draft_2",
        )
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_query_drafts/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(draft.id))
        self.assertEqual(response.json()["results"][0]["name"], "test_draft")

    def test_create_draft_with_saved_query_id(self):
        # Create a saved query first
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="test_query",
            team=self.team,
            query={
                "kind": "HogQLQuery",
                "query": "select event from events LIMIT 50",
            },
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/warehouse_saved_query_drafts/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as updated_event from events LIMIT 100",
                },
                "saved_query_id": str(saved_query.id),
                "name": "test_draft",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        draft = response.json()
        self.assertEqual(draft["saved_query_id"], str(saved_query.id))
        self.assertEqual(draft["name"], "test_draft")
        # Verify it was actually saved to the database
        draft_obj = DataWarehouseSavedQueryDraft.objects.get(id=draft["id"])
        self.assertIsNotNone(draft_obj.edited_history_id)
        self.assertEqual(draft_obj.saved_query.id, saved_query.id)
