from typing import Any, cast

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase

from products.alerts.backend.delivery.dispatch import deliver
from products.alerts.backend.delivery.message import AlertMessage
from products.alerts.backend.delivery.telemetry import record_delivery
from products.alerts.backend.delivery.thread_store import NullThreadStore
from products.alerts.backend.delivery.transport import REPLY, DeliveryError, MessageHandle
from products.alerts.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    EvaluationAnnouncement,
    GroupTransition,
    Notification,
)

TARGET = cast(AlertDestinationData, {"type": "slack", "slack_workspace_id": 1, "slack_channel_id": "C-ENG"})


def _announcement(kind: AlertEventKind = AlertEventKind.FIRING) -> EvaluationAnnouncement:
    transition = GroupTransition(
        grouping_key="",
        kind=kind,
        previous_state="not_firing",
        state="firing",
        value=300.0,
        labels={},
        condition={"threshold_count": 100, "threshold_operator": "above"},
        source_config={},
        error_message=None,
    )
    return EvaluationAnnouncement(
        alert_name="API errors",
        consecutive_failures=0,
        notifications=(Notification(notification_key="", transitions=(transition,)),),
    )


class FakeTransport:
    capabilities = frozenset({REPLY})
    provider = "fake"

    def __init__(self, handle: MessageHandle | None = None, error: Exception | None = None) -> None:
        self.handle = handle or MessageHandle(external_ref={"ts": "1"})
        self.error = error
        self.sends: list[tuple[AlertMessage, MessageHandle | None]] = []

    def channel_target(self, target: AlertDestinationData) -> str:
        return "C-ENG"

    def deliver(
        self, *, team_id: int, target: AlertDestinationData, message: AlertMessage, in_reply_to: Any = None
    ) -> MessageHandle | None:
        self.sends.append((message, in_reply_to))
        if self.error:
            raise self.error
        return self.handle


class RecordingThreadStore(NullThreadStore):
    def __init__(self) -> None:
        self.remembered: list[MessageHandle] = []

    def remember(self, *, handle: MessageHandle, **_: Any) -> None:
        self.remembered.append(handle)


class TestDeliveryDispatch(SimpleTestCase):
    def _deliver(self, transport: FakeTransport, store: Any) -> Any:
        with patch("products.alerts.backend.delivery.dispatch.record_delivery") as recorded:
            deliver(
                transport=transport,
                thread_store=store,
                team_id=2,
                configuration_id="cfg-1",
                target=TARGET,
                announcement=_announcement(),
            )
        return recorded

    def test_a_first_message_is_remembered_so_a_resolve_can_reply_to_it(self) -> None:
        store = RecordingThreadStore()
        transport = FakeTransport()

        self._deliver(transport, store)

        assert [handle.external_ref for handle in store.remembered] == [{"ts": "1"}]

    def test_a_refused_send_is_counted_rather_than_passed_over(self) -> None:
        transport = FakeTransport(error=DeliveryError("nope"))

        with patch("products.alerts.backend.delivery.dispatch.record_delivery") as recorded:
            with pytest.raises(DeliveryError):
                deliver(
                    transport=transport,
                    thread_store=NullThreadStore(),
                    team_id=2,
                    configuration_id="cfg-1",
                    target=TARGET,
                    announcement=_announcement(),
                )

        assert recorded.call_args.kwargs["succeeded"] is False

    def test_a_store_that_remembers_nothing_still_delivers(self) -> None:
        transport = FakeTransport()

        self._deliver(transport, NullThreadStore())

        assert [handle for _, handle in transport.sends] == [None]


class TestDeliveryTelemetry(SimpleTestCase):
    def test_an_outcome_is_keyed_to_alerts_rather_than_to_hog_functions(self) -> None:
        with patch("products.alerts.backend.delivery.telemetry.get_producer") as producer:
            record_delivery(team_id=2, configuration_id="cfg-1", provider="slack", succeeded=True)

        payload = producer.return_value.produce.call_args.kwargs["data"]
        assert payload["app_source"] == "alert"
        assert payload["app_source_id"] == "cfg-1"
        assert (payload["metric_kind"], payload["metric_name"]) == ("success", "succeeded")

    def test_a_broken_producer_does_not_fail_a_send_that_already_happened(self) -> None:
        with patch("products.alerts.backend.delivery.telemetry.get_producer", side_effect=RuntimeError("down")):
            record_delivery(team_id=2, configuration_id="cfg-1", provider="slack", succeeded=True)
