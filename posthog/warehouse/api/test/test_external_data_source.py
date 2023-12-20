from posthog.test.base import APIBaseTest
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema
import uuid
from unittest.mock import patch
from posthog.temporal.data_imports.pipelines.stripe.stripe_pipeline import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)


class TestSavedQuery(APIBaseTest):
    def _create_external_data_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            prefix="test",
            job_inputs={
                "stripe_secret_key": "sk_test_123",
            },
        )

    def _create_external_data_schema(self, source_id) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name="Customers", team_id=self.team.pk, source_id=source_id, table=None
        )

    def test_create_external_data_source(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/external_data_sources/",
            data={"source_type": "Stripe", "client_secret": "sk_test_123"},
        )
        payload = response.json()

        self.assertEqual(response.status_code, 201)
        # number of schemas should match default schemas for Stripe
        self.assertEqual(
            ExternalDataSchema.objects.filter(source_id=payload["id"]).count(),
            len(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[ExternalDataSource.Type.STRIPE]),
        )

    def test_prefix_external_data_source(self):
        # Create no prefix

        response = self.client.post(
            f"/api/projects/{self.team.id}/external_data_sources/",
            data={"source_type": "Stripe", "client_secret": "sk_test_123"},
        )
        self.assertEqual(response.status_code, 201)

        # Try to create same type without prefix again

        response = self.client.post(
            f"/api/projects/{self.team.id}/external_data_sources/",
            data={"source_type": "Stripe", "client_secret": "sk_test_123"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"message": "Source type already exists. Prefix is required"})

        # Create with prefix
        response = self.client.post(
            f"/api/projects/{self.team.id}/external_data_sources/",
            data={"source_type": "Stripe", "client_secret": "sk_test_123", "prefix": "test_"},
        )

        self.assertEqual(response.status_code, 201)

        # Try to create same type with same prefix again
        response = self.client.post(
            f"/api/projects/{self.team.id}/external_data_sources/",
            data={"source_type": "Stripe", "client_secret": "sk_test_123", "prefix": "test_"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"message": "Prefix already exists"})

    def test_list_external_data_source(self):
        self._create_external_data_source()
        self._create_external_data_source()

        response = self.client.get(f"/api/projects/{self.team.id}/external_data_sources/")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["results"]), 2)

    def test_get_external_data_source_with_schema(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)

        response = self.client.get(f"/api/projects/{self.team.id}/external_data_sources/{source.pk}")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertListEqual(
            list(payload.keys()),
            ["id", "created_at", "created_by", "status", "source_type", "prefix", "last_run_at", "schemas"],
        )
        self.assertEqual(
            payload["schemas"],
            [
                {
                    "id": str(schema.pk),
                    "last_synced_at": schema.last_synced_at,
                    "name": schema.name,
                    "should_sync": schema.should_sync,
                    "latest_error": schema.latest_error,
                    "table": schema.table,
                }
            ],
        )

    def test_delete_external_data_source(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)

        response = self.client.delete(f"/api/projects/{self.team.id}/external_data_sources/{source.pk}")

        self.assertEqual(response.status_code, 204)

        self.assertFalse(ExternalDataSource.objects.filter(pk=source.pk).exists())
        self.assertFalse(ExternalDataSchema.objects.filter(pk=schema.pk).exists())

    @patch("posthog.warehouse.api.external_data_source.trigger_external_data_workflow")
    def test_reload_external_data_source(self, mock_trigger):
        source = self._create_external_data_source()

        response = self.client.post(f"/api/projects/{self.team.id}/external_data_sources/{source.pk}/reload/")

        source.refresh_from_db()

        self.assertEqual(mock_trigger.call_count, 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(source.status, "Running")
