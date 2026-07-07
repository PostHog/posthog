import uuid
from datetime import timedelta
from typing import Any, cast

from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import AsyncMock, patch

from parameterized import parameterized

from posthog.models import ActivityLog
from posthog.models.activity_logging.activity_log import Detail

from products.data_modeling.backend.facade.modeling import DataWarehouseModelPath
from products.data_modeling.backend.facade.models import (
    DAG,
    DataModelingJob,
    DataWarehouseManagedViewSet,
    DataWarehouseSavedQuery,
    DataWarehouseSavedQueryColumnAnnotation,
    Node,
    NodeType,
)
from products.data_tools.backend.models.datawarehouse_saved_query_folder import DataWarehouseSavedQueryFolder
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind


class TestSavedQuery(APIBaseTest):
    def test_create_with_folder(self):
        folder = DataWarehouseSavedQueryFolder.objects.create(team=self.team, name="Marketing", created_by=self.user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
                "folder_id": str(folder.id),
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        saved_query = response.json()
        self.assertEqual(saved_query["folder_id"], str(folder.id))
        self.assertEqual(saved_query["folder_name"], "Marketing")

    def test_create_with_other_team_folder_id_matches_nonexistent_folder_error(self):
        other_team = self.create_team_with_organization(organization=self.organization)
        other_team_folder = DataWarehouseSavedQueryFolder.objects.create(
            team=other_team, name="Other team folder", created_by=self.user
        )
        missing_folder_id = uuid.uuid4()

        other_team_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
                "folder_id": str(other_team_folder.id),
            },
        )
        missing_folder_response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
                "folder_id": str(missing_folder_id),
            },
        )

        self.assertEqual(other_team_response.status_code, 400, other_team_response.content)
        self.assertEqual(missing_folder_response.status_code, 400, missing_folder_response.content)
        self.assertEqual(other_team_response.json()["attr"], "folder_id")
        self.assertEqual(missing_folder_response.json()["attr"], "folder_id")
        self.assertEqual(other_team_response.json()["code"], "does_not_exist")
        self.assertEqual(missing_folder_response.json()["code"], "does_not_exist")
        self.assertTrue(other_team_response.json()["detail"].endswith("- object does not exist."))
        self.assertTrue(missing_folder_response.json()["detail"].endswith("- object does not exist."))

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
                    "description": None,
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
            patch("products.data_warehouse.backend.logic.data_load.saved_query_service.sync_saved_query_workflow"),
            patch(
                "products.data_warehouse.backend.logic.data_load.saved_query_service.saved_query_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/materialize",
            )

            assert response.status_code == 200

            saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)

            assert saved_query.is_materialized is True
            assert saved_query.sync_frequency_interval == timedelta(hours=24)

    def test_materialize_action_idempotent(self):
        """Test that the materialize action is idempotent and can be called multiple times"""
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
            patch("products.data_warehouse.backend.logic.data_load.saved_query_service.sync_saved_query_workflow"),
            patch(
                "products.data_warehouse.backend.logic.data_load.saved_query_service.saved_query_workflow_exists",
                return_value=False,
            ),
        ):
            # First call to materialize
            response = self.client.post(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/materialize",
            )

            assert response.status_code == 200

            saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)
            assert saved_query.is_materialized is True
            assert saved_query.sync_frequency_interval == timedelta(hours=24)

        with (
            patch(
                "products.data_warehouse.backend.logic.data_load.saved_query_service.sync_saved_query_workflow"
            ) as mock_sync,
            patch(
                "products.data_warehouse.backend.logic.data_load.saved_query_service.saved_query_workflow_exists",
                return_value=True,
            ),
            patch(
                "products.data_warehouse.backend.logic.data_load.saved_query_service.unpause_saved_query_schedule"
            ) as mock_unpause,
        ):
            # Second call to materialize - should be idempotent
            response = self.client.post(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/materialize",
            )

            assert response.status_code == 200

            saved_query.refresh_from_db()
            assert saved_query.is_materialized is True
            assert saved_query.sync_frequency_interval == timedelta(hours=24)
            # Schedule already exists, so should not unpause (unpause=False on second call)
            mock_unpause.assert_not_called()
            # But should still update the schedule
            mock_sync.assert_called_once()

    def test_materialize_action_with_managed_viewset_fails(self):
        """Test that materializing a managed viewset query fails"""
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
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}/materialize",
            )

            assert response.status_code == 400
            assert response.json()["detail"] == "Cannot materialize a query from a managed viewset."

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
                    "description": None,
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

    def test_create_with_query_as_string_returns_validation_error(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view_bad_payload",
                "query": '{"kind": "HogQLQuery", "query": "SELECT 1"}',
            },
            format="json",
        )
        assert response.status_code == 400, response.content
        response_json = response.json()
        assert "JSON object" in response_json.get("detail", "")

    def test_create_with_query_missing_query_key_returns_validation_error(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view_missing_key",
                "query": {"kind": "HogQLQuery"},
            },
            format="json",
        )
        assert response.status_code == 400, response.content

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

    def test_create_with_malformed_query_returns_validation_error(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "test_malformed",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select * from events *",
                },
            },
        )
        assert response.status_code == 400, response.content
        response_json = response.json()
        assert "Invalid query" in response_json["detail"]

    def test_delete(self):
        query_name = "test_query"
        saved_query = DataWarehouseSavedQuery.objects.create(team=self.team, name=query_name)

        with patch(
            "products.data_warehouse.backend.logic.data_load.saved_query_service.delete_saved_query_schedule"
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

        delete_activity = ActivityLog.objects.get(
            item_id=str(saved_query.id), scope="DataWarehouseSavedQuery", activity="deleted"
        )
        assert cast(dict[str, Any], delete_activity.detail)["name"] == query_name

    def test_update_folder_assignment(self):
        folder = DataWarehouseSavedQueryFolder.objects.create(
            team=self.team, name="Warehouse ops", created_by=self.user
        )
        saved_query = DataWarehouseSavedQuery.objects.create(team=self.team, name="test_query", created_by=self.user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}/",
            {"folder_id": str(folder.id), "soft_update": True},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        saved_query.refresh_from_db()
        self.assertEqual(saved_query.folder_id, folder.id)

    def test_create_folder_and_list_view_count(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_query_folders/",
            {"name": "Finance"},
        )

        self.assertEqual(response.status_code, 201, response.content)
        folder_id = response.json()["id"]

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="finance_view",
            folder_id=folder_id,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/warehouse_saved_query_folders/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()[0]["name"], "Finance")
        self.assertEqual(response.json()[0]["view_count"], 1)

    def test_delete_folder_deletes_views(self):
        folder = DataWarehouseSavedQueryFolder.objects.create(team=self.team, name="Deprecated", created_by=self.user)
        first_view = DataWarehouseSavedQuery.objects.create(team=self.team, name="deprecated_a", folder=folder)
        second_view = DataWarehouseSavedQuery.objects.create(team=self.team, name="deprecated_b", folder=folder)

        with patch(
            "products.data_warehouse.backend.logic.data_load.saved_query_service.delete_saved_query_schedule"
        ) as mock_delete_saved_query_schedule:
            response = self.client.delete(
                f"/api/environments/{self.team.id}/warehouse_saved_query_folders/{folder.id}/"
            )

        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(mock_delete_saved_query_schedule.call_count, 2)
        self.assertFalse(DataWarehouseSavedQueryFolder.objects.filter(id=folder.id).exists())

        first_view.refresh_from_db()
        second_view.refresh_from_db()
        self.assertTrue(first_view.deleted)
        self.assertTrue(second_view.deleted)

    def test_delete_folder_deletes_endpoint_views(self):
        folder = DataWarehouseSavedQueryFolder.objects.create(team=self.team, name="Endpoints", created_by=self.user)
        endpoint_view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="endpoint_view",
            folder=folder,
            origin=DataWarehouseSavedQuery.Origin.ENDPOINT,
        )

        with patch(
            "products.data_warehouse.backend.logic.data_load.saved_query_service.delete_saved_query_schedule"
        ) as mock_delete_saved_query_schedule:
            response = self.client.delete(
                f"/api/environments/{self.team.id}/warehouse_saved_query_folders/{folder.id}/"
            )

        self.assertEqual(response.status_code, 204, response.content)
        mock_delete_saved_query_schedule.assert_called_once()
        self.assertFalse(DataWarehouseSavedQueryFolder.objects.filter(id=folder.id).exists())

        endpoint_view.refresh_from_db()
        self.assertTrue(endpoint_view.deleted)

    def test_rename_folder(self):
        folder = DataWarehouseSavedQueryFolder.objects.create(team=self.team, name="Finance", created_by=self.user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_query_folders/{folder.id}/",
            {"name": "Revenue"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        folder.refresh_from_db()
        self.assertEqual(folder.name, "Revenue")

    def test_rename_folder_rejects_duplicate_name(self):
        DataWarehouseSavedQueryFolder.objects.create(team=self.team, name="Finance", created_by=self.user)
        folder = DataWarehouseSavedQueryFolder.objects.create(team=self.team, name="Revenue", created_by=self.user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_query_folders/{folder.id}/",
            {"name": "Finance"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("A folder with this name already exists.", str(response.json()))

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
        """Test that updating sync_frequency via PATCH only sets the interval"""
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

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
            {"sync_frequency": "24hour"},
        )

        self.assertEqual(response.status_code, 200)

        # Verify the interval was set
        updated_query = DataWarehouseSavedQuery.objects.get(id=saved_query["id"])
        self.assertEqual(updated_query.sync_frequency_interval, timedelta(hours=24))

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

        with (
            patch(
                "products.data_warehouse.backend.presentation.views.saved_query.saved_query_workflow_exists",
                return_value=True,
            ) as mock_workflow_exists,
            patch(
                "products.data_warehouse.backend.presentation.views.saved_query.pause_saved_query_schedule"
            ) as mock_pause_saved_query_schedule,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {"sync_frequency": "never"},
            )
            self.assertEqual(response.status_code, 200)
            saved_query_id = response.json()["id"]
            saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)
            mock_workflow_exists.assert_called_once_with(saved_query)
            mock_pause_saved_query_schedule.assert_called_once_with(saved_query)

    def _create_saved_query_for_frequency_tests(self) -> dict:
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
        return response.json()

    def _v2_flag_only(self, key, *args, **kwargs):
        return key == "data-modeling-backend-v2"

    @parameterized.expand(
        [
            ("24hour", timedelta(hours=24)),
            ("never", None),
        ]
    )
    def test_update_sync_frequency_on_tiered_v2_writes_target_through(
        self, sync_frequency: str, expected_target: timedelta | None
    ):
        from products.data_modeling.backend.logic.node_frequency import get_frequency_target, set_frequency_target
        from products.data_modeling.backend.models import Node

        saved_query = self._create_saved_query_for_frequency_tests()
        node = Node.objects.get(saved_query_id=saved_query["id"])
        set_frequency_target(node, timedelta(hours=12))
        reconcile_module = "products.data_modeling.backend.logic.schedule_reconcile"

        with (
            patch(
                "products.data_warehouse.backend.presentation.views.saved_query.posthoganalytics.feature_enabled",
                side_effect=self._v2_flag_only,
            ),
            patch(f"{reconcile_module}.tiered_schedules_enabled", return_value=True),
            patch(f"{reconcile_module}.maybe_reconcile_dag") as reconcile,
            patch(
                "products.data_warehouse.backend.presentation.views.saved_query.saved_query_workflow_exists"
            ) as v1_exists,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {"sync_frequency": sync_frequency},
            )

        self.assertEqual(response.status_code, 200, response.json())
        # the node target is the only store of frequency intent; the interval stays NULL
        updated = DataWarehouseSavedQuery.objects.get(id=saved_query["id"])
        self.assertIsNone(updated.sync_frequency_interval)
        node.refresh_from_db()
        self.assertEqual(get_frequency_target(node), expected_target)
        reconcile.assert_called_once()
        # a stale v1 schedule from a half-finished migration must not be revived by the PATCH
        v1_exists.assert_not_called()

    def test_update_sync_frequency_on_tiered_v2_rolls_back_invalid_target(self):
        from products.data_modeling.backend.logic.freshness import UnsatisfiableFrequencyError

        saved_query = self._create_saved_query_for_frequency_tests()
        reconcile_module = "products.data_modeling.backend.logic.schedule_reconcile"

        with (
            patch(
                "products.data_warehouse.backend.presentation.views.saved_query.posthoganalytics.feature_enabled",
                side_effect=self._v2_flag_only,
            ),
            patch(f"{reconcile_module}.tiered_schedules_enabled", return_value=True),
            patch(
                f"{reconcile_module}.apply_saved_query_frequency_target",
                side_effect=UnsatisfiableFrequencyError("target is fresher than its sources deliver"),
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {"sync_frequency": "15min"},
            )

        self.assertEqual(response.status_code, 400)
        # validation happens inside the transaction: the interval write rolls back with it
        updated = DataWarehouseSavedQuery.objects.get(id=saved_query["id"])
        self.assertIsNone(updated.sync_frequency_interval)

    def test_update_sync_frequency_on_untiered_v2_stays_blocked(self):
        saved_query = self._create_saved_query_for_frequency_tests()

        with (
            patch(
                "products.data_warehouse.backend.presentation.views.saved_query.posthoganalytics.feature_enabled",
                side_effect=self._v2_flag_only,
            ),
            patch(
                "products.data_modeling.backend.logic.schedule_reconcile.tiered_schedules_enabled",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {"sync_frequency": "24hour"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("managed by the DAG", response.json()["detail"])

    def test_sync_frequency_is_a_writable_field(self):
        # Regression: sync_frequency used to be a read-only SerializerMethodField, so it was
        # marked readOnly in the generated OpenAPI/MCP schemas and silently dropped from writes.
        from products.data_warehouse.backend.presentation.views.saved_query import DataWarehouseSavedQuerySerializer

        field = DataWarehouseSavedQuerySerializer().fields["sync_frequency"]
        self.assertFalse(field.read_only)

    def _create_saved_query(self) -> dict:
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
        return response.json()

    @parameterized.expand(
        [
            ("15min", "15min", timedelta(minutes=15)),
            ("6hour", "6hour", timedelta(hours=6)),
            ("1hour", "1hour", timedelta(hours=1)),
            ("30day", "30day", timedelta(days=30)),
            # Sub-15min cadences are deprecated for saved queries and clamped up to the "15min" floor.
            ("5min", "15min", timedelta(minutes=15)),
            ("1min", "15min", timedelta(minutes=15)),
        ]
    )
    def test_update_sync_frequency_round_trip(self, sent: str, expected_value: str, expected_interval: timedelta):
        saved_query = self._create_saved_query()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
            {"sync_frequency": sent},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["sync_frequency"], expected_value)

        updated_query = DataWarehouseSavedQuery.objects.get(id=saved_query["id"])
        self.assertEqual(updated_query.sync_frequency_interval, expected_interval)

    def test_update_sync_frequency_rejects_invalid_value(self):
        saved_query = self._create_saved_query()

        response = self.client.patch(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
            {"sync_frequency": "every_fortnight"},
        )
        self.assertEqual(response.status_code, 400, response.content)

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
        saved_query_id = response.json()["id"]
        saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)

        with patch(
            "products.data_warehouse.backend.logic.data_load.saved_query_service.delete_saved_query_schedule"
        ) as mock_delete_saved_query_schedule:
            response = self.client.delete(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}",
            )

            self.assertEqual(response.status_code, 204)
            mock_delete_saved_query_schedule.assert_called_once_with(saved_query)

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
                    "description": None,
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
            latest_detail = cast(dict[str, Any], activity_logs[0].detail)
            query_change = next(change for change in latest_detail["changes"] if change["field"] == "query")
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
            created_detail = cast(dict[str, Any], activity_logs[1].detail)
            query_change = next(change for change in created_detail["changes"] if change["field"] == "query")
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

    def test_update_concurrency_ignores_non_query_activity(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "sync_view",
                "query": {"kind": "HogQLQuery", "query": "select event as event from events LIMIT 100"},
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        saved_query = response.json()
        query_change_history_id = saved_query["latest_history_id"]
        self.assertIsNotNone(query_change_history_id)

        # A materialized view's sync/status transitions write newer activity logs that do not change
        # the query. They must not advance the optimistic-concurrency head.
        query_activity = ActivityLog.objects.get(id=query_change_history_id)
        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.team.organization_id,
            activity="sync_triggered",
            scope="DataWarehouseSavedQuery",
            item_id=str(saved_query["id"]),
            detail=Detail(changes=[]),
            created_at=query_activity.created_at + timedelta(minutes=1),
        )

        # The concurrency head still points at the last query edit, not the newer sync.
        get_response = self.client.get(f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}/")
        self.assertEqual(get_response.json()["latest_history_id"], query_change_history_id)

        # Saving again based on that head must succeed despite the newer sync activity.
        with patch.object(DataWarehouseSavedQuery, "get_columns") as mock_get_columns:
            mock_get_columns.return_value = {}
            update_response = self.client.patch(
                f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query['id']}",
                {
                    "query": {"kind": "HogQLQuery", "query": "select event as event from events LIMIT 10"},
                    "edited_history_id": query_change_history_id,
                },
            )
        self.assertEqual(update_response.status_code, 200, update_response.content)

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
                "products.data_warehouse.backend.logic.data_load.saved_query_service.delete_schedule"
            ) as mock_delete_schedule,
            patch("products.data_warehouse.backend.logic.data_load.saved_query_service.sync_connect"),
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

    def test_dependencies_no_dependencies(self):
        """Test dependencies endpoint returns zero counts for a view with no dependencies"""
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "simple_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201)
        saved_query_id = response.json()["id"]

        # Test dependencies endpoint
        response = self.client.get(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/dependencies",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["upstream_count"], 1)  # events
        self.assertEqual(data["downstream_count"], 0)  # No downstream dependencies

    def test_dependencies_with_upstream_and_downstream(self):
        """Test dependencies endpoint correctly counts immediate dependencies"""
        # Create parent view
        response_parent = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "parent_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response_parent.status_code, 201)
        parent_id = response_parent.json()["id"]

        # Create child view that depends on parent
        response_child = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "child_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event as event from parent_view LIMIT 50",
                },
            },
        )
        self.assertEqual(response_child.status_code, 201)
        child_id = response_child.json()["id"]

        # Create grandchild view that depends on child
        response_grandchild = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "grandchild_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event as event from child_view LIMIT 25",
                },
            },
        )
        self.assertEqual(response_grandchild.status_code, 201)
        grandchild_id = response_grandchild.json()["id"]

        # Test parent dependencies (should have downstream but no upstream saved queries)
        response = self.client.get(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{parent_id}/dependencies",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["upstream_count"], 1)  # events table
        self.assertEqual(data["downstream_count"], 1)  # child_view

        # Test child dependencies (should have both upstream and downstream)
        response = self.client.get(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{child_id}/dependencies",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["upstream_count"], 1)  # parent_view (only immediate parent)
        self.assertEqual(data["downstream_count"], 1)  # grandchild_view

        # Test grandchild dependencies (should have upstream but no downstream)
        response = self.client.get(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{grandchild_id}/dependencies",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["upstream_count"], 1)  # child_view (only immediate parent)
        self.assertEqual(data["downstream_count"], 0)  # No downstream

    def test_run_history_no_runs(self):
        """Test run_history endpoint returns empty array for a view with no runs"""
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "view_no_runs",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201)
        saved_query_id = response.json()["id"]

        # Test run_history endpoint
        response = self.client.get(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/run_history",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["run_history"], [])

    def test_run_history_with_runs(self):
        """Test run_history endpoint returns correct run history"""
        # Create a materialized view
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "materialized_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201)
        saved_query_id = response.json()["id"]
        saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)

        # Create multiple runs with different statuses
        from django.utils import timezone

        now = timezone.now()

        # Create 7 runs to test the limit of 5
        runs = []
        for i in range(7):
            status = DataModelingJob.Status.COMPLETED if i % 2 == 0 else DataModelingJob.Status.FAILED
            run = DataModelingJob.objects.create(
                team=self.team,
                saved_query=saved_query,
                status=status,
                last_run_at=now - timedelta(hours=i),
            )
            runs.append(run)

        # Test run_history endpoint
        response = self.client.get(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/run_history",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Should return only the 5 most recent runs
        self.assertEqual(len(data["run_history"]), 5)

        # Verify they are ordered by most recent first
        for i in range(len(data["run_history"])):
            expected_status = DataModelingJob.Status.COMPLETED if i % 2 == 0 else DataModelingJob.Status.FAILED
            self.assertEqual(data["run_history"][i]["status"], expected_status)
            self.assertIsNotNone(data["run_history"][i]["timestamp"])

        # Verify the most recent run is first
        most_recent_run = runs[0]
        self.assertEqual(data["run_history"][0]["status"], most_recent_run.status)

    def test_run_history_mixed_statuses(self):
        """Test run_history endpoint with various run statuses"""
        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "mixed_status_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": "select event as event from events LIMIT 100",
                },
            },
        )
        self.assertEqual(response.status_code, 201)
        saved_query_id = response.json()["id"]
        saved_query = DataWarehouseSavedQuery.objects.get(id=saved_query_id)

        from django.utils import timezone

        now = timezone.now()

        # Create runs with different statuses
        statuses = [
            DataModelingJob.Status.COMPLETED,
            DataModelingJob.Status.FAILED,
            DataModelingJob.Status.RUNNING,
            DataModelingJob.Status.CANCELLED,
        ]

        for i, status in enumerate(statuses):
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=saved_query,
                status=status,
                last_run_at=now - timedelta(hours=i),
            )

        # Test run_history endpoint
        response = self.client.get(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query_id}/run_history",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(len(data["run_history"]), 4)

        # Verify all different statuses are present
        returned_statuses = [run["status"] for run in data["run_history"]]
        self.assertIn("Completed", returned_statuses)
        self.assertIn("Failed", returned_statuses)
        self.assertIn("Running", returned_statuses)
        self.assertIn("Cancelled", returned_statuses)

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_materialize_and_revert_are_rate_limited(self, _rate_limit_enabled_mock):
        api_key = self.create_personal_api_key_with_scopes(["warehouse_view:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="rate_limit_test_view",
            query={"kind": "HogQLQuery", "query": "select event as event from events LIMIT 100"},
            created_by=self.user,
        )

        with (
            patch("products.data_warehouse.backend.logic.data_load.saved_query_service.sync_saved_query_workflow"),
            patch(
                "products.data_warehouse.backend.logic.data_load.saved_query_service.saved_query_workflow_exists",
                return_value=False,
            ),
        ):
            for action in ("materialize", "revert_materialization"):
                # First 5 requests should succeed (rate is 5/hour)
                for i in range(5):
                    response = self.client.post(
                        f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}/{action}",
                    )
                    assert response.status_code == 200, f"{action} request {i + 1} returned {response.status_code}"

                # 6th request should be throttled
                response = self.client.post(
                    f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}/{action}",
                )
                assert response.status_code == 429, f"{action} should be throttled but got {response.status_code}"

                # Clear the throttle cache so the next action starts fresh
                from django.core.cache import cache

                cache.clear()


class TestSavedQueryRunV2Aware(APIBaseTest):
    """The run action branches on the saved query's schedule version: materialize the backing node
    via the v2 workflow when its DAG is on a v2 schedule, otherwise trigger the v1 per-query
    schedule (which only exists for v1 saved queries).
    """

    def _make_saved_query_with_node(self, name: str) -> tuple[DataWarehouseSavedQuery, DAG, Node]:
        dag = DAG.objects.create(team=self.team, name=f"posthog_{self.team.id}")
        saved_query = DataWarehouseSavedQuery.objects.create(
            name=name,
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        node = Node.objects.create(
            team=self.team,
            dag=dag,
            saved_query=saved_query,
            type=NodeType.VIEW,
        )
        return saved_query, dag, node

    @patch("products.data_warehouse.backend.presentation.views.saved_query.trigger_saved_query_schedule")
    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    @patch("products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids")
    def test_run_on_v2_schedule_materializes_node_without_v1_trigger(
        self, mock_v2_dags, mock_sync_connect, mock_trigger
    ):
        saved_query, dag, _node = self._make_saved_query_with_node("v2_view")
        mock_v2_dags.return_value = {str(dag.id)}
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}/run/",
        )

        self.assertEqual(response.status_code, 200, response.content)
        mock_trigger.assert_not_called()
        mock_client.start_workflow.assert_called_once()
        self.assertEqual(mock_client.start_workflow.call_args[0][0], "data-modeling-materialize-view")

    @patch("products.data_warehouse.backend.presentation.views.saved_query.trigger_saved_query_schedule")
    @patch("products.data_modeling.backend.logic.node_materialization.sync_connect")
    @patch("products.data_modeling.backend.logic.node_materialization.get_v2_saved_query_ids")
    def test_run_on_v2_without_backing_node_does_not_fall_back_to_v1(
        self, mock_v2_ids, mock_sync_connect, mock_trigger
    ):
        # v2 is confirmed but no backing node exists: nothing is materialized, and it must not fall
        # back to the v1 schedule trigger, which a v2 saved query has no schedule for.
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="orphan_view", team=self.team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
        )
        mock_v2_ids.return_value = {saved_query.id}
        mock_client = AsyncMock()
        mock_sync_connect.return_value = mock_client

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}/run/",
        )

        self.assertEqual(response.status_code, 200, response.content)
        mock_trigger.assert_not_called()
        mock_client.start_workflow.assert_not_called()

    @patch("products.data_warehouse.backend.presentation.views.saved_query.trigger_saved_query_schedule")
    @patch("products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids")
    def test_run_on_v1_triggers_saved_query_schedule(self, mock_v2_dags, mock_trigger):
        saved_query, _dag, _node = self._make_saved_query_with_node("v1_view")
        mock_v2_dags.return_value = set()

        response = self.client.post(
            f"/api/environments/{self.team.id}/warehouse_saved_queries/{saved_query.id}/run/",
        )

        self.assertEqual(response.status_code, 200, response.content)
        mock_trigger.assert_called_once()


class TestSavedQueryDescription(APIBaseTest):
    def _base(self) -> str:
        return f"/api/environments/{self.team.id}/warehouse_saved_queries/"

    def _create(self, name: str = "revenue_view", description: str | None = None) -> dict:
        payload: dict[str, Any] = {"name": name, "query": {"kind": "HogQLQuery", "query": "SELECT 1 AS amount"}}
        if description is not None:
            payload["description"] = description
        response = self.client.post(self._base(), payload)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def _view_level_annotation(self, view_id: str) -> DataWarehouseSavedQueryColumnAnnotation | None:
        return (
            DataWarehouseSavedQueryColumnAnnotation.objects.for_team(self.team.id)
            .filter(saved_query_id=view_id, column_name="")
            .first()
        )

    def test_create_with_description_writes_user_edited_annotation_and_returns_it(self):
        view = self._create(description="Revenue per order, one row per order.")
        assert view["description"] == "Revenue per order, one row per order."
        annotation = self._view_level_annotation(view["id"])
        assert annotation is not None
        assert annotation.description == "Revenue per order, one row per order."
        assert annotation.is_user_edited is True

    def test_get_returns_view_description(self):
        view = self._create(description="What this view means.")
        response = self.client.get(f"{self._base()}{view['id']}/")
        assert response.status_code == 200, response.content
        assert response.json()["description"] == "What this view means."

    def test_update_description_only_upserts_and_is_returned(self):
        view = self._create()
        assert view["description"] is None
        patch = self.client.patch(f"{self._base()}{view['id']}/", {"description": "Set via update."})
        assert patch.status_code == 200, patch.content
        assert patch.json()["description"] == "Set via update."
        annotation = self._view_level_annotation(view["id"])
        assert annotation is not None and annotation.is_user_edited is True
        get = self.client.get(f"{self._base()}{view['id']}/")
        assert get.json()["description"] == "Set via update."

    def test_update_empty_description_clears_it(self):
        view = self._create(description="Initial.")
        patch = self.client.patch(f"{self._base()}{view['id']}/", {"description": ""})
        assert patch.status_code == 200, patch.content
        assert patch.json()["description"] is None
        assert self._view_level_annotation(view["id"]) is None

    def test_update_without_description_leaves_it_untouched(self):
        view = self._create(description="Keep me.")
        patch = self.client.patch(f"{self._base()}{view['id']}/", {"name": "renamed_view"})
        assert patch.status_code == 200, patch.content
        assert patch.json()["description"] == "Keep me."

    def test_per_column_description_round_trips_into_columns(self):
        view = self._create()
        column_name = self.client.get(f"{self._base()}{view['id']}/").json()["columns"][0]["name"]
        annotate = self.client.post(
            f"/api/projects/{self.team.id}/saved_query_column_annotations/",
            {"saved_query": view["id"], "column_name": column_name, "description": "The order amount in cents."},
        )
        assert annotate.status_code == 201, annotate.content
        columns = self.client.get(f"{self._base()}{view['id']}/").json()["columns"]
        described = {c["name"]: c.get("description") for c in columns}
        assert described[column_name] == "The order amount in cents."

    def test_list_includes_view_description(self):
        self._create(name="described_view", description="Listed description.")
        results = self.client.get(self._base()).json()["results"]
        described = {v["name"]: v.get("description") for v in results}
        assert described["described_view"] == "Listed description."
