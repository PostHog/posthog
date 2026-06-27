import uuid
import datetime as dt
from urllib.parse import quote

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team

from products.data_warehouse.backend.logic.external_data_source.notifications import (
    MAX_SCHEMAS_PER_DIGEST_EMAIL,
    get_team_ids_with_recent_sync_failures,
    notify_external_data_sync_failures,
)
from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource

pytestmark = [
    pytest.mark.django_db,
]

SENDER_PATH = (
    "products.data_warehouse.backend.logic.external_data_source.notifications.send_external_data_failure_digest"
)


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
        assert [(item["schema_name"], item["paused"]) for item in items] == [
            ("Invoice", True),
            ("Charge", False),
        ]
        assert items[0]["error"] == "Invalid API key"
        assert items[0]["source_type"] == "Stripe"
        assert f"managed-{source.id}/syncs?schema=Invoice" in items[0]["url"]

    @pytest.mark.parametrize(
        "name,label,expected_display",
        [
            ("C08LGV7UHS9", "#data-alerts", "#data-alerts"),  # label preferred for display
            ("Charge", None, "Charge"),  # falls back to name when label is missing
        ],
    )
    def test_display_uses_label_but_url_uses_name(self, name, label, expected_display):
        team, source = _create_team_and_source()
        ExternalDataSchema.objects.create(
            name=name,
            label=label,
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="transient error",
        )

        with patch(SENDER_PATH) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        (_, items) = mock_sender.call_args.args
        # The displayed name prefers the human-readable label...
        assert items[0]["schema_name"] == expected_display
        # ...but the deep link always keeps using the raw identifier.
        assert f"?schema={quote(name)}" in items[0]["url"]

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

    def test_caps_listed_schemas_and_reports_omitted_count(self):
        team, source = _create_team_and_source()
        total = MAX_SCHEMAS_PER_DIGEST_EMAIL + 5
        schemas = ExternalDataSchema.objects.bulk_create(
            ExternalDataSchema(
                name=f"table_{i:03d}",
                team=team,
                source=source,
                status=ExternalDataSchema.Status.FAILED,
                latest_error="boom",
            )
            for i in range(total)
        )

        with patch(SENDER_PATH, return_value=True) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        (_, items) = mock_sender.call_args.args
        assert len(items) == MAX_SCHEMAS_PER_DIGEST_EMAIL
        assert mock_sender.call_args.kwargs["omitted_count"] == 5
        assert (
            ExternalDataSchema.objects.filter(
                id__in=[schema.id for schema in schemas], last_error_notified_at__isnull=False
            ).count()
            == total
        )

    def test_stamps_schemas_after_successful_send(self):
        team, source = _create_team_and_source()
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="boom",
        )

        with patch(SENDER_PATH, return_value=True):
            notify_external_data_sync_failures(team.pk)

        schema.refresh_from_db()
        assert schema.last_error_notified_at is not None

    def test_does_not_stamp_when_email_not_sent(self):
        team, source = _create_team_and_source()
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="boom",
        )

        with patch(SENDER_PATH, return_value=False):
            notify_external_data_sync_failures(team.pk)

        schema.refresh_from_db()
        assert schema.last_error_notified_at is None

    def test_excludes_schemas_of_deleted_source(self):
        team, source = _create_team_and_source()
        ExternalDataSource.objects.filter(id=source.id).update(deleted=True)
        ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="boom",
        )

        with patch(SENDER_PATH) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        mock_sender.assert_not_called()

    @pytest.mark.parametrize(
        "run_offset,expected_sent",
        [
            (dt.timedelta(hours=1), True),  # failed run after the last notification -> report again
            (dt.timedelta(hours=-1), False),  # no run since the last notification -> stay silent
        ],
    )
    def test_already_notified_failure_renotifies_only_on_newer_run(self, run_offset, expected_sent):
        team, source = _create_team_and_source()
        notified_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="boom",
            last_error_notified_at=notified_at,
        )
        job = ExternalDataJob.objects.create(
            team=team, pipeline=source, schema=schema, status=ExternalDataJob.Status.FAILED
        )
        ExternalDataJob.objects.filter(id=job.id).update(finished_at=notified_at + run_offset)

        with patch(SENDER_PATH) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        assert mock_sender.called == expected_sent


class TestGetTeamIdsWithRecentSyncFailures:
    def _create_schema_with_job(
        self,
        *,
        schema_status: str,
        job_finished_at: dt.datetime,
        schema_deleted: bool = False,
        source_deleted: bool = False,
        last_error_notified_at: dt.datetime | None = None,
    ) -> Team:
        team, source = _create_team_and_source()
        if source_deleted:
            ExternalDataSource.objects.filter(id=source.id).update(deleted=True)
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=schema_status,
            deleted=schema_deleted,
            latest_error="boom",
            last_error_notified_at=last_error_notified_at,
        )
        job = ExternalDataJob.objects.create(
            team=team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.FAILED,
        )
        ExternalDataJob.objects.filter(id=job.id).update(finished_at=job_finished_at)
        return team

    def test_includes_team_with_recent_failure_on_failing_schema(self):
        team = self._create_schema_with_job(
            schema_status=ExternalDataSchema.Status.FAILED,
            job_finished_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
        )

        assert get_team_ids_with_recent_sync_failures() == [team.pk]

    @pytest.mark.parametrize(
        "schema_status,job_age,schema_deleted,source_deleted",
        [
            (ExternalDataSchema.Status.FAILED, dt.timedelta(hours=30), False, False),
            (ExternalDataSchema.Status.COMPLETED, dt.timedelta(hours=2), False, False),
            (ExternalDataSchema.Status.FAILED, dt.timedelta(hours=2), True, False),
            (ExternalDataSchema.Status.FAILED, dt.timedelta(hours=2), False, True),
        ],
    )
    def test_excludes_non_actionable_teams(self, schema_status, job_age, schema_deleted, source_deleted):
        self._create_schema_with_job(
            schema_status=schema_status,
            job_finished_at=dt.datetime.now(dt.UTC) - job_age,
            schema_deleted=schema_deleted,
            source_deleted=source_deleted,
        )

        assert get_team_ids_with_recent_sync_failures() == []

    def test_excludes_failures_already_communicated(self):
        self._create_schema_with_job(
            schema_status=ExternalDataSchema.Status.FAILED,
            job_finished_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
            last_error_notified_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
        )

        assert get_team_ids_with_recent_sync_failures() == []

    def test_includes_failures_newer_than_the_stamp(self):
        team = self._create_schema_with_job(
            schema_status=ExternalDataSchema.Status.FAILED,
            job_finished_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
            last_error_notified_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
        )

        assert get_team_ids_with_recent_sync_failures() == [team.pk]

    def test_includes_failure_blocked_just_after_digest_rollover(self):
        team = self._create_schema_with_job(
            schema_status=ExternalDataSchema.Status.FAILED,
            job_finished_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=24, minutes=10),
            last_error_notified_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=24, minutes=14),
        )

        assert get_team_ids_with_recent_sync_failures() == [team.pk]

    def test_only_returns_qualifying_teams(self):
        qualifying = self._create_schema_with_job(
            schema_status=ExternalDataSchema.Status.FAILED,
            job_finished_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
        )
        self._create_schema_with_job(
            schema_status=ExternalDataSchema.Status.COMPLETED,
            job_finished_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
        )

        assert get_team_ids_with_recent_sync_failures() == [qualifying.pk]
