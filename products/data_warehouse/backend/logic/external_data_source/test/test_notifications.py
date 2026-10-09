import uuid
import datetime as dt
from collections.abc import Iterator
from urllib.parse import quote

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import override_settings

from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.instance_setting import override_instance_config
from posthog.models.messaging import MessagingRecord
from posthog.tasks.email import ExternalDataFailureDigestItem

from products.cdp.backend.facade.models import HogFunction
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.data_warehouse.backend.logic.external_data_source.alerts import (
    FAILURE_DIGEST_EVENT,
    build_failure_digest_summary,
)
from products.data_warehouse.backend.logic.external_data_source.notifications import (
    MAX_SCHEMAS_PER_DIGEST_EMAIL,
    get_team_ids_with_recent_sync_failures,
    notify_external_data_sync_failures,
)
from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource

SENDER_PATH = (
    "products.data_warehouse.backend.logic.external_data_source.notifications.send_external_data_failure_digest"
)
ALERTS_PATH = "products.data_warehouse.backend.logic.external_data_source.alerts"


@pytest.fixture(autouse=True)
def destination_flag() -> Iterator[MagicMock]:
    with patch(f"{ALERTS_PATH}.posthoganalytics.feature_enabled", return_value=False) as flag:
        yield flag


def _create_recipient(team: Team, *, opted_out: bool = False) -> User:
    user = User.objects.create_user(
        email=f"member-{uuid.uuid4()}@example.com",
        password=None,
        first_name="Test",
        partial_notification_settings={"plugin_disabled": not opted_out},
    )
    OrganizationMembership.objects.create(organization=team.organization, user=user)
    return user


def _create_email_template() -> HogFunctionTemplate:
    return HogFunctionTemplate.objects.create(
        template_id="template-posthog-email",
        name="Email project members",
        code="return event",
        type="internal_destination",
        inputs_schema=[
            {"key": key, "type": "string", "required": True}
            for key in ("subject", "body", "action_url", "action_label")
        ],
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


@pytest.mark.django_db
class TestNotifyExternalDataSyncFailures:
    @pytest.mark.parametrize("enabled", [False, None, True])
    @time_machine.travel("2026-05-15T09:00:00Z", tick=False)
    def test_digest_delivery_path(self, destination_flag: MagicMock, enabled: bool | None) -> None:
        destination_flag.return_value = enabled
        team, source = _create_team_and_source()
        recipient = _create_recipient(team)
        _create_recipient(team, opted_out=True)
        _create_email_template()
        schemas = [
            ExternalDataSchema.objects.create(
                name=name,
                team=team,
                source=source,
                status=ExternalDataSchema.Status.FAILED,
                latest_error=error,
                should_sync=not paused,
                auto_disabled_at=dt.datetime.now(dt.UTC) if paused else None,
            )
            for name, error, paused in [("Invoice", "Invalid API key", True), ("Charge", "Retry needed", False)]
        ]
        with (
            patch(SENDER_PATH, return_value=True) as sender,
            patch(f"{ALERTS_PATH}.produce_internal_event") as produce,
            patch("posthog.plugins.plugin_server_api.publish_message"),
        ):
            notify_external_data_sync_failures(team.pk)

        if enabled:
            sender.assert_not_called()
            produce.assert_called_once()
            assert produce.call_args.kwargs["team_id"] == team.pk
            event = produce.call_args.kwargs["event"]
            source_url = f"{settings.SITE_URL}/project/{team.pk}/data-management/sources/managed-{source.id}/syncs"
            assert event.event == FAILURE_DIGEST_EVENT
            assert event.distinct_id == f"team_{team.pk}"
            assert event.properties == {
                "$notify_user_ids": [recipient.pk],
                "schemas": [
                    {
                        "schema_name": name,
                        "source_id": str(source.id),
                        "source_type": "Stripe",
                        "source_prefix": "",
                        "source_url": source_url,
                        "error": error,
                        "paused": paused,
                        "url": f"{source_url}?schema={name}",
                    }
                    for name, error, paused in [("Invoice", "Invalid API key", True), ("Charge", "Retry needed", False)]
                ],
                "schema_count": 2,
                "omitted_count": 0,
                "digest_day": "2026-05-14",
                "sources_url": f"{settings.SITE_URL}/project/{team.pk}/data-management/sources",
                "summary": "Stripe / Invoice: Invalid API key (paused)\nStripe / Charge: Retry needed",
            }
            assert MessagingRecord.objects.filter(
                campaign_key=f"external_data_failure_digest_{team.pk}_2026-05-14", sent_at__isnull=False
            ).exists()
        else:
            sender.assert_called_once()
            produce.assert_not_called()
            assert not HogFunction.objects.filter(team=team).exists()
        for schema in schemas:
            schema.refresh_from_db()
            assert schema.last_error_notified_at == dt.datetime.now(dt.UTC)
        destination_flag.assert_any_call(
            key="dwh-failure-email-destination",
            distinct_id=str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.pk)},
            group_properties={"organization": {"id": str(team.organization_id)}, "project": {"id": str(team.pk)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    @pytest.mark.parametrize("state", ["enabled", "deleted", "disabled"])
    def test_preserves_default_destination(self, destination_flag: MagicMock, state: str) -> None:
        destination_flag.return_value = True
        team, source = _create_team_and_source()
        _create_recipient(team)
        template = _create_email_template()
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="Retry needed",
        )
        with (
            patch(SENDER_PATH) as sender,
            patch(f"{ALERTS_PATH}.produce_internal_event") as produce,
            patch("posthog.plugins.plugin_server_api.publish_message"),
        ):
            with time_machine.travel("2026-05-15T12:00:00Z", tick=False):
                notify_external_data_sync_failures(team.pk)
            function = HogFunction.objects.get(team=team)
            assert function.created_by is None
            assert function.enabled
            assert function.type == "internal_destination"
            assert function.template_id == template.template_id
            assert function.hog_function_template == template
            assert function.hog == template.code
            assert function.bytecode == template.bytecode
            assert function.inputs_schema == template.inputs_schema
            assert function.filters is not None
            assert function.inputs is not None
            assert function.filters["source"] == "internal-events"
            assert function.filters["events"] == [{"id": FAILURE_DIGEST_EVENT, "type": "events"}]
            assert function.inputs["body"]["value"] == "These tables failed to sync:\n\n{event.properties.summary}"
            assert function.inputs["body"]["bytecode"]
            HogFunction.objects.filter(pk=function.pk).update(
                deleted=state == "deleted", enabled=state == "enabled", name="Custom email"
            )
            ExternalDataSchema.objects.filter(pk=schema.pk).update(last_error_notified_at=None)
            with time_machine.travel("2026-05-16T12:00:00Z", tick=False):
                notify_external_data_sync_failures(team.pk)
        sender.assert_not_called()
        assert produce.call_count == 2
        assert HogFunction.objects.filter(team=team).count() == 1
        function.refresh_from_db()
        assert function.deleted == (state == "deleted")
        assert function.enabled == (state == "enabled")
        assert function.name == "Custom email"

    @pytest.mark.parametrize("sent", [False, True])
    def test_missing_template_uses_email(self, destination_flag: MagicMock, sent: bool) -> None:
        destination_flag.return_value = True
        team, source = _create_team_and_source()
        _create_recipient(team)
        schema = ExternalDataSchema.objects.create(
            name="Charge", team=team, source=source, status=ExternalDataSchema.Status.FAILED
        )
        with patch(SENDER_PATH, return_value=sent) as sender, patch(f"{ALERTS_PATH}.produce_internal_event") as produce:
            notify_external_data_sync_failures(team.pk)
        sender.assert_called_once()
        produce.assert_not_called()
        assert not HogFunction.objects.filter(team=team).exists()
        schema.refresh_from_db()
        assert (schema.last_error_notified_at is not None) == sent

    @pytest.mark.parametrize("opted_out_member", [False, True])
    def test_event_without_recipients(self, destination_flag: MagicMock, opted_out_member: bool) -> None:
        destination_flag.return_value = True
        team, source = _create_team_and_source()
        if opted_out_member:
            _create_recipient(team, opted_out=True)
        _create_email_template()
        schema = ExternalDataSchema.objects.create(
            name="Charge", team=team, source=source, status=ExternalDataSchema.Status.FAILED
        )
        with patch(SENDER_PATH) as sender, patch(f"{ALERTS_PATH}.produce_internal_event") as produce:
            notify_external_data_sync_failures(team.pk)
        sender.assert_not_called()
        produce.assert_not_called()
        schema.refresh_from_db()
        assert schema.last_error_notified_at is None
        assert not MessagingRecord.objects.exists()

    def test_failed_produce_does_not_stamp(self, destination_flag: MagicMock) -> None:
        destination_flag.return_value = True
        team, source = _create_team_and_source()
        _create_recipient(team)
        _create_email_template()
        schema = ExternalDataSchema.objects.create(
            name="Charge", team=team, source=source, status=ExternalDataSchema.Status.FAILED
        )
        with (
            patch(SENDER_PATH) as sender,
            patch(f"{ALERTS_PATH}.produce_internal_event", side_effect=RuntimeError("Queue unavailable")) as produce,
            patch("posthog.plugins.plugin_server_api.publish_message"),
        ):
            notify_external_data_sync_failures(team.pk)
        produce.assert_called_once()
        sender.assert_not_called()
        schema.refresh_from_db()
        assert schema.last_error_notified_at is None
        assert not MessagingRecord.objects.exists()

    @pytest.mark.parametrize("first_enabled,second_enabled", [(True, True), (True, False), (False, True)])
    @override_settings(SITE_URL="https://example.com", TEST=True)
    @time_machine.travel("2026-05-15T12:00:00Z", tick=False)
    def test_dedupes_across_delivery_paths(
        self, destination_flag: MagicMock, first_enabled: bool, second_enabled: bool
    ) -> None:
        team, source = _create_team_and_source()
        _create_recipient(team)
        _create_email_template()
        schema = ExternalDataSchema.objects.create(
            name="Charge", team=team, source=source, status=ExternalDataSchema.Status.FAILED
        )

        def record_delivery(*, send_async: bool) -> None:
            MessagingRecord.objects.create(
                email_hash="test-recipient",
                campaign_key=f"external_data_failure_digest_{team.pk}_2026-05-15",
                sent_at=dt.datetime.now(dt.UTC),
            )

        with (
            override_instance_config("EMAIL_ENABLED", True),
            override_instance_config("EMAIL_HOST", "smtp.example.com"),
            patch("posthog.tasks.email.EmailMessage.send", side_effect=record_delivery) as send,
            patch(f"{ALERTS_PATH}.produce_internal_event") as produce,
            patch("posthog.plugins.plugin_server_api.publish_message"),
        ):
            destination_flag.return_value = first_enabled
            notify_external_data_sync_failures(team.pk)
            schema.refresh_from_db()
            assert schema.last_error_notified_at is not None
            ExternalDataSchema.objects.filter(pk=schema.pk).update(last_error_notified_at=None)
            destination_flag.return_value = second_enabled
            notify_external_data_sync_failures(team.pk)
        assert produce.call_count == int(first_enabled)
        assert send.call_count == int(not first_enabled)
        schema.refresh_from_db()
        assert schema.last_error_notified_at is None

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
        # PostHog stopped this one itself after a non-retryable error, so it stays in the digest:
        # only the user can repair the source and turn syncing back on.
        ExternalDataSchema.objects.create(
            name="Invoice",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            should_sync=False,
            auto_disabled_at=dt.datetime.now(dt.UTC),
            latest_error="Invalid API key",
        )
        # CDC breakage halts syncing without flipping should_sync — it must still read as
        # "action required", not "will retry".
        ExternalDataSchema.objects.create(
            name="Accounts",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            should_sync=True,
            latest_error="Replication slot dropped",
            sync_type_config={"cdc_broken": {"reason": "auto_dropped_critical_lag"}},
        )

        with patch(SENDER_PATH) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        mock_sender.assert_called_once()
        team_id, items = mock_sender.call_args.args
        assert team_id == team.pk
        assert [(item["schema_name"], item["paused"]) for item in items] == [
            ("Accounts", True),
            ("Invoice", True),
            ("Charge", False),
        ]
        assert items[0]["error"] == "Replication slot dropped"
        assert items[0]["source_type"] == "Stripe"
        assert f"managed-{source.id}/syncs?schema=Accounts" in items[0]["url"]

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
            # The user switched syncing off. The status stays Failed for the syncs UI, but
            # there is nothing left to chase, so the digest must not report it.
            (ExternalDataSchema.Status.FAILED, False, False),
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

    @pytest.mark.parametrize("use_destination", [False, True])
    def test_caps_listed_schemas_and_reports_omitted_count(
        self, destination_flag: MagicMock, use_destination: bool
    ) -> None:
        destination_flag.return_value = use_destination
        team, source = _create_team_and_source()
        if use_destination:
            _create_recipient(team)
            _create_email_template()
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

        with (
            patch(SENDER_PATH, return_value=True) as mock_sender,
            patch(f"{ALERTS_PATH}.produce_internal_event") as produce,
            patch("posthog.plugins.plugin_server_api.publish_message"),
        ):
            notify_external_data_sync_failures(team.pk)

        if use_destination:
            mock_sender.assert_not_called()
            properties = produce.call_args.kwargs["event"].properties
            items = properties["schemas"]
            assert properties["omitted_count"] == 5
            assert properties["schema_count"] == total
        else:
            (_, items) = mock_sender.call_args.args
            assert mock_sender.call_args.kwargs["omitted_count"] == 5
        assert len(items) == MAX_SCHEMAS_PER_DIGEST_EMAIL
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

    @pytest.mark.parametrize(
        "notified_age,expected_sent",
        [
            (dt.timedelta(days=8), True),  # still failing past the window -> remind again
            (dt.timedelta(days=6), False),  # notified recently, no new run -> stay silent
        ],
    )
    def test_renotifies_still_failing_schema_without_a_newer_run(self, notified_age, expected_sent):
        # A paused schema never runs again, so it produces no newer failed job. It must
        # still get a reminder once its last email ages past the re-notify window.
        team, source = _create_team_and_source()
        ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            status=ExternalDataSchema.Status.FAILED,
            should_sync=False,
            auto_disabled_at=dt.datetime.now(dt.UTC) - notified_age,
            latest_error="Invalid API key",
            last_error_notified_at=dt.datetime.now(dt.UTC) - notified_age,
        )

        with patch(SENDER_PATH) as mock_sender:
            notify_external_data_sync_failures(team.pk)

        assert mock_sender.called == expected_sent


@pytest.mark.django_db
class TestGetTeamIdsWithRecentSyncFailures:
    def _create_schema_with_job(
        self,
        *,
        schema_status: str,
        job_finished_at: dt.datetime,
        schema_deleted: bool = False,
        source_deleted: bool = False,
        last_error_notified_at: dt.datetime | None = None,
        should_sync: bool = True,
        auto_disabled_at: dt.datetime | None = None,
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
            should_sync=should_sync,
            auto_disabled_at=auto_disabled_at,
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
        "schema_status,job_age,schema_deleted,source_deleted,should_sync",
        [
            (ExternalDataSchema.Status.FAILED, dt.timedelta(hours=30), False, False, True),
            (ExternalDataSchema.Status.COMPLETED, dt.timedelta(hours=2), False, False, True),
            (ExternalDataSchema.Status.FAILED, dt.timedelta(hours=2), True, False, True),
            (ExternalDataSchema.Status.FAILED, dt.timedelta(hours=2), False, True, True),
            # Switched off by the user, so the catch-up sweep has nothing to chase.
            (ExternalDataSchema.Status.FAILED, dt.timedelta(hours=2), False, False, False),
        ],
    )
    def test_excludes_non_actionable_teams(self, schema_status, job_age, schema_deleted, source_deleted, should_sync):
        self._create_schema_with_job(
            schema_status=schema_status,
            job_finished_at=dt.datetime.now(dt.UTC) - job_age,
            schema_deleted=schema_deleted,
            source_deleted=source_deleted,
            should_sync=should_sync,
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

    def test_includes_still_failing_schema_past_the_renotify_window(self):
        # PostHog halted this schema itself, so it never runs again. No recent failed run
        # (30h stale) and the last email is 8 days old: the team would drop out forever
        # without the re-notify path.
        team = self._create_schema_with_job(
            schema_status=ExternalDataSchema.Status.FAILED,
            job_finished_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=30),
            last_error_notified_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=8),
            should_sync=False,
            auto_disabled_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=9),
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


@pytest.mark.parametrize(
    "count,error,omitted_count,expected_lines,expected_omitted",
    [
        (0, "Retry needed", 0, 0, 0),
        (2, "Retry needed", 0, 2, 0),
        (2, "Retry needed", 5, 2, 5),
        (30, "x" * 250, 0, 15, 15),
        (30, "x" * 250, 5, 15, 20),
        (2, "Retry\nneeded", 0, 2, 0),
    ],
)
def test_failure_digest_summary(
    count: int, error: str, omitted_count: int, expected_lines: int, expected_omitted: int
) -> None:
    item: ExternalDataFailureDigestItem = {
        "schema_name": "Charge",
        "source_type": "Stripe",
        "source_id": "source-1",
        "source_prefix": "",
        "source_url": "https://example.com/syncs",
        "url": "https://example.com/syncs?schema=Charge",
        "error": error,
        "paused": True,
    }
    summary = build_failure_digest_summary([item] * count, omitted_count)
    expected = [f"Stripe / Charge: {' '.join(error[:200].splitlines())} (paused)"] * expected_lines
    if expected_omitted:
        expected.append(f"and {expected_omitted} more")
    assert summary == "\n".join(expected)
    assert len(summary) <= 3500
