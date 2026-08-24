from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.alerts.backend.destination_configs import (
    AlertDestinationConfig,
    EventKindSpec,
    build_alert_destination_config,
)
from products.alerts.backend.destinations import (
    AlertDelivery,
    alert_internal_event_delivered,
    create_alert_destination_hog_functions,
    delete_shared_alert_destinations,
    get_or_create_shared_alert,
    list_active_alert_destinations,
    serialize_deliveries,
    soft_delete_alert_destinations,
    soft_delete_all_alert_destinations,
)
from products.alerts.backend.models.shared_alert import AlertDestination, AlertProduct, AlertSharedIdentity
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


class TestSharedAlertDualWrite(APIBaseTest):
    """The dual-write path that stamps explicit ownership onto HogFunctions.

    Phase 3 of the RFC: writers still fill the legacy `alert_id`/event filters,
    but they also copy the relationship onto the new `alert_destination` /
    `alert_event_kind` columns so routing can migrate behind the scenes.
    """

    def _build_config(self, *, event_kind: str) -> AlertDestinationConfig:
        spec = EventKindSpec(
            event_id=f"$logs_alert_{event_kind}",
            display_kind=event_kind,
            header=f"Alert is {event_kind}",
            details=(),
            primary_action_url="",
            primary_action_label="View",
            webhook_body={},
            product_label="Test",
        )
        return build_alert_destination_config(
            team=self.team,
            spec=spec,
            alert_id="alert-1",
            alert_name="Signups",
            data={"type": "webhook", "webhook_url": "https://example.com/hook"},
            slack_context_elements=(),
            alert_event_kind=event_kind,
        )

    def test_creates_alert_destination_and_stamps_ownership(self) -> None:
        shared_alert = AlertSharedIdentity.objects.create(
            product=AlertProduct.LOGS,
            organization_id=self.team.organization_id,
            execution_team_id=self.team.id,
        )

        configs = [self._build_config(event_kind="firing"), self._build_config(event_kind="resolved")]
        hog_functions = create_alert_destination_hog_functions(
            configs,
            request=MagicMock(user=self.user),
            shared_alert=shared_alert,
            destination_name="Webhook example.com",
        )

        destination = AlertDestination.objects.get(shared_alert=shared_alert)
        assert destination.type == "webhook"
        assert destination.name == "Webhook example.com"
        assert len(hog_functions) == 2
        for hog_function, config in zip(hog_functions, configs):
            assert hog_function.alert_destination_id == destination.id
            assert hog_function.alert_event_kind == config.alert_event_kind
            # Filter-based routing keeps working until runtime switches over.
            assert hog_function.filters == {
                "events": [{"id": "$logs_alert_firing", "type": "events"}],
                "properties": [{"key": "alert_id", "value": "alert-1", "operator": "exact", "type": "event"}],
            }

    def test_creates_hog_functions_without_shared_alert_write_path(self) -> None:
        hog_functions = create_alert_destination_hog_functions(
            [self._build_config(event_kind="firing")],
            request=MagicMock(user=self.user),
        )

        assert len(hog_functions) == 1
        assert hog_functions[0].alert_destination_id is None
        assert hog_functions[0].alert_event_kind is None
        assert not AlertDestination.objects.exists()

    def test_rejects_duplicate_event_kinds_in_one_logical_destination(self) -> None:
        shared_alert = AlertSharedIdentity.objects.create(
            product=AlertProduct.LOGS,
            organization_id=self.team.organization_id,
            execution_team_id=self.team.id,
        )

        configs = [self._build_config(event_kind="firing"), self._build_config(event_kind="firing")]
        with self.assertRaisesRegex(ValidationError, "alert_event_kind values must be unique"):
            create_alert_destination_hog_functions(
                configs,
                request=MagicMock(user=self.user),
                shared_alert=shared_alert,
                destination_name="Webhook example.com",
            )

    def test_get_or_create_shared_alert_updates_execution_team(self) -> None:
        shared_alert = AlertSharedIdentity.objects.create(
            product=AlertProduct.BILLING,
            organization_id=self.team.organization_id,
            execution_team_id=None,
        )

        ret = get_or_create_shared_alert(
            alert_id=shared_alert.id,
            product=AlertProduct.BILLING,
            organization_id=self.team.organization_id,
            execution_team_id=self.team.id,
        )

        assert ret.id == shared_alert.id
        ret.refresh_from_db()
        assert ret.execution_team_id == self.team.id

    def test_delete_shared_alert_destinations_soft_deletes_executors_and_clears_rows(self) -> None:
        shared_alert = AlertSharedIdentity.objects.create(
            product=AlertProduct.LOGS,
            organization_id=self.team.organization_id,
            execution_team_id=self.team.id,
        )
        configs = [self._build_config(event_kind="firing"), self._build_config(event_kind="resolved")]
        hog_functions = create_alert_destination_hog_functions(
            configs,
            request=MagicMock(user=self.user),
            shared_alert=shared_alert,
            destination_name="Webhook example.com",
        )

        with self.captureOnCommitCallbacks(execute=True):
            delete_shared_alert_destinations(shared_alert=shared_alert)

        for hog_function in hog_functions:
            hog_function.refresh_from_db()
            assert hog_function.deleted is True
            assert hog_function.enabled is False
        assert not AlertDestination.objects.filter(id=shared_alert.id).exists()
