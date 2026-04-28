from posthog.test.base import BaseTest
from unittest.mock import patch

from products.data_warehouse.backend.models import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType

CLEANUP_PATH = "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.cleanup_cdc_resources_on_deletion"


class TestExternalDataSourceSoftDelete(BaseTest):
    """Soft-deletion marks the row deleted. CDC sources additionally delegate
    teardown to the registered source impl — non-CDC sources don't touch the
    registry at all."""

    def _create_source(self, *, source_type: str, job_inputs: dict | None) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            source_id="src-1",
            connection_id="conn-1",
            destination_id="dest-1",
            team=self.team,
            status="Completed",
            source_type=source_type,
            job_inputs=job_inputs,
        )

    @patch(CLEANUP_PATH)
    def test_non_cdc_source_skips_cleanup(self, mock_cleanup):
        source = self._create_source(
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "localhost", "cdc_enabled": False},
        )

        source.soft_delete()

        source.refresh_from_db()
        self.assertTrue(source.deleted)
        self.assertIsNotNone(source.deleted_at)
        mock_cleanup.assert_not_called()

    @patch(CLEANUP_PATH)
    def test_missing_job_inputs_skips_cleanup(self, mock_cleanup):
        source = self._create_source(source_type=ExternalDataSourceType.POSTGRES, job_inputs=None)

        source.soft_delete()

        source.refresh_from_db()
        self.assertTrue(source.deleted)
        mock_cleanup.assert_not_called()

    @patch(CLEANUP_PATH)
    def test_cdc_source_delegates_to_source_impl(self, mock_cleanup):
        source = self._create_source(
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "localhost", "cdc_enabled": True},
        )

        source.soft_delete()

        source.refresh_from_db()
        self.assertTrue(source.deleted)
        # PostgresSource.cleanup_cdc_resources_on_deletion(self) — the model row is the only arg.
        mock_cleanup.assert_called_once()
        ((called_source,), _) = mock_cleanup.call_args
        self.assertEqual(called_source.pk, source.pk)
