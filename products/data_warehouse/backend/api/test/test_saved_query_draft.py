from posthog.test.base import APIBaseTest

from posthog.models import Team

from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.datawarehouse_saved_query_draft import DataWarehouseSavedQueryDraft


class TestDataWarehouseSavedQueryDraft(APIBaseTest):
    def test_create_draft(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/warehouse_saved_query_drafts/",
            {
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        assert response.status_code == 201, response.content
        draft = response.json()
        assert draft["query"] == {"kind": "HogQLQuery", "query": "select event as event from events LIMIT 100"}
        # no attached view
        assert draft["name"] == "Untitled"

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
            },
        )

        assert response.status_code == 200, response.content
        draft.refresh_from_db()
        assert draft.query == {"kind": "HogQLQuery", "query": "select event as updated from events LIMIT 100"}
        # no attached view
        assert draft.name == None

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

        assert response.status_code == 204, response.content
        assert not DataWarehouseSavedQueryDraft.objects.filter(id=draft.id).exists()

    def test_list_drafts(self):
        team2 = Team.objects.create(organization=self.organization)

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
        DataWarehouseSavedQueryDraft.objects.create(
            team=team2,
            created_by=self.user,
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
            name="test_draft_2",
        )
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_query_drafts/")

        assert response.status_code == 200, response.content
        response_data = response.json()

        # Verify pagination metadata
        assert "count" in response_data
        assert "next" in response_data
        assert "previous" in response_data
        assert "results" in response_data

        # Verify content
        assert response_data["count"] == 1
        assert response_data["next"] is None
        assert response_data["previous"] is None
        assert len(response_data["results"]) == 1
        assert response_data["results"][0]["id"] == str(draft.id)
        assert response_data["results"][0]["name"] == "test_draft"

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
            },
        )

        assert response.status_code == 201, response.content
        draft = response.json()
        assert draft["saved_query_id"] == str(saved_query.id)
        assert draft["name"] == "(1) test_query"
        # Verify it was actually saved to the database
        draft_obj = DataWarehouseSavedQueryDraft.objects.get(id=draft["id"])
        assert draft_obj.saved_query is not None
        assert draft_obj.saved_query.id == saved_query.id
