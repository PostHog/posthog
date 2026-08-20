from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.alerts.backend.destination_configs import (
    DESTINATION_TEMPLATE_IDS,
    DestinationType,
    EventKindSpec,
    build_alert_destination_config,
)
from products.alerts.backend.destinations import (
    AlertDelivery,
    alert_internal_event_delivered,
    create_alert_destination_hog_functions,
    list_active_alert_destinations,
    serialize_deliveries,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
)
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

ALLOWED_EVENT_IDS = ("$logs_alert_firing", "$logs_alert_resolved")


class TestSoftDeleteAlertDestinations(APIBaseTest):
    def _make_hog_function(
        self, *, template_id: str, alert_id: str, event_id: str = "$logs_alert_firing"
    ) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Test destination",
            type="destination",
            template_id=template_id,
            enabled=True,
            inputs_schema=[],
            inputs={},
            hog="return event",
            filters={
                "events": [{"id": event_id, "type": "events"}],
                "properties": [{"key": "alert_id", "value": alert_id}],
            },
        )

    def _make_group(self, *, template_id: str, alert_id: str) -> list[HogFunction]:
        return [
            self._make_hog_function(template_id=template_id, alert_id=alert_id, event_id=event_id)
            for event_id in ALLOWED_EVENT_IDS
        ]

    def test_deletes_alert_destination_with_matching_alert_id(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        soft_delete_alert_destinations(
            team_id=self.team.id,
            alert_id="alert-1",
            allowed_event_ids=ALLOWED_EVENT_IDS,
            hog_function_ids=[destination.id for destination in destinations],
        )

        for destination in destinations:
            destination.refresh_from_db()
            assert destination.deleted is True
            assert destination.enabled is False

    def test_rejects_partial_destination_group(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.assertRaisesRegex(ValidationError, "Delete every HogFunction"):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destinations[0].id],
            )

        assert not HogFunction.objects.filter(id__in=[destination.id for destination in destinations], deleted=True)

    def test_reports_invalid_ids_and_does_not_delete_any_destinations(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")
        other = self._make_hog_function(template_id="template-webhook", alert_id="alert-1", event_id="$unrelated_event")

        with self.assertRaises(ValidationError) as error:
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destinations[0].id, other.id],
            )

        assert isinstance(error.exception.detail, dict)
        hog_function_id_errors = error.exception.detail["hog_function_ids"]
        assert isinstance(hog_function_id_errors, list)
        assert str(hog_function_id_errors[0]) == (
            f"These HogFunctions do not belong to this alert: {other.id}. Refresh the alert and try again."
        )
        for hog_function in (*destinations, other):
            hog_function.refresh_from_db()
            assert hog_function.deleted is False
            assert hog_function.enabled is True

    def test_deletes_all_destinations_for_alert_only(self) -> None:
        slack_destination = self._make_hog_function(template_id="template-slack", alert_id="alert-1")
        webhook_destination = self._make_hog_function(template_id="template-webhook", alert_id="alert-1")
        other_alert_destination = self._make_hog_function(template_id="template-slack", alert_id="alert-2")
        non_destination = self._make_hog_function(template_id="template-webhook-custom", alert_id="alert-1")
        unrelated_event_destination = self._make_hog_function(
            template_id="template-webhook", alert_id="alert-1", event_id="$unrelated_event"
        )

        deleted_count = soft_delete_all_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=ALLOWED_EVENT_IDS
        )

        assert deleted_count == 2
        for destination in (slack_destination, webhook_destination):
            destination.refresh_from_db()
            assert destination.deleted is True
            assert destination.enabled is False

        for destination in (other_alert_destination, non_destination, unrelated_event_destination):
            destination.refresh_from_db()
            assert destination.deleted is False
            assert destination.enabled is True

    def test_rejects_empty_allowed_event_ids_without_deleting_destinations(self) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.assertRaisesRegex(ValueError, "allowed_event_ids must not be empty"):
            soft_delete_all_alert_destinations(team_id=self.team.id, alert_id="alert-1", allowed_event_ids=())

        for destination in destinations:
            destination.refresh_from_db()
            assert destination.deleted is False
            assert destination.enabled is True

    @patch("products.alerts.backend.destinations.reload_hog_functions_on_workers")
    def test_reload_happens_after_destination_delete_commits(self, reload_hog_functions_on_workers) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.captureOnCommitCallbacks(execute=True):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id for destination in destinations],
            )
            reload_hog_functions_on_workers.assert_not_called()

        reload_hog_functions_on_workers.assert_called_once_with(
            team_id=self.team.id, hog_function_ids=sorted(str(destination.id) for destination in destinations)
        )

    @patch("products.alerts.backend.destinations.reload_hog_functions_on_workers", side_effect=RuntimeError("boom"))
    def test_reload_failure_does_not_fail_committed_delete(self, _reload_hog_functions_on_workers) -> None:
        destinations = self._make_group(template_id="template-slack", alert_id="alert-1")

        with self.captureOnCommitCallbacks(execute=True):
            soft_delete_alert_destinations(
                team_id=self.team.id,
                alert_id="alert-1",
                allowed_event_ids=ALLOWED_EVENT_IDS,
                hog_function_ids=[destination.id for destination in destinations],
            )

        for destination in destinations:
            destination.refresh_from_db()
            assert destination.deleted is True
            assert destination.enabled is False


class TestAlertInternalEventDelivery(APIBaseTest):
    @patch("products.alerts.backend.destinations.capture_exception")
    @patch("products.alerts.backend.destinations.ALERT_INTERNAL_EVENT_DELIVERY_FAILURES")
    def test_expected_delivery_failure_records_metric_without_capturing_exception(
        self, delivery_failures, capture_exception
    ) -> None:
        produce_result = MagicMock()
        produce_result.get.side_effect = RuntimeError("delivery failed")

        delivered = alert_internal_event_delivered(
            produce_result,
            team_id=self.team.id,
            alert_id="alert-1",
            event_name="$logs_alert_firing",
        )

        assert delivered is False
        capture_exception.assert_not_called()
        delivery_failures.labels.assert_called_once_with(event_name="$logs_alert_firing")
        delivery_failures.labels.return_value.inc.assert_called_once_with()


class TestListActiveAlertDestinations(APIBaseTest):
    def _make_hog_function(
        self, *, template_id: str, alert_id: str, event_id: str = "$logs_alert_firing", name: str = "Test destination"
    ) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name=name,
            type="destination",
            template_id=template_id,
            enabled=True,
            inputs_schema=[],
            inputs={},
            hog="return event",
            filters={
                "events": [{"id": event_id, "type": "events"}],
                "properties": [{"key": "alert_id", "value": alert_id}],
            },
        )

    def test_list_active_alert_destinations_returns_name_and_type(self) -> None:
        self._make_hog_function(
            template_id="template-slack", alert_id="alert-1", name="Alerts — Signups (firing) → Slack #eng-alerts"
        )
        self._make_hog_function(
            template_id="template-slack", alert_id="alert-1", name="Alerts — Signups (firing) → Slack #alerts"
        )
        self._make_hog_function(template_id="template-webhook", alert_id="alert-2")
        disabled = self._make_hog_function(template_id="template-slack", alert_id="alert-1", name="Disabled")
        disabled.enabled = False
        disabled.save()
        deleted = self._make_hog_function(template_id="template-slack", alert_id="alert-1", name="Deleted")
        deleted.deleted = True
        deleted.save()

        destinations = list_active_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=("$logs_alert_firing",)
        )
        names_and_types = [(d.name, d.destination_type) for d in destinations]

        assert ("Slack #eng-alerts", "slack") in names_and_types
        assert ("Slack #alerts", "slack") in names_and_types
        assert all(isinstance(d.id, str) for d in destinations)
        assert len(destinations) == 2

    @parameterized.expand(
        [
            ("alert_name_contains_separator", "Alerts — A → B (firing) → Slack #eng-alerts", "Slack #eng-alerts"),
            ("renamed_destination_has_no_separator", "My renamed destination", "My renamed destination"),
            ("name_clipped_before_separator", "Alerts — a very long alert name…", "Alerts — a very long alert name…"),
        ]
    )
    def test_destination_name_reduces_to_its_trailing_segment(
        self, _name: str, hog_function_name: str, expected: str
    ) -> None:
        self._make_hog_function(template_id="template-slack", alert_id="alert-1", name=hog_function_name)

        destinations = list_active_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=("$logs_alert_firing",)
        )

        assert [d.name for d in destinations] == [expected]

    @parameterized.expand(
        [
            ("userinfo_credentials_are_dropped", "https://user:s3cret@hooks.example.com/hook", "hooks.example.com"),
            ("uppercase_scheme_is_matched", "HTTPS://hooks.example.com/services/secret", "hooks.example.com"),
            ("non_http_scheme_is_matched", "ftp://hooks.example.com/secret", "hooks.example.com"),
            ("port_is_dropped", "https://hooks.example.com:8443/secret", "hooks.example.com"),
        ]
    )
    def test_receipt_names_keep_only_the_url_host(self, _name: str, url: str, expected_host: str) -> None:
        self._make_hog_function(
            template_id="template-webhook", alert_id="alert-1", name=f"Alerts — X (firing) → Webhook {url}"
        )

        destinations = list_active_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=("$logs_alert_firing",)
        )

        assert [d.name for d in destinations] == [f"Webhook {expected_host}"]

    def test_list_active_alert_destinations_strips_webhook_urls_to_host(self) -> None:
        # Webhook names embed the full URL, whose path is the channel credential —
        # receipts surface in the API and tooltip, so only the host may survive.
        self._make_hog_function(
            template_id="template-webhook",
            alert_id="alert-1",
            name="Alerts — Signups (firing) → Webhook https://discord.com/api/webhooks/123/secret-token",
        )

        destinations = list_active_alert_destinations(
            team_id=self.team.id, alert_id="alert-1", allowed_event_ids=("$logs_alert_firing",)
        )

        assert [d.name for d in destinations] == ["Webhook discord.com"]


class TestSerializeDeliveries(APIBaseTest):
    def test_serialize_deliveries_roundtrips_dataclass_fields(self) -> None:
        delivery = AlertDelivery(channel="email", target="a@example.com", at="2026-08-11T00:00:00+00:00")
        result = serialize_deliveries([delivery])

        assert result == [
            {
                "channel": "email",
                "target": "a@example.com",
                "target_id": None,
                "template": None,
                "status": "accepted",
                "at": "2026-08-11T00:00:00+00:00",
            }
        ]

    def test_serialize_deliveries_with_all_fields(self) -> None:
        delivery = AlertDelivery(
            channel="hog_function",
            target="Slack #general",
            target_id="hf-123",
            template="slack",
            status="accepted",
            at="2026-08-11T01:00:00+00:00",
        )
        result = serialize_deliveries([delivery])

        assert result == [
            {
                "channel": "hog_function",
                "target": "Slack #general",
                "target_id": "hf-123",
                "template": "slack",
                "status": "accepted",
                "at": "2026-08-11T01:00:00+00:00",
            }
        ]


class TestCreateAlertDestinationSecretInputs(APIBaseTest):
    @parameterized.expand(
        [
            (
                "webhook",
                DestinationType.WEBHOOK,
                "url",
                [{"key": "url", "type": "string"}, {"key": "body", "type": "json"}],
                "https://hooks.example.com/T123/secret-path",
            ),
            (
                "discord",
                DestinationType.DISCORD,
                "webhookUrl",
                [{"key": "webhookUrl", "type": "string"}, {"key": "content", "type": "string"}],
                "https://discord.com/api/webhooks/123/secret-token",
            ),
            (
                "teams",
                DestinationType.TEAMS,
                "webhookUrl",
                [{"key": "webhookUrl", "type": "string"}, {"key": "text", "type": "string"}],
                "https://example.webhook.office.com/webhookb2/secret-path/IncomingWebhook/abc/def",
            ),
        ]
    )
    def test_created_destination_stores_webhook_url_as_secret_input(
        self,
        _name: str,
        destination_type: DestinationType,
        url_key: str,
        inputs_schema: list[dict],
        webhook_url: str,
    ) -> None:
        HogFunctionTemplate.objects.get_or_create(
            template_id=DESTINATION_TEMPLATE_IDS[destination_type],
            defaults={
                "sha": "1.0.0",
                "name": destination_type.label,
                "description": "Test template",
                "code": "return event",
                "code_language": "hog",
                "inputs_schema": inputs_schema,
                "type": "destination",
                "status": "stable",
                "category": ["Integrations"],
                "free": True,
            },
        )
        spec = EventKindSpec(
            event_id="$logs_alert_firing",
            display_kind="firing",
            header="Alert firing",
            details=(),
            primary_action_url="https://example.com/alerts",
            primary_action_label="View alert",
            webhook_body={},
        )
        config = build_alert_destination_config(
            team=self.team,
            spec=spec,
            alert_id="alert-1",
            alert_name="Test alert",
            data={"type": destination_type, "webhook_url": webhook_url},
            slack_context_elements=(),
        )

        created = create_alert_destination_hog_functions([config], request=MagicMock(user=self.user))

        assert len(created) == 1
        hog_function = created[0]
        assert url_key not in (hog_function.inputs or {})
        assert (hog_function.encrypted_inputs or {})[url_key]["value"] == webhook_url
        assert "secret" not in (hog_function.name or "")
        schema_by_key = {schema["key"]: schema for schema in hog_function.inputs_schema or []}
        assert schema_by_key[url_key]["secret"] is True


class TestHardenAlertDestinationSecrets(APIBaseTest):
    def _legacy_row(self, *, event_id: str, name: str) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name=name,
            type="internal_destination",
            template_id="template-webhook",
            enabled=True,
            hog="return event",
            inputs_schema=[{"key": "url", "type": "string"}, {"key": "body", "type": "json"}],
            inputs={"url": {"value": "https://hooks.example.com/T123/secret"}, "body": {"value": {}}},
            filters={
                "events": [{"id": event_id, "type": "events"}],
                "properties": [{"key": "alert_id", "value": "alert-1"}],
            },
        )

    def test_backfill_moves_url_to_encrypted_inputs_and_strips_names(self) -> None:
        managed = self._legacy_row(
            event_id="$billing_alert_firing",
            name="Billing alert (firing) → Webhook https://hooks.example.com/T123/secret",
        )
        legacy_insight = self._legacy_row(
            event_id="$insight_alert_firing",
            name="Webhook https://hooks.example.com/T123/secret",
        )

        call_command("harden_alert_destination_secrets")
        managed.refresh_from_db()
        assert (managed.inputs or {})["url"]["value"] == "https://hooks.example.com/T123/secret"
        assert (managed.name or "").endswith("Webhook https://hooks.example.com/T123/secret")

        call_command("harden_alert_destination_secrets", "--live")

        managed.refresh_from_db()
        assert managed.name == "Billing alert (firing) → Webhook hooks.example.com"
        assert "url" not in (managed.inputs or {})
        assert (managed.encrypted_inputs or {})["url"]["value"] == "https://hooks.example.com/T123/secret"
        assert (managed.inputs or {})["body"] == {"value": {}}
        assert managed.enabled is True

        legacy_insight.refresh_from_db()
        assert (legacy_insight.inputs or {})["url"]["value"] == "https://hooks.example.com/T123/secret"
        assert legacy_insight.name == "Webhook https://hooks.example.com/T123/secret"

    def test_backfill_keeps_a_url_the_user_put_in_the_alert_name(self) -> None:
        row = self._legacy_row(
            event_id="$logs_alert_firing",
            name="Logs alert on https://api.example.com/checkout (firing) → Webhook https://hooks.example.com/T123/secret",
        )

        call_command("harden_alert_destination_secrets", "--live")

        row.refresh_from_db()
        assert row.name == "Logs alert on https://api.example.com/checkout (firing) → Webhook hooks.example.com"
