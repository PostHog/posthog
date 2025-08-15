from unittest.mock import patch
from datetime import datetime, UTC
from posthog.test.base import APIBaseTest
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
            source_id="test-id",
            connection_id="conn-id",
            destination_id="dest-id",
            team=self.team,
            source_type="Stripe",
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
        self.assertEqual(data["trackedBillingRows"], 100)
        self.assertEqual(data["pendingBillingRows"], 50)
        self.assertEqual(data["totalRows"], 150)

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
        """Test recent activity endpoint returns both external data jobs and modeling jobs"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source)
        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=100, billable=True, status="Completed"
        )

        DataModelingJob.objects.create(team=self.team, status="Running", rows_materialized=50)

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["activities"]), 2)
        self.assertEqual(data["total_count"], 2)

        external_activity = next(a for a in data["activities"] if a["type"] == "Stripe")
        self.assertEqual(external_activity["name"], "customers")
        self.assertEqual(external_activity["status"], "Completed")
        self.assertEqual(external_activity["rows"], 100)
        self.assertEqual(external_activity["schema_id"], str(schema.id))
        self.assertEqual(external_activity["source_id"], str(source.id))

        modeling_activity = next(a for a in data["activities"] if a["type"] == "materialized_view")
        self.assertEqual(modeling_activity["name"], None)
        self.assertEqual(modeling_activity["status"], "Running")
        self.assertEqual(modeling_activity["rows"], 50)

    def test_recent_activity_respects_limit_parameter(self):
        """Test recent activity respects limit parameter and max limit"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="test", team=self.team, source=source)

        for i in range(5):
            ExternalDataJob.objects.create(
                pipeline_id=source.pk,
                schema=schema,
                team=self.team,
                rows_synced=i * 10,
                billable=True,
                status="Completed",
            )

        response = self.client.get(f"{endpoint}?limit=2")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["activities"]), 2)
        self.assertEqual(data["limit"], 2)

        response = self.client.get(f"{endpoint}?limit=100")
        data = response.json()

        self.assertEqual(data["limit"], 50)

    def test_recent_activity_handles_jobs_with_null_schemas(self):
        """Test recent activity handles jobs with null schemas gracefully"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        # Create job without schema
        ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=None, team=self.team, rows_synced=100, billable=True, status="Completed"
        )

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["activities"]), 1)

        activity = data["activities"][0]
        self.assertIsNone(activity["name"])
        self.assertIsNone(activity["schema_id"])
        self.assertEqual(activity["type"], "Stripe")

    def test_recent_activity_handles_jobs_with_null_pipelines(self):
        """Test recent activity handles jobs with null pipelines gracefully"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        # Create job with null pipeline by setting pipeline_id to None (simulating orphaned job)
        ExternalDataJob.objects.create(
            pipeline_id=None, schema=None, team=self.team, rows_synced=100, billable=True, status="Completed"
        )

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["activities"]), 1)

        activity = data["activities"][0]
        self.assertIsNone(activity["type"])
        self.assertIsNone(activity["source_id"])

    def test_recent_activity_invalid_limit_parameters(self):
        """Test recent activity handles invalid limit parameters"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        # Test negative limit
        response = self.client.get(f"{endpoint}?limit=-5")
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["limit"], 50)  # Should default to MAX_RECENT_ACTIVITY_RESULTS

        # Test very large limit
        response = self.client.get(f"{endpoint}?limit=999999")
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["limit"], 50)  # Should cap at MAX_RECENT_ACTIVITY_RESULTS

        # Test non-numeric limit
        response = self.client.get(f"{endpoint}?limit=abc")
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["limit"], 50)  # Should default to MAX_RECENT_ACTIVITY_RESULTS

    def test_recent_activity_empty_result_sets(self):
        """Test recent activity handles empty result sets"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["activities"]), 0)
        self.assertEqual(data["total_count"], 0)
        self.assertIn("limit", data)

    def test_recent_activity_modeling_job_without_saved_query(self):
        """Test recent activity handles DataModelingJob without saved_query"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        DataModelingJob.objects.create(team=self.team, saved_query=None, status="Running", rows_materialized=50)

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["activities"]), 1)

        activity = data["activities"][0]
        self.assertIsNone(activity["name"])
        self.assertEqual(activity["type"], "materialized_view")
        self.assertEqual(activity["status"], "Running")

    @patch("posthog.warehouse.api.data_warehouse.BillingManager")
    @patch("posthog.warehouse.api.data_warehouse.get_cached_instance_license")
    def test_total_rows_stats_handles_malformed_billing_dates(self, mock_license, mock_billing_manager):
        """Test total_rows_stats handles malformed billing period dates"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/total_rows_stats"

        mock_billing_manager.return_value.get_billing.return_value = {
            "billing_period": {
                "current_period_start": "invalid-date",
                "current_period_end": "2023-09-01T00:00:00Z",
                "interval": "month",
            },
            "usage_summary": {"rows_synced": {"usage": 100}},
        }

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["billingAvailable"], True)
        self.assertEqual(data["trackedBillingRows"], 100)
        # When dates are invalid, should fallback to tracked billing rows only
        self.assertEqual(data["totalRows"], 100)
        self.assertEqual(data["pendingBillingRows"], 0)

    @patch("posthog.warehouse.api.data_warehouse.BillingManager")
    @patch("posthog.warehouse.api.data_warehouse.get_cached_instance_license")
    def test_total_rows_stats_handles_malformed_usage_summary(self, mock_license, mock_billing_manager):
        """Test total_rows_stats handles malformed usage_summary structure"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/total_rows_stats"

        # Test with non-dict usage_summary
        mock_billing_manager.return_value.get_billing.return_value = {
            "billing_period": {
                "current_period_start": "2023-08-01T00:00:00Z",
                "current_period_end": "2023-09-01T00:00:00Z",
                "interval": "month",
            },
            "usage_summary": "invalid_structure",
        }

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["trackedBillingRows"], 0)

    @patch("posthog.warehouse.api.data_warehouse.BillingManager")
    @patch("posthog.warehouse.api.data_warehouse.get_cached_instance_license")
    def test_total_rows_stats_handles_missing_billing_period(self, mock_license, mock_billing_manager):
        """Test total_rows_stats handles missing billing period"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/total_rows_stats"

        mock_billing_manager.return_value.get_billing.return_value = {
            "usage_summary": {"rows_synced": {"usage": 100}},
            # No billing_period
        }

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["billingAvailable"], False)
        self.assertEqual(data["trackedBillingRows"], 0)
        self.assertEqual(data["pendingBillingRows"], 0)

    def test_team_isolation_in_recent_activity(self):
        """Test that recent activity properly isolates data by team"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/recent_activity"

        # Create another team
        from posthog.models import Team, Organization

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # Create jobs for both teams
        source1 = ExternalDataSource.objects.create(
            source_id="test-id-1",
            connection_id="conn-id-1",
            destination_id="dest-id-1",
            team=self.team,
            source_type="Stripe",
        )
        schema1 = ExternalDataSchema.objects.create(name="customers", team=self.team, source=source1)
        ExternalDataJob.objects.create(
            pipeline_id=source1.pk, schema=schema1, team=self.team, rows_synced=100, billable=True, status="Completed"
        )

        source2 = ExternalDataSource.objects.create(
            source_id="test-id-2",
            connection_id="conn-id-2",
            destination_id="dest-id-2",
            team=other_team,
            source_type="Hubspot",
        )
        schema2 = ExternalDataSchema.objects.create(name="contacts", team=other_team, source=source2)
        ExternalDataJob.objects.create(
            pipeline_id=source2.pk, schema=schema2, team=other_team, rows_synced=200, billable=True, status="Completed"
        )

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["activities"]), 1)  # Only our team's job

        activity = data["activities"][0]
        self.assertEqual(activity["name"], "customers")
        self.assertEqual(activity["type"], "Stripe")
