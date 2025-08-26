from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from posthog.warehouse.models.data_modeling_job import DataModelingJob


class TestDataWarehouseAPI(APIBaseTest):
    def _setup_breakdown_test_data(self, mock_billing_manager):
        """Helper to setup common test data for breakdown tests"""
        mock_billing_manager.return_value.get_billing.return_value = {
            "billing_period": {
                "current_period_start": "2023-08-01T00:00:00Z",
                "current_period_end": "2023-09-01T00:00:00Z",
            }
        }
        source = ExternalDataSource.objects.create(
            source_id="test", connection_id="conn", destination_id="dest", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)
        return source, schema

    def _create_job_with_date(self, source, schema, rows_synced, date, status="Completed"):
        """Helper to create a job and set its created_at date"""
        job = ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=rows_synced, status=status
        )
        ExternalDataJob.objects.filter(pk=job.pk).update(created_at=date)
        return job

    def _create_test_source_and_schema(self, source_type="Stripe", schema_name="test"):
        """Helper to create test source and schema"""
        source = ExternalDataSource.objects.create(
            source_id="test-id",
            connection_id="conn-id",
            destination_id="dest-id",
            team=self.team,
            source_type=source_type,
        )
        schema = ExternalDataSchema.objects.create(name=schema_name, team=self.team, source=source)
        return source, schema

    @patch("posthog.warehouse.api.data_warehouse.BillingManager")
    @patch("posthog.warehouse.api.data_warehouse.get_cached_instance_license")
    def test_basic_calculation_with_billing_data(self, mock_license, mock_billing_manager):
        """trackedBillingRows from billing; pending = db_total - tracked; totalRows = tracked + pending"""

        mock_billing_manager.return_value.get_billing.return_value = {
            "billing_period": {
                "current_period_start": "2023-08-01T00:00:00Z",
                "current_period_end": "2023-09-01T00:00:00Z",
                "interval": "month",
            },
            "usage_summary": {"rows_synced": {"usage": 100}},
        }

        source, schema = self._create_test_source_and_schema()

        job = ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=150, billable=True
        )
        ExternalDataJob.objects.filter(pk=job.pk).update(created_at=datetime(2023, 8, 15, tzinfo=UTC))

        response = self.client.get(f"/api/projects/{self.team.id}/data_warehouse/total_rows_stats")
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
        source, schema = self._create_test_source_and_schema(schema_name="customers")
        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Completed"
        )
        DataModelingJob.objects.create(team=self.team, status="Running", rows_materialized=50)

        response = self.client.get(f"/api/projects/{self.team.id}/data_warehouse/recent_activity")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["results"]), 2)
        types = [activity["type"] for activity in data["results"]]
        self.assertIn("Stripe", types)
        self.assertIn("Materialized view", types)

    def test_recent_activity_pagination(self):
        source, schema = self._create_test_source_and_schema(schema_name="customers")

        for i in range(5):
            ExternalDataJob.objects.create(
                pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100 + i, status="Completed"
            )

        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        first_page = self.client.get(f"{endpoint}?limit=2&offset=0").json()
        second_page = self.client.get(f"{endpoint}?limit=3&offset=2").json()

        self.assertEqual(len(first_page["results"]), 2)
        self.assertEqual(len(second_page["results"]), 3)

        first_ids = {r["id"] for r in first_page["results"]}
        second_ids = {r["id"] for r in second_page["results"]}
        self.assertFalse(first_ids.intersection(second_ids))
        self.assertEqual(len(first_ids.union(second_ids)), 5)

    def test_recent_activity_edge_cases(self):
        """Test empty states and mixed pagination"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        # Test empty state
        self.assertEqual(len(self.client.get(endpoint).json()["results"]), 0)

        # Test with modeling job only
        DataModelingJob.objects.create(team=self.team, status="Running", rows_materialized=50)
        data = self.client.get(endpoint).json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["type"], "Materialized view")

        # Test with mixed jobs
        source, schema = self._create_test_source_and_schema()
        for _ in range(3):
            ExternalDataJob.objects.create(
                pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Completed"
            )

        data = self.client.get(endpoint).json()
        self.assertEqual(len(data["results"]), 4)
        types = [r["type"] for r in data["results"]]
        self.assertIn("Stripe", types)
        self.assertIn("Materialized view", types)

    @patch("posthog.warehouse.api.data_warehouse.BillingManager")
    @patch("posthog.warehouse.api.data_warehouse.get_cached_instance_license")
    def test_breakdown_of_rows_synced_by_day_in_billing_period(self, mock_license, mock_billing_manager):
        """Test daily breakdown groups jobs by date and includes run details"""
        source, schema = self._setup_breakdown_test_data(mock_billing_manager)
        self._create_job_with_date(source, schema, 100, datetime(2023, 8, 15, tzinfo=UTC))

        response = self.client.get(
            f"/api/projects/{self.team.id}/data_warehouse/breakdown_of_rows_synced_by_day_in_billing_period"
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["breakdown_of_rows_by_day"]), 1)
        self.assertEqual(data["breakdown_of_rows_by_day"][0]["rows_synced"], 100)
        self.assertEqual(len(data["breakdown_of_rows_by_day"][0]["runs"]), 1)

    @patch("posthog.warehouse.api.data_warehouse.BillingManager")
    @patch("posthog.warehouse.api.data_warehouse.get_cached_instance_license")
    def test_breakdown_excludes_jobs_outside_billing_period(self, mock_license, mock_billing_manager):
        """Test jobs outside billing period are excluded"""
        source, schema = self._setup_breakdown_test_data(mock_billing_manager)

        self._create_job_with_date(source, schema, 100, datetime(2023, 8, 15, tzinfo=UTC))  # Inside period
        self._create_job_with_date(source, schema, 200, datetime(2023, 7, 30, tzinfo=UTC))  # Outside period

        response = self.client.get(
            f"/api/projects/{self.team.id}/data_warehouse/breakdown_of_rows_synced_by_day_in_billing_period"
        )
        data = response.json()

        self.assertEqual(len(data["breakdown_of_rows_by_day"]), 1)  # Only 1 day, not 2
        self.assertEqual(data["breakdown_of_rows_by_day"][0]["rows_synced"], 100)  # Only inside job
