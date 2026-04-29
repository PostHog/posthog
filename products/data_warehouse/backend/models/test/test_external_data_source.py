from posthog.test.base import BaseTest
from unittest.mock import patch

from products.data_warehouse.backend.models import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType

CLEANUP_PATH = "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.cleanup_cdc_resources_on_deletion"


class TestExternalDataSourceSoftDelete(BaseTest):
    """Soft-deletion marks the row deleted and unconditionally hands off to the
    registered source impl's `cleanup_cdc_resources_on_deletion` — each source
    decides whether there's anything to tear down. The model carries no
    source-specific knowledge."""

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
    def test_soft_delete_marks_deleted_and_delegates_to_source_impl(self, mock_cleanup):
        source = self._create_source(
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "localhost", "cdc_enabled": True},
        )

        source.soft_delete()

        source.refresh_from_db()
        self.assertTrue(source.deleted)
        self.assertIsNotNone(source.deleted_at)
        mock_cleanup.assert_called_once()
        ((called_source,), _) = mock_cleanup.call_args
        self.assertEqual(called_source.pk, source.pk)

    @patch(CLEANUP_PATH)
    def test_soft_delete_calls_cleanup_for_non_cdc_postgres_too(self, mock_cleanup):
        # Reviewer's design: model doesn't gate on cdc_enabled. The source impl is
        # responsible for deciding it has nothing to do.
        source = self._create_source(
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "localhost", "cdc_enabled": False},
        )

        source.soft_delete()

        source.refresh_from_db()
        self.assertTrue(source.deleted)
        mock_cleanup.assert_called_once()

    @patch(CLEANUP_PATH)
    def test_soft_delete_calls_cleanup_when_job_inputs_missing(self, mock_cleanup):
        source = self._create_source(source_type=ExternalDataSourceType.POSTGRES, job_inputs=None)

        source.soft_delete()

        source.refresh_from_db()
        self.assertTrue(source.deleted)
        mock_cleanup.assert_called_once()
