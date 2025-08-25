from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from posthog.warehouse.models.data_modeling_job import DataModelingJob


class TestDataWarehouseAPI(APIBaseTest):
    @patch("posthog.warehouse.api.data_warehouse.BillingManager")
    @patch("posthog.warehouse.api.data_warehouse.get_cached_instance_license")
    def test_basic_calculation_with_billing_data(self, mock_license, mock_billing_manager):
        """trackedBillingRows from billing; pending = db_total - tracked; totalRows = tracked + pending"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/total_rows_stats"

        mock_billing_manager.return_value.get_billing.return_value = {
            "billing_period": {
                "current_period_start": "2023-08-01T00:00:00Z",
                "current_period_end": "2023-09-01T00:00:00Z",
                "interval": "month",
            },
            "usage_summary": {"rows_synced": {"usage": 100}},
        }

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="test", team=self.team, source=source)

        job = ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            rows_synced=150,
            billable=True,
        )
        ExternalDataJob.objects.filter(pk=job.pk).update(created_at=datetime(2023, 8, 15, tzinfo=UTC))

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["tracked_billing_rows"], 100)
        self.assertEqual(data["pending_billing_rows"], 50)
        self.assertEqual(data["total_rows"], 150)

    @patch("posthog.warehouse.api.data_warehouse.BillingManager")
    @patch("posthog.warehouse.api.data_warehouse.get_cached_instance_license")
    def test_billing_exception_returns_500(self, mock_license, mock_billing_manager):
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/total_rows_stats"
        mock_billing_manager.return_value.get_billing.side_effect = Exception("Billing service unavailable")

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(data["error"], "An error occurred retrieving billing information")

    def test_recent_activity_includes_external_jobs_and_modeling_jobs(self):
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)
        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Completed"
        )
        DataModelingJob.objects.create(team=self.team, status="Running", rows_materialized=50)

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["results"]), 2)

        types = [activity["type"] for activity in data["results"]]
        self.assertIn("Stripe", types)
        self.assertIn("Materialized view", types)

    def test_recent_activity_pagination(self):
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        for i in range(5):
            ExternalDataJob.objects.create(
                pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100 + i, status="Completed"
            )

        response = self.client.get(f"{endpoint}?limit=2&offset=0")
        first_page_data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(first_page_data["results"]), 2)
        first_page_ids = {result["id"] for result in first_page_data["results"]}

        response = self.client.get(f"{endpoint}?limit=3&offset=2")
        second_page_data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(second_page_data["results"]), 3)

        second_page_ids = {result["id"] for result in second_page_data["results"]}
        self.assertFalse(
            first_page_ids.intersection(second_page_ids), "Second page should contain different results than first page"
        )

        all_ids = first_page_ids.union(second_page_ids)
        self.assertEqual(len(all_ids), 5, "Total unique results should equal number of created jobs")

        all_results_response = self.client.get(endpoint)
        all_results = all_results_response.json()["results"]
        created_dates = [result["created_at"] for result in all_results]
        self.assertEqual(
            created_dates, sorted(created_dates, reverse=True), "Results should be ordered by created_at DESC"
        )

    def test_recent_activity_edge_cases(self):
        """Test empty states and mixed pagination"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        response = self.client.get(endpoint)
        self.assertEqual(len(response.json()["results"]), 0)

        DataModelingJob.objects.create(team=self.team, status="Running", rows_materialized=50)
        response = self.client.get(endpoint)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["type"], "Materialized view")

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="test", team=self.team, source=source)
        for _ in range(3):
            ExternalDataJob.objects.create(
                pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Completed"
            )

        response = self.client.get(endpoint)
        data = response.json()
        self.assertEqual(len(data["results"]), 4)
        types = [r["type"] for r in data["results"]]
        self.assertIn("Stripe", types)
        self.assertIn("Materialized view", types)
