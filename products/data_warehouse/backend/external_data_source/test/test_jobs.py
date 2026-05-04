import uuid

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team

from products.data_warehouse.backend.external_data_source.jobs import update_external_job_status
from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource

pytestmark = [
    pytest.mark.django_db,
]


def _create_org_team_source_schema_job() -> tuple[Team, ExternalDataSource, ExternalDataSchema, ExternalDataJob]:
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org, name="Test Team")
    source = ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        status="running",
        source_type="Stripe",
    )
    schema = ExternalDataSchema.objects.create(name="Charge", team=team, source=source)
    job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=100,
    )
    return team, source, schema, job


class TestUpdateExternalJobStatus:
    def test_first_terminal_transition_stamps_finished_at_and_emits(self):
        team, _source, _schema, job = _create_org_team_source_schema_job()

        with patch(
            "products.data_warehouse.backend.external_data_source.jobs.emit_data_import_app_metrics"
        ) as mock_emit:
            updated = update_external_job_status(
                job_id=str(job.id),
                team_id=team.pk,
                status=ExternalDataJob.Status.COMPLETED,
                logger=MagicMock(),
                latest_error=None,
            )

        assert updated.status == ExternalDataJob.Status.COMPLETED
        assert updated.finished_at is not None
        mock_emit.assert_called_once()
        emitted_job = mock_emit.call_args.args[0]
        assert emitted_job.id == job.id
        assert emitted_job.status == ExternalDataJob.Status.COMPLETED

    def test_retried_terminal_transition_is_idempotent(self):
        """A redelivered Kafka message or retried Temporal activity must not
        re-emit app_metrics2 rows for a job that already reached terminal state."""
        team, _source, _schema, job = _create_org_team_source_schema_job()

        with patch(
            "products.data_warehouse.backend.external_data_source.jobs.emit_data_import_app_metrics"
        ) as mock_emit:
            update_external_job_status(
                job_id=str(job.id),
                team_id=team.pk,
                status=ExternalDataJob.Status.COMPLETED,
                logger=MagicMock(),
                latest_error=None,
            )
            first_finished_at = ExternalDataJob.objects.get(id=job.id).finished_at

            update_external_job_status(
                job_id=str(job.id),
                team_id=team.pk,
                status=ExternalDataJob.Status.COMPLETED,
                logger=MagicMock(),
                latest_error=None,
            )

        assert mock_emit.call_count == 1
        second_finished_at = ExternalDataJob.objects.get(id=job.id).finished_at
        assert second_finished_at == first_finished_at

    def test_non_terminal_status_does_not_emit_or_stamp(self):
        team, _source, _schema, job = _create_org_team_source_schema_job()

        with patch(
            "products.data_warehouse.backend.external_data_source.jobs.emit_data_import_app_metrics"
        ) as mock_emit:
            updated = update_external_job_status(
                job_id=str(job.id),
                team_id=team.pk,
                status=ExternalDataJob.Status.RUNNING,
                logger=MagicMock(),
                latest_error=None,
            )

        assert updated.finished_at is None
        mock_emit.assert_not_called()

    def test_concurrent_rows_synced_update_is_not_clobbered(self):
        """Regression: `update_external_job_status` must not overwrite `rows_synced`
        with the in-memory value it loaded at the top of the function. In V3 the
        consumer-side completion can race a still-pending `update_job_row_count`
        F-update from the activity (e.g. on retry). Saving the full model would
        rewind the count — and downstream emit `count: 0` for the rows metric."""
        team, _source, _schema, job = _create_org_team_source_schema_job()
        # Job loaded with rows_synced=100; simulate a concurrent F-update bumping
        # it to 500 between objects.get() and model.save() inside the function.

        original_save = ExternalDataJob.save

        def save_with_concurrent_update(self, *args, **kwargs):
            ExternalDataJob.objects.filter(id=self.id).update(rows_synced=500)
            return original_save(self, *args, **kwargs)

        with (
            patch(
                "products.data_warehouse.backend.external_data_source.jobs.emit_data_import_app_metrics"
            ) as mock_emit,
            patch.object(ExternalDataJob, "save", autospec=True, side_effect=save_with_concurrent_update),
        ):
            update_external_job_status(
                job_id=str(job.id),
                team_id=team.pk,
                status=ExternalDataJob.Status.COMPLETED,
                logger=MagicMock(),
                latest_error=None,
            )

        # The concurrent +400 increment must survive the status save.
        assert ExternalDataJob.objects.get(id=job.id).rows_synced == 500
        emitted_job = mock_emit.call_args.args[0]
        assert emitted_job.rows_synced == 500

    def test_failed_status_emits_and_stamps(self):
        team, _source, _schema, job = _create_org_team_source_schema_job()

        with patch(
            "products.data_warehouse.backend.external_data_source.jobs.emit_data_import_app_metrics"
        ) as mock_emit:
            updated = update_external_job_status(
                job_id=str(job.id),
                team_id=team.pk,
                status=ExternalDataJob.Status.FAILED,
                logger=MagicMock(),
                latest_error="boom",
            )

        assert updated.status == ExternalDataJob.Status.FAILED
        assert updated.finished_at is not None
        assert updated.latest_error == "boom"
        mock_emit.assert_called_once()
