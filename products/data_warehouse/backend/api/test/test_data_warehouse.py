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

        assert response.status_code == 200
        assert data["tracked_billing_rows"] == 100
        assert data["pending_billing_rows"] == 50
        assert data["total_rows"] == 150

    @patch("products.data_warehouse.backend.api.data_warehouse.BillingManager")
    @patch("products.data_warehouse.backend.api.data_warehouse.get_cached_instance_license")
    def test_billing_exception_returns_500(self, mock_license, mock_billing_manager):
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/total_rows_stats"
        mock_billing_manager.return_value.get_billing.side_effect = Exception("Billing service unavailable")

        response = self.client.get(endpoint)
        data = response.json()

        assert response.status_code == 500
        assert data["error"] == "An error occurred retrieving billing information"

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

        assert response.status_code == 200
        assert data["days"] == 7
        assert data["total_jobs"] == 3
        assert data["successful_jobs"] == 2
        assert data["failed_jobs"] == 1
        assert data["external_data_jobs"]["total"] == 2
        assert data["external_data_jobs"]["successful"] == 1
        assert data["external_data_jobs"]["failed"] == 1
        assert data["modeling_jobs"]["total"] == 1
        assert data["modeling_jobs"]["successful"] == 1
        assert data["modeling_jobs"]["failed"] == 0
        assert "breakdown" in data
        assert "cutoff_time" in data

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

        assert response.status_code == 200
        assert data["days"] == 1
        assert data["total_jobs"] == 1
        assert len(data["breakdown"]) == 24

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

        assert response.status_code == 200
        assert data["days"] == 30
        assert data["total_jobs"] == 2
        assert data["successful_jobs"] == 1
        assert data["failed_jobs"] == 1
        assert len(data["breakdown"]) == 30

    def test_job_stats_invalid_days_parameter(self):
        """Test job_stats endpoint rejects invalid days parameter"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/job_stats"

        response = self.client.get(f"{endpoint}?days=14")
        assert response.status_code == 400
        assert "Invalid days parameter" in response.json()["error"]

        response = self.client.get(f"{endpoint}?days=invalid")
        assert response.status_code == 400
        assert "Invalid days parameter" in response.json()["error"]

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

        assert response.status_code == 200
        assert data["total_jobs"] == 1
        assert data["successful_jobs"] == 1

    def test_job_stats_empty_state(self):
        """Test job_stats endpoint with no jobs"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/job_stats"

        response = self.client.get(endpoint)
        data = response.json()

        assert response.status_code == 200
        assert data["total_jobs"] == 0
        assert data["successful_jobs"] == 0
        assert data["failed_jobs"] == 0
        assert data["external_data_jobs"]["total"] == 0
        assert data["modeling_jobs"]["total"] == 0
        assert "breakdown" in data

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

        assert response.status_code == 200
        assert data["total_jobs"] == 3

        today_key = str(today_start)
        assert today_key in data["breakdown"]
        assert data["breakdown"][today_key]["successful"] == 2
        assert data["breakdown"][today_key]["failed"] == 1

    def test_running_activity_returns_only_running_jobs(self):
        """Test running_activity endpoint returns only running jobs"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/running_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Running"
        )
        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=200, status="Completed"
        )
        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=300, status="Failed"
        )

        DataModelingJob.objects.create(team=self.team, status="Running", rows_materialized=50)
        DataModelingJob.objects.create(team=self.team, status="Completed", rows_materialized=75)

        response = self.client.get(endpoint)
        data = response.json()

        assert response.status_code == 200
        assert len(data["results"]) == 2

        statuses = [activity["status"] for activity in data["results"]]
        assert all(status == "Running" for status in statuses)

        types = [activity["type"] for activity in data["results"]]
        assert "Stripe" in types
        assert "Materialized view" in types

    def test_completed_activity_returns_only_completed_jobs(self):
        """Test completed_activity endpoint returns only jobs with status 'Completed'"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/completed_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Running"
        )
        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=200, status="Completed"
        )
        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=300, status="Failed"
        )

        DataModelingJob.objects.create(team=self.team, status="Running", rows_materialized=50)
        DataModelingJob.objects.create(team=self.team, status="Completed", rows_materialized=75)
        DataModelingJob.objects.create(team=self.team, status="Failed", rows_materialized=25)

        response = self.client.get(endpoint)
        data = response.json()

        assert response.status_code == 200
        assert len(data["results"]) == 2

        statuses = [activity["status"] for activity in data["results"]]
        assert all(status == "Completed" for status in statuses)

        types = [activity["type"] for activity in data["results"]]
        assert types.count("Stripe") == 1
        assert types.count("Materialized view") == 1

    def test_running_activity_pagination(self):
        """Test running_activity endpoint pagination"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/running_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        for i in range(5):
            ExternalDataJob.objects.create(
                pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100 + i, status="Running"
            )

        response = self.client.get(f"{endpoint}?limit=2&offset=0")
        first_page_data = response.json()

        assert response.status_code == 200
        assert len(first_page_data["results"]) == 2
        assert first_page_data["next"] is not None

        response = self.client.get(f"{endpoint}?limit=2&offset=2")
        second_page_data = response.json()

        assert response.status_code == 200
        assert len(second_page_data["results"]) == 2

    def test_completed_activity_pagination(self):
        """Test completed_activity endpoint pagination"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/completed_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        # Create 7 completed jobs and 3 failed jobs to test filtering and pagination
        for i in range(10):
            status = "Completed" if i < 7 else "Failed"
            ExternalDataJob.objects.create(
                pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100 + i, status=status
            )

        response = self.client.get(f"{endpoint}?limit=3&offset=0")
        first_page_data = response.json()

        assert response.status_code == 200
        assert len(first_page_data["results"]) == 3
        assert first_page_data["next"] is not None

        response = self.client.get(f"{endpoint}?limit=3&offset=3")
        second_page_data = response.json()

        assert response.status_code == 200
        assert len(second_page_data["results"]) == 3

    def test_running_activity_cutoff_days(self):
        """Test running_activity endpoint respects cutoff_days parameter"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/running_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Running"
        )

        old_job = ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=200, status="Running"
        )
        ExternalDataJob.objects.filter(pk=old_job.pk).update(created_at=timezone.now() - timedelta(days=35))

        response = self.client.get(f"{endpoint}?cutoff_days=30")
        data = response.json()

        assert response.status_code == 200
        assert len(data["results"]) == 1
        assert data["results"][0]["rows"] == 100

        response = self.client.get(f"{endpoint}?cutoff_days=40")
        data = response.json()

        assert response.status_code == 200
        assert len(data["results"]) == 2

    def test_completed_activity_cutoff_days(self):
        """Test completed_activity endpoint respects cutoff_days parameter"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/completed_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Completed"
        )

        old_job = ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=200, status="Failed"
        )
        ExternalDataJob.objects.filter(pk=old_job.pk).update(created_at=timezone.now() - timedelta(days=35))

        response = self.client.get(f"{endpoint}?cutoff_days=30")
        data = response.json()

        assert response.status_code == 200
        assert len(data["results"]) == 1
        assert data["results"][0]["rows"] == 100

    def test_running_activity_empty_state(self):
        """Test running_activity endpoint with no running jobs"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/running_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Completed"
        )

        response = self.client.get(endpoint)
        data = response.json()

        assert response.status_code == 200
        assert len(data["results"]) == 0

    def test_completed_activity_empty_state(self):
        """Test completed_activity endpoint with no completed jobs"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/completed_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)

        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, status="Running"
        )

        response = self.client.get(endpoint)
        data = response.json()

        assert response.status_code == 200
        assert len(data["results"]) == 0

    def test_running_activity_ordering(self):
        """Test running_activity endpoint returns results ordered by created_at DESC"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/running_activity"

        for i in range(3):
            DataModelingJob.objects.create(team=self.team, status="Running", rows_materialized=100 + i)

        response = self.client.get(endpoint)
        data = response.json()

        assert response.status_code == 200
        created_dates = [result["created_at"] for result in data["results"]]
        assert created_dates == sorted(created_dates, reverse=True)

    def test_completed_activity_ordering(self):
        """Test completed_activity endpoint returns results ordered by created_at DESC"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/completed_activity"

        for i in range(3):
            status = "Completed" if i % 2 == 0 else "Failed"
            DataModelingJob.objects.create(team=self.team, status=status, rows_materialized=100 + i)

        response = self.client.get(endpoint)
        data = response.json()

        assert response.status_code == 200
        created_dates = [result["created_at"] for result in data["results"]]
        assert created_dates == sorted(created_dates, reverse=True)

    def test_running_activity_invalid_parameters(self):
        """Test running_activity endpoint rejects invalid parameters"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/running_activity"

        response = self.client.get(f"{endpoint}?limit=invalid")
        assert response.status_code == 400

        response = self.client.get(f"{endpoint}?offset=invalid")
        assert response.status_code == 400

        response = self.client.get(f"{endpoint}?cutoff_days=invalid")
        assert response.status_code == 400

    def test_completed_activity_invalid_parameters(self):
        """Test completed_activity endpoint rejects invalid parameters"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/completed_activity"

        response = self.client.get(f"{endpoint}?limit=invalid")
        assert response.status_code == 400

        response = self.client.get(f"{endpoint}?offset=invalid")
        assert response.status_code == 400

        response = self.client.get(f"{endpoint}?cutoff_days=invalid")
        assert response.status_code == 400
