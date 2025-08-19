from unittest.mock import patch
from datetime import datetime, UTC
from posthog.test.base import APIBaseTest
from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource


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
