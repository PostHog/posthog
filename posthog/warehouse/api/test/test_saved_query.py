import uuid
from unittest.mock import patch

from posthog.test.base import APIBaseTest
from posthog.warehouse.models import DataWarehouseModelPath, DataWarehouseSavedQuery
from posthog.models import ActivityLog


class TestSavedQuery(APIBaseTest):
    def test_create(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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

    def test_create_with_types(self):
        with patch.object(DataWarehouseSavedQuery, "get_columns") as mock_get_columns:
            response = self.client.post(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/",
                {
                    "name": "event_view",
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "select event as event from events LIMIT 100",
                    },
                    "types": [["event", "Nullable(String)"]],
                },
            )
            assert response.status_code == 201
            saved_query = response.json()
            assert saved_query["name"] == "event_view"
            assert saved_query["columns"] == [
                {
                    "key": "event",
                    "name": "event",
                    "type": "string",
                    "schema_valid": True,
                    "fields": None,
                    "table": None,
                    "chain": None,
                }
            ]

            mock_get_columns.assert_not_called()

    def test_create_name_overlap_error(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "events",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_create_using_placeholders(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "test_1",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select * from events where {filters}",
                },
            },
        )
        assert response.status_code == 400

        response_json = response.json()
        assert "Variables like {filters} are not allowed in views" in response_json["detail"]

    def test_delete(self):
        query_name = "test_query"
        saved_query = DataWarehouseSavedQuery.objects.create(team=self.team, name=query_name)

        with patch("posthog.warehouse.api.saved_query.delete_saved_query_schedule") as mock_delete_saved_query_schedule:
            response = self.client.delete(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}",
            )

            mock_delete_saved_query_schedule.assert_called()

            assert response.status_code == 204

        saved_query.refresh_from_db()

        assert saved_query.deleted is True
        assert saved_query.deleted_at is not None
        assert saved_query.deleted_name == query_name
        assert saved_query.name.startswith("POSTHOG_DELETED_")

    def test_listing_deleted_queries(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="deleted_saved_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
            deleted=True,
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="saved_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
        )

        assert response.status_code == 200
        json = response.json()

        assert json["count"] == 1

    def test_get_deleted_query(self):
        query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="deleted_saved_query",
            query={
                "kind": "HogQLQuery",
                "query": "select event as event from events LIMIT 100",
            },
            deleted=True,
        )

        response = self.client.get(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{query.id}",
        )

        assert response.status_code == 404

    def test_update_sync_frequency_with_existing_schedule(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201)
        saved_query = response.json()

        with (
            patch("posthog.warehouse.api.saved_query.sync_saved_query_workflow") as mock_sync_saved_query_workflow,
            patch("posthog.warehouse.api.saved_query.saved_query_workflow_exists") as mock_saved_query_workflow_exists,
        ):
            mock_saved_query_workflow_exists.return_value = True

            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {"sync_frequency": "24hour"},
            )

            self.assertEqual(response.status_code, 200)
            mock_saved_query_workflow_exists.assert_called_once()
            mock_sync_saved_query_workflow.assert_called_once()

    def test_update_sync_frequency_to_never(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201)
        saved_query = response.json()

        with patch("posthog.warehouse.api.saved_query.delete_saved_query_schedule") as mock_delete_saved_query_schedule:
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {"sync_frequency": "never"},
            )

            self.assertEqual(response.status_code, 200)
            mock_delete_saved_query_schedule.assert_called_once_with(saved_query["id"])

    def test_update_with_types(self):
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
        self.assertEqual(response.status_code, 201)
        saved_query = response.json()

        with patch.object(DataWarehouseSavedQuery, "get_columns") as mock_get_columns:
            response = self.client.patch(
                f"/api/projects/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {
                    "name": "event_view",
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "select event as event from events LIMIT 100",
                    },
                    "types": [["event", "Nullable(String)"]],
                },
            )

            mock_get_columns.assert_not_called()

    def test_delete_with_existing_schedule(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201)
        saved_query = response.json()

        with patch("posthog.warehouse.api.saved_query.delete_saved_query_schedule") as mock_delete_saved_query_schedule:
            response = self.client.delete(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
            )

            self.assertEqual(response.status_code, 204)
            mock_delete_saved_query_schedule.assert_called_once_with(saved_query["id"])

    def test_saved_query_doesnt_exist(self):
        saved_query_1_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/" + saved_query_1_response["id"],
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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "outer_event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event from event_view LIMIT 100",
                },
            },
        )
        self.assertEqual(saved_view_2_response.status_code, 201, saved_view_2_response.content)

    def test_create_with_saved_query(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": query,
                },
            },
        )

        response_child = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_parent_id}/ancestors",
        )

        self.assertEqual(response.status_code, 200, response.content)
        parent_ancestors = response.json()["ancestors"]
        parent_ancestors.sort()
        self.assertEqual(parent_ancestors, ["events", "persons"])

        saved_query_child_id = response_child.json()["id"]
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/ancestors",
        )

        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors = response.json()["ancestors"]
        child_ancestors.sort()
        self.assertEqual(child_ancestors, sorted([saved_query_parent_id, "events", "persons"]))

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/ancestors", {"level": 1}
        )

        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors_level_1 = response.json()["ancestors"]
        child_ancestors_level_1.sort()
        self.assertEqual(child_ancestors_level_1, [saved_query_parent_id])

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/ancestors", {"level": 2}
        )
        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors_level_2 = response.json()["ancestors"]
        child_ancestors_level_2.sort()
        self.assertEqual(child_ancestors_level_2, sorted([saved_query_parent_id, "events", "persons"]))

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/ancestors", {"level": 10}
        )
        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors_level_10 = response.json()["ancestors"]
        child_ancestors_level_10.sort()
        self.assertEqual(child_ancestors_level_10, sorted([saved_query_parent_id, "events", "persons"]))

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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": query,
                },
            },
        )

        response_child = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view_2",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from event_view",
                },
            },
        )

        response_grand_child = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_parent_id}/descendants",
        )

        self.assertEqual(response.status_code, 200, response.content)
        parent_descendants = response.json()["descendants"]
        self.assertEqual(
            sorted(parent_descendants),
            sorted([saved_query_child_id, saved_query_grand_child_id]),
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_parent_id}/descendants",
            {"level": 1},
        )

        self.assertEqual(response.status_code, 200, response.content)
        parent_descendants_level_1 = response.json()["descendants"]
        self.assertEqual(
            parent_descendants_level_1,
            [saved_query_child_id],
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_parent_id}/descendants",
            {"level": 2},
        )

        self.assertEqual(response.status_code, 200, response.content)
        parent_descendants_level_2 = response.json()["descendants"]
        self.assertEqual(
            sorted(parent_descendants_level_2),
            sorted([saved_query_child_id, saved_query_grand_child_id]),
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_child_id}/descendants",
        )

        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors = response.json()["descendants"]
        self.assertEqual(child_ancestors, [saved_query_grand_child_id])

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_grand_child_id}/descendants",
        )

        self.assertEqual(response.status_code, 200, response.content)
        child_ancestors = response.json()["descendants"]
        self.assertEqual(child_ancestors, [])

    def test_update_without_query_change_doesnt_call_get_columns(self):
        # First create a saved query
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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

        # Now update it without changing the query
        with patch.object(DataWarehouseSavedQuery, "get_columns") as mock_get_columns:
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {"name": "updated_event_view"},  # Only changing the name, not the query
            )

            self.assertEqual(response.status_code, 200, response.content)
            updated_query = response.json()
            self.assertEqual(updated_query["name"], "updated_event_view")

            # Verify get_columns was not called
            mock_get_columns.assert_not_called()

    def test_update_with_query_change_calls_get_columns(self):
        # First create a saved query
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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

        # Now update it with a query change
        with patch.object(DataWarehouseSavedQuery, "get_columns") as mock_get_columns:
            mock_get_columns.return_value = {}
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "select event as event from events LIMIT 10",
                    },
                },
            )

            self.assertEqual(response.status_code, 200, response.content)

            # Verify get_columns was called
            mock_get_columns.assert_called_once()

    def test_create_with_activity_log(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
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
        self.assertEqual(saved_query["query"]["kind"], "HogQLQuery")
        self.assertEqual(saved_query["query"]["query"], "select event as event from events LIMIT 100")

        with patch.object(DataWarehouseSavedQuery, "get_columns") as mock_get_columns:
            mock_get_columns.return_value = {}
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "select event as event from events LIMIT 10",
                    },
                    "current_query": saved_query["query"]["query"],
                },
            )

            self.assertEqual(response.status_code, 200, response.content)

            activity_logs = ActivityLog.objects.filter(
                item_id=saved_query["id"], scope="DataWarehouseSavedQuery"
            ).order_by("-created_at")
            self.assertEqual(activity_logs.count(), 2)
            self.assertEqual(activity_logs[0].activity, "updated")
            query_change = next(change for change in activity_logs[0].detail["changes"] if change["field"] == "query")
            self.assertEqual(
                query_change["after"],
                {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 10",
                },
            )
            self.assertEqual(
                query_change["before"],
                {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            )
            self.assertEqual(activity_logs[1].activity, "created")
            query_change = next(change for change in activity_logs[1].detail["changes"] if change["field"] == "query")
            self.assertEqual(
                query_change["after"],
                {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            )
            self.assertEqual(query_change["before"], None)
