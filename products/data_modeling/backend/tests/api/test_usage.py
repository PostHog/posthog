from datetime import UTC, datetime, timedelta
from uuid import UUID

import time_machine

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team

from products.data_modeling.backend.models.data_modeling_job import DataModelingJob
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.presentation.views.usage import ModelUsageQuerySerializer
from products.warehouse_sources.backend.facade.testing import WarehouseAccessControlTestMixin


class TestModelUsageValidation(SimpleTestCase):
    @parameterized.expand([("days", 0), ("days", 91), ("page", 0), ("page_size", 101)])
    def test_rejects_out_of_bounds(self, field: str, value: int) -> None:
        serializer = ModelUsageQuerySerializer(data={field: value})
        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)


@time_machine.travel("2026-10-16T12:00:00Z", tick=False)
class TestModelUsage(WarehouseAccessControlTestMixin):
    resource = "warehouse_objects"

    def test_usage_is_scoped_and_preserves_unknown_cost(self) -> None:
        model = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="daily_orders", query={"kind": "HogQLQuery", "query": "SELECT 1"}
        )
        finished = datetime(2026, 10, 15, 20, tzinfo=UTC)
        measured = {
            "read_bytes": 1024,
            "read_rows": 100,
            "cpu_microseconds": 2_000_000,
            "query_count": 3,
            "usage_updated_at": finished,
        }
        base = {"team": self.team, "saved_query": model, "status": "Completed", "last_run_at": finished}
        DataModelingJob.objects.create(**base, **measured)
        DataModelingJob.objects.create(**{**base, "status": "Failed"})
        DataModelingJob.objects.create(**{**base, "status": "Running"}, **measured)
        DataModelingJob.objects.create(**{**base, "engine": "managed_warehouse"}, **measured)
        DataModelingJob.objects.create(**{**base, "last_run_at": finished + timedelta(days=1)}, **measured)
        other_team = Team.objects.create(organization=self.organization)
        DataModelingJob.objects.create(team=other_team, status="Completed", last_run_at=finished, **measured)
        result = self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/", {"days": 7})
        self.assertEqual(result.status_code, 200, result.content)
        data = result.json()
        self.assertEqual(
            data["overview"],
            {
                "runs": 2,
                "measured_runs": 1,
                "read_bytes": 1024,
                "read_rows": 100,
                "cpu_microseconds": 2_000_000,
                "query_count": 3,
            },
        )
        self.assertEqual(len(data["trends"]), 7)
        self.assertIsNone(data["trends"][0]["read_bytes"])
        self.assertEqual(data["trends"][-1]["runs"], 2)
        self.assertEqual(data["models"][0]["name"], "daily_orders")
        self.assertEqual(data["count"], 1)
        invalid = self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/", {"days": 91})
        self.assertEqual(invalid.status_code, 400)

    def test_model_breakdown_paginates_without_changing_totals(self) -> None:
        finished = datetime(2026, 10, 15, 20, tzinfo=UTC)
        model_ids = []
        for index, value in enumerate([0, 1000, 1000, None]):
            model = DataWarehouseSavedQuery.objects.create(
                id=UUID(int=index + 1),
                team=self.team,
                name=f"model_{index}",
                query={"kind": "HogQLQuery", "query": "SELECT 1"},
                deleted=index == 1,
            )
            model_ids.append(str(model.id))
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=model,
                status="Completed",
                last_run_at=finished,
                read_bytes=value,
                usage_updated_at=finished if value is not None else None,
            )
        results = [
            self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/", {"page": page, "page_size": 1}).json()
            for page in [1, 2, 3, 4]
        ]
        self.assertEqual([data["models"][0]["read_bytes"] for data in results], [1000, 1000, 0, None])
        self.assertEqual(
            [data["models"][0]["saved_query_id"] for data in results],
            [model_ids[index] for index in [1, 2, 0, 3]],
        )
        self.assertTrue(results[0]["models"][0]["deleted"])
        self.assertEqual([data["overview"]["read_bytes"] for data in results], [2000] * 4)
        self.assertEqual([data["count"] for data in results], [4] * 4)

    def test_denies_warehouse_access(self) -> None:
        self._create_project_default(access_level="none")
        self.client.force_login(self.no_access_user)
        result = self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/")
        self.assertEqual(result.status_code, 403)

    @parameterized.expand([(False,), (True,)])
    def test_usage_totals_follow_saved_query_access(self, explicit_grant: bool) -> None:
        finished = datetime(2026, 10, 15, 20, tzinfo=UTC)
        visible = DataWarehouseSavedQuery.objects.create(team=self.team, name="visible_model")
        restricted = DataWarehouseSavedQuery.objects.create(team=self.team, name="restricted_model")
        if explicit_grant:
            self._create_project_default(access_level="none")
            self._create_access_control(
                self.viewer_user, resource="warehouse_view", resource_id=str(visible.id), access_level="viewer"
            )
        self._create_access_control(
            self.viewer_user, resource="warehouse_view", resource_id=str(restricted.id), access_level="none"
        )
        for model, read_bytes in [(visible, 100), (restricted, 900)]:
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=model,
                status="Completed",
                last_run_at=finished,
                read_bytes=read_bytes,
                usage_updated_at=finished,
            )
        self.client.force_login(self.viewer_user)
        result = self.client.get(f"/api/projects/{self.team.id}/data_modeling_usage/")
        self.assertEqual(result.status_code, 200, result.content)
        data = result.json()
        self.assertEqual(data["overview"]["read_bytes"], 100)
        self.assertEqual(data["overview"]["runs"], 1)
        self.assertEqual(data["trends"][-1]["read_bytes"], 100)
        self.assertEqual(data["count"], 1)
        self.assertEqual([row["saved_query_id"] for row in data["models"]], [str(visible.id)])
