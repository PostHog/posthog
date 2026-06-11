import uuid
import datetime as dt

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team

from products.data_warehouse.backend.external_data_source.notifications import (
    ERROR_SNIPPET_MAX_LENGTH,
    get_team_ids_with_recent_sync_failures,
    notify_external_data_sync_failures,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

pytestmark = [
    pytest.mark.django_db,
]

SENDER_PATH = "products.data_warehouse.backend.external_data_source.notifications.send_external_data_failure_digest"


def _create_team_and_source() -> tuple[Team, ExternalDataSource]:
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
    return team, source


class TestNotifyExternalDataSyncFailures:
    def test_sends_digest_with_failing_schemas_classified(self):
        team, source = _create_team_and_source()
        ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            should_sync=True,
            latest_error="transient error",
        )
        ExternalDataSchema.objects.create(
            name="Invoice",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            should_sync=False,
            latest_error="Invalid API key",
        )

        with patch(SENDER_PATH) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        mock_sender.assert_called_once()
        team_id, items = mock_sender.call_args.args
        assert team_id == team.pk
        # Paused schemas come first.
        assert [(item["schema_name"], item["paused"]) for item in items] == [
            ("Invoice", True),
            ("Charge", False),
        ]
        assert items[0]["error"] == "Invalid API key"
        assert items[0]["source_type"] == "Stripe"
        assert f"managed-{source.id}/syncs?schema=Invoice" in items[0]["url"]

    @pytest.mark.parametrize(
        "status,should_sync,deleted",
        [
            (ExternalDataSchema.Status.COMPLETED, True, False),
            (ExternalDataSchema.Status.RUNNING, True, False),
            (ExternalDataSchema.Status.BILLING_LIMIT_REACHED, True, False),
            (ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW, True, False),
            (ExternalDataSchema.Status.FAILED, True, True),
        ],
    )
    def test_does_not_send_for_non_failing_or_deleted_schemas(self, status, should_sync, deleted):
        team, source = _create_team_and_source()
        ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=status,
            should_sync=should_sync,
            deleted=deleted,
            latest_error="some error",
        )

        with patch(SENDER_PATH) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        mock_sender.assert_not_called()

    def test_truncates_long_errors(self):
        team, source = _create_team_and_source()
        ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="x" * 1000,
        )

        with patch(SENDER_PATH) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        (_, items) = mock_sender.call_args.args
        assert len(items[0]["error"]) == ERROR_SNIPPET_MAX_LENGTH
        assert items[0]["error"].endswith("…")

    def test_missing_error_defaults_to_unknown(self):
        team, source = _create_team_and_source()
        ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error=None,
        )

        with patch(SENDER_PATH) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        (_, items) = mock_sender.call_args.args
        assert items[0]["error"] == "Unknown error"

    def test_swallows_sender_exceptions(self):
        team, source = _create_team_and_source()
        ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="boom",
        )

        with patch(SENDER_PATH, side_effect=Exception("smtp down")):
            notify_external_data_sync_failures(team.pk)


class TestGetTeamIdsWithRecentSyncFailures:
    def _create_schema_with_job(
        self,
        *,
        schema_status: str,
        job_finished_at: dt.datetime,
        schema_deleted: bool = False,
    ) -> Team:
        team, source = _create_team_and_source()
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=schema_status,
            deleted=schema_deleted,
            latest_error="boom",
        )
        job = ExternalDataJob.objects.create(
            team=team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.FAILED,
        )
        # finished_at is stamped by the status-update path; set it directly here.
        ExternalDataJob.objects.filter(id=job.id).update(finished_at=job_finished_at)
        return team

    def test_includes_team_with_recent_failure_on_failing_schema(self):
        team = self._create_schema_with_job(
            schema_status=ExternalDataSchema.Status.FAILED,
            job_finished_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
        )

        assert get_team_ids_with_recent_sync_failures() == [team.pk]

    @pytest.mark.parametrize(
        "schema_status,job_age,schema_deleted",
        [
            # Failure older than the lookback — already had its chance to be flushed.
            (ExternalDataSchema.Status.FAILED, dt.timedelta(hours=30), False),
            # Schema recovered since the failure.
            (ExternalDataSchema.Status.COMPLETED, dt.timedelta(hours=2), False),
            # Schema deleted since the failure.
            (ExternalDataSchema.Status.FAILED, dt.timedelta(hours=2), True),
        ],
    )
    def test_excludes_non_actionable_teams(self, schema_status, job_age, schema_deleted):
        self._create_schema_with_job(
            schema_status=schema_status,
            job_finished_at=dt.datetime.now(dt.UTC) - job_age,
            schema_deleted=schema_deleted,
        )

        assert get_team_ids_with_recent_sync_failures() == []
