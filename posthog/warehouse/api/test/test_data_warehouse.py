from unittest.mock import patch

from django.utils import timezone
from posthog.test.base import APIBaseTest
from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource


class TestDataWarehouseAPI(APIBaseTest):
    @patch("ee.billing.billing_manager.BillingManager")
    @patch("posthog.cloud_utils.get_cached_instance_license")
    def test_basic_calculation_with_billing_data(self, mock_license, mock_billing_manager):
        """Test core calculation: trackedBillingRows from billing, pendingBillingRows = db_total - billing_total"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/total_rows_stats"

        mock_billing_manager.return_value.get_billing.return_value = {
            "billing_period": {
                "current_period_start": "2023-08-01T00:00:00Z",
                "current_period_end": "2023-09-01T00:00:00Z",
                "interval": "monthly",
            },
            "usage_summary": {"rows_synced": {"usage": 100}},
        }

        source = ExternalDataSource.objects.create(
            source_id="test-id", connection_id="conn-id", destination_id="dest-id", team=self.team, source_type="Stripe"
        )
        schema = ExternalDataSchema.objects.create(name="test", team=self.team, source=source)
        job = ExternalDataJob.objects.create(
            pipeline_id=source.pk, schema=schema, team=self.team, rows_synced=150, billable=True
        )
        job.created_at = timezone.datetime(2023, 8, 15, tzinfo=timezone.utc)
        job.save()

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        # trackedBillings rows comes from the usage_summary.rows_synced.usage, which was set to 100
        # totalRows comes from the rows_synced field on the job, which was set to 150
        # pendingBillingRows is the difference between totalRows and trackedBillingRows (150 - 100 = 50)
        self.assertEqual(data["trackedBillingRows"], 100)
        self.assertEqual(data["pendingBillingRows"], 50)
        self.assertEqual(data["totalRows"], 150)

    @patch("ee.billing.billing_manager.BillingManager")
    @patch("posthog.cloud_utils.get_cached_instance_license")
    def test_billing_exception_returns_500(self, mock_license, mock_billing_manager):
        """Test when billing throws exception - should return 500"""
        endpoint = f"/api/projects/{self.team.id}/data_warehouse/total_rows_stats"

        mock_billing_manager.return_value.get_billing.side_effect = Exception("Billing service unavailable")

        response = self.client.get(endpoint)
        data = response.json()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(data["error"], "An error occured retrieving billing information")
