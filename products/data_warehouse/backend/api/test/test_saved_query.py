import uuid
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import patch

from posthog.models import ActivityLog

from products.data_warehouse.backend.models import DataWarehouseModelPath, DataWarehouseSavedQuery, DataWarehouseTable
from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind


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
        self.assertIsNotNone(saved_query["latest_history_id"])

    def test_upsert(self):
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

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
                "soft_update": True,
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_materialize_view(self):
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

        assert response.status_code == 201
        saved_query_id = response.data["id"]
        assert saved_query_id is not None

        with (
            patch("products.data_warehouse.backend.api.saved_query.sync_saved_query_workflow"),
            patch("products.data_warehouse.backend.api.saved_query.saved_query_workflow_exists", return_value=False),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}",
                {
                    "id": saved_query_id,
                    "lifecycle": "update",
                    "sync_frequency": "24hour",
                },
            )

            assert response.status_code == 200
            assert response.data["is_materialized"] is True

            saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)

            assert saved_query.is_materialized is True

    def test_materialize_view_no_sync_frequency(self):
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

        assert response.status_code == 201
        saved_query_id = response.data["id"]
        assert saved_query_id is not None

        with (
            patch(
                "products.data_warehouse.backend.api.saved_query.pause_saved_query_schedule"
            ) as mock_pause_saved_query_schedule,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}",
                {
                    "id": saved_query_id,
                    "lifecycle": "update",
                    "sync_frequency": "never",
                },
            )

            assert response.status_code == 200
            assert response.data["is_materialized"] is True

            saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)

            assert saved_query.is_materialized is True
            assert saved_query.sync_frequency_interval is None

            mock_pause_saved_query_schedule.assert_called()

        with (
            patch("products.data_warehouse.backend.api.saved_query.sync_saved_query_workflow"),
            patch("products.data_warehouse.backend.api.saved_query.saved_query_workflow_exists", return_value=True),
            patch(
                "products.data_warehouse.backend.api.saved_query.unpause_saved_query_schedule"
            ) as mock_unpause_saved_query_schedule,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}",
                {
                    "id": saved_query_id,
                    "lifecycle": "update",
                    "sync_frequency": "24hour",
                },
            )

            assert response.status_code == 200
            assert response.data["is_materialized"] is True

            saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)

            assert saved_query.is_materialized is True
            assert saved_query.sync_frequency_interval == timedelta(hours=24)

            mock_unpause_saved_query_schedule.assert_called()

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
        assert "Filters and placeholder expressions are not allowed in views" in response_json["detail"]

    def test_create_using_placeholders_foo_variable(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "test_1",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select * from events where {variables.foo}",
                },
            },
        )
        assert response.status_code == 400

        response_json = response.json()
        assert "Variables like {variables.foo} are not allowed in views" in response_json["detail"]

    def test_create_using_placeholders_custom_expr(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "test_1",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select * from events where {1 + 2}",
                },
            },
        )
        assert response.status_code == 400

        response_json = response.json()
        assert "Filters and placeholder expressions are not allowed in views" in response_json["detail"]

    def test_delete(self):
        query_name = "test_query"
        saved_query = DataWarehouseSavedQuery.objects.create(team=self.team, name=query_name)

        with patch(
            "products.data_warehouse.backend.api.saved_query.delete_saved_query_schedule"
        ) as mock_delete_saved_query_schedule:
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

    def test_listing_many_queries(self):
        for i in range(150):
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=f"saved_query_{i}",
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

        assert json["count"] == 150
        assert len(json["results"]) == 150

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
            patch(
                "products.data_warehouse.backend.api.saved_query.sync_saved_query_workflow"
            ) as mock_sync_saved_query_workflow,
            patch(
                "products.data_warehouse.backend.api.saved_query.saved_query_workflow_exists"
            ) as mock_saved_query_workflow_exists,
            patch(
                "products.data_warehouse.backend.api.saved_query.unpause_saved_query_schedule"
            ) as mock_unpause_saved_query_schedule,
        ):
            mock_saved_query_workflow_exists.return_value = True

            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {"sync_frequency": "24hour"},
            )

            self.assertEqual(response.status_code, 200)
            mock_saved_query_workflow_exists.assert_called_once()
            mock_sync_saved_query_workflow.assert_called_once()
            mock_unpause_saved_query_schedule.assert_called_once()

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

        with patch(
            "products.data_warehouse.backend.api.saved_query.pause_saved_query_schedule"
        ) as mock_pause_saved_query_schedule:
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {"sync_frequency": "never"},
            )

            self.assertEqual(response.status_code, 200)
            mock_pause_saved_query_schedule.assert_called_once_with(saved_query["id"])

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

        with patch(
            "products.data_warehouse.backend.api.saved_query.delete_saved_query_schedule"
        ) as mock_delete_saved_query_schedule:
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
                "edited_history_id": saved_query_1_response["latest_history_id"],
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
                    "edited_history_id": saved_query["latest_history_id"],
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
                    "edited_history_id": saved_query["latest_history_id"],
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

            # this should fail because the activity log has changed
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "select event as event from events LIMIT 1",
                    },
                    "edited_history_id": saved_query["latest_history_id"],
                },
            )

            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(response.json()["detail"], "The query was modified by someone else.")

    def test_create_with_activity_log_existing_view(self):
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

        ActivityLog.objects.filter(item_id=saved_query["id"], scope="DataWarehouseSavedQuery").delete()

        with patch.object(DataWarehouseSavedQuery, "get_columns") as mock_get_columns:
            mock_get_columns.return_value = {}
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "select event as event from events LIMIT 10",
                    },
                    "edited_history_id": None,
                },
            )

            self.assertEqual(response.status_code, 200, response.content)

    def test_revert_materialization(self):
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
        saved_query_id = saved_query["id"]

        db_saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)
        db_saved_query.sync_frequency_interval = "24hours"
        db_saved_query.last_run_at = "2025-05-01T00:00:00Z"
        db_saved_query.status = DataWarehouseSavedQuery.Status.COMPLETED
        db_saved_query.is_materialized = True

        mock_table = DataWarehouseTable.objects.create(
            team=self.team, name="materialized_event_view", format="Parquet", url_pattern="s3://bucket/path"
        )
        db_saved_query.table = mock_table
        db_saved_query.save()

        DataWarehouseModelPath.objects.create(team=self.team, path=[mock_table.id.hex, db_saved_query.id.hex])

        with (
            patch(
                "products.data_warehouse.backend.data_load.saved_query_service.delete_schedule"
            ) as mock_delete_schedule,
            patch("products.data_warehouse.backend.data_load.saved_query_service.sync_connect"),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/revert_materialization",
            )

            self.assertEqual(response.status_code, 200, response.content)

            db_saved_query.refresh_from_db()
            self.assertIsNone(db_saved_query.sync_frequency_interval)
            self.assertIsNone(db_saved_query.last_run_at)
            self.assertIsNone(db_saved_query.latest_error)
            self.assertIsNone(db_saved_query.status)
            self.assertIsNone(db_saved_query.table_id)
            self.assertFalse(db_saved_query.is_materialized)

            # Check the table has been deleted
            mock_table.refresh_from_db()
            self.assertTrue(mock_table.deleted)

            self.assertEqual(
                DataWarehouseModelPath.objects.filter(
                    team=self.team, path__lquery=f"*{{1,}}.{db_saved_query.id.hex}"
                ).count(),
                0,
            )

            mock_delete_schedule.assert_called_once_with(mock.ANY, schedule_id=str(db_saved_query.id))

    def test_create_with_existing_name(self):
        DataWarehouseTable.objects.create(
            team=self.team, name="some_event_table", format="Parquet", url_pattern="s3://bucket/path"
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "some_event_table",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "A table with this name already exists."

    def test_update_saved_query_with_managed_viewset_fails(self):
        """Test that updating a saved query with managed viewset fails with correct error message"""
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="managed_view",
            query={"kind": "HogQLQuery", "query": "select event as event from events LIMIT 100"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}",
                {
                    "name": "updated_managed_view",
                    "query": {
                        "kind": "HogQLQuery",
                        "query": "select event as event from events LIMIT 200",
                    },
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"], "Cannot update a query from a managed viewset")

    def test_delete_saved_query_with_managed_viewset_fails(self):
        """Test that deleting a saved query with managed viewset fails with correct error message"""
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="managed_view",
            query={"kind": "HogQLQuery", "query": "select event as event from events LIMIT 100"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.delete(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}",
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json()["detail"],
                "Cannot delete a query from a managed viewset directly. Disable the managed viewset instead.",
            )

    def test_revert_materialization_saved_query_with_managed_viewset_fails(self):
        """Test that reverting materialization of a saved query with managed viewset fails with correct error message"""
        managed_viewset = DataWarehouseManagedViewSet.objects.create(
            team=self.team,
            kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
        )

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="managed_view",
            query={"kind": "HogQLQuery", "query": "select event as event from events LIMIT 100"},
            managed_viewset=managed_viewset,
            created_by=self.user,
        )

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.post(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}/revert_materialization",
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json()["detail"], "Cannot revert materialization of a query from a managed viewset."
            )
