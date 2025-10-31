from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.models.data_modeling_job import DataModelingJob


class TestDataWarehouseAPI(APIBaseTest):
    @patch("products.data_warehouse.backend.api.data_warehouse.BillingManager")
    @patch("products.data_warehouse.backend.api.data_warehouse.get_cached_instance_license")
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

    @patch("products.data_warehouse.backend.api.data_warehouse.BillingManager")
    @patch("products.data_warehouse.backend.api.data_warehouse.get_cached_instance_license")
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

    def test_job_stats_default_7_days(self):
        """Test job_stats endpoint with default 7-day period"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/job_stats"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=100,
            finished_at=timezone.now(),
        )

        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            status=ExternalDataJob.Status.FAILED,
            rows_synced=0,
            finished_at=timezone.now(),
        )

        DataModelingJob.objects.create(team=self.team, status=DataModelingJob.Status.COMPLETED, rows_materialized=50)

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["days"], 7)
        self.assertEqual(data["total_jobs"], 3)
        self.assertEqual(data["successful_jobs"], 2)
        self.assertEqual(data["failed_jobs"], 1)
        self.assertEqual(data["external_data_jobs"]["total"], 2)
        self.assertEqual(data["external_data_jobs"]["successful"], 1)
        self.assertEqual(data["external_data_jobs"]["failed"], 1)
        self.assertEqual(data["modeling_jobs"]["total"], 1)
        self.assertEqual(data["modeling_jobs"]["successful"], 1)
        self.assertEqual(data["modeling_jobs"]["failed"], 0)
        self.assertIn("breakdown", data)
        self.assertIn("cutoff_time", data)

    def test_job_stats_1_day_hourly_breakdown(self):
        """Test job_stats endpoint with 1-day period returns hourly breakdown"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/job_stats"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=100,
            finished_at=timezone.now(),
        )

        with self.assertNumQueries(14):
            response = self.client.get(f"{endpoint}?days=1")
            data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["days"], 1)
        self.assertEqual(data["total_jobs"], 1)
        self.assertEqual(len(data["breakdown"]), 24)

    def test_job_stats_30_days(self):
        """Test job_stats endpoint with 30-day period"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/job_stats"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=100,
            finished_at=timezone.now() - timedelta(days=5),
        )

        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            status=ExternalDataJob.Status.FAILED,
            rows_synced=0,
            finished_at=timezone.now() - timedelta(days=10),
        )

        with self.assertNumQueries(14):
            response = self.client.get(f"{endpoint}?days=30")
            data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["days"], 30)
        self.assertEqual(data["total_jobs"], 2)
        self.assertEqual(data["successful_jobs"], 1)
        self.assertEqual(data["failed_jobs"], 1)
        self.assertEqual(len(data["breakdown"]), 30)

    def test_job_stats_invalid_days_parameter(self):
        """Test job_stats endpoint rejects invalid days parameter"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/job_stats"

        response = self.client.get(f"{endpoint}?days=14")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid days parameter", response.json()["error"])

        response = self.client.get(f"{endpoint}?days=invalid")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid days parameter", response.json()["error"])

    def test_job_stats_excludes_old_jobs(self):
        """Test job_stats endpoint only includes jobs within the specified time range"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/job_stats"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=100,
            finished_at=timezone.now() - timedelta(days=3),
        )

        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=200,
            finished_at=timezone.now() - timedelta(days=10),
        )

        response = self.client.get(f"{endpoint}?days=7")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["total_jobs"], 1)
        self.assertEqual(data["successful_jobs"], 1)

    def test_job_stats_empty_state(self):
        """Test job_stats endpoint with no jobs"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/job_stats"

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["total_jobs"], 0)
        self.assertEqual(data["successful_jobs"], 0)
        self.assertEqual(data["failed_jobs"], 0)
        self.assertEqual(data["external_data_jobs"]["total"], 0)
        self.assertEqual(data["modeling_jobs"]["total"], 0)
        self.assertIn("breakdown", data)

    def test_job_stats_breakdown_aggregation(self):
        """Test job_stats breakdown correctly aggregates jobs by time period"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/job_stats"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        today_start = timezone.now().date()

        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=100,
            finished_at=today_start + timedelta(hours=2),
        )

        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            schema=schema,
            team=self.team,
            status=ExternalDataJob.Status.FAILED,
            rows_synced=0,
            finished_at=today_start + timedelta(hours=3),
        )

        modeling_job = DataModelingJob.objects.create(
            team=self.team, status=DataModelingJob.Status.COMPLETED, rows_materialized=50
        )
        DataModelingJob.objects.filter(pk=modeling_job.pk).update(created_at=today_start + timedelta(hours=4))

        with self.assertNumQueries(14):
            response = self.client.get(f"{endpoint}?days=7")
            data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["total_jobs"], 3)

        today_key = str(today_start)
        self.assertIn(today_key, data["breakdown"])
        self.assertEqual(data["breakdown"][today_key]["successful"], 2)
        self.assertEqual(data["breakdown"][today_key]["failed"], 1)
