from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from products.alerts_platform.backend.delivery.dispatch import deliver
from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.telemetry import record_delivery
from products.alerts_platform.backend.delivery.thread_store import NullThreadStore, ThreadClaim, ThreadKey
from products.alerts_platform.backend.delivery.transport import DeliveryError, MessageHandle
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
)

TARGET = cast(AlertDestinationData, {"type": "slack", "slack_workspace_id": 1, "slack_channel_id": "C-ENG"})
FIRST_FIRING = datetime(2026, 9, 30, 9, tzinfo=UTC)
SECOND_FIRING = datetime(2026, 9, 30, 17, tzinfo=UTC)


def _transition(
    kind: AlertEventKind = AlertEventKind.FIRING,
    episode_started_at: datetime | None = FIRST_FIRING,
    grouping_key: str = "",
) -> AnnouncedTransition:
    return AnnouncedTransition(
        grouping_key=grouping_key,
        kind=kind,
        episode_started_at=episode_started_at,
        value=300.0,
        labels={},
        condition={"threshold_count": 100, "threshold_operator": "above"},
        source_config={},
        error_message=None,
        occurred_at=FIRST_FIRING,
    )


def _announcement(
    kind: AlertEventKind = AlertEventKind.FIRING, episode_started_at: datetime | None = FIRST_FIRING
) -> EvaluationAnnouncement:
    return EvaluationAnnouncement(
        configuration_id="cfg-1",
        alert_name="API errors",
        consecutive_failures=0,
        transitions=(_transition(kind, episode_started_at),),
    )


class FakeTransport:
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
    """Keeps what a real store would keep, so the key dispatch builds is observable."""

    def __init__(self) -> None:
        self.threads: dict[ThreadKey, MessageHandle] = {}
        self.delivered_keys: dict[ThreadKey, list[str]] = {}
        self._claimed: dict[str, ThreadKey] = {}

    def claim(self, key: ThreadKey, evaluation_key: str) -> ThreadClaim | None:
        if evaluation_key in self.delivered_keys.get(key, []):
            return None
        thread_id = str(len(self._claimed))
        self._claimed[thread_id] = key
        return ThreadClaim(
            thread_id=thread_id,
            evaluation_key=evaluation_key,
            handle=self.threads.get(key),
            claimed_at=timezone.now(),
        )

    def delivered(self, claim: ThreadClaim, handle: MessageHandle | None) -> None:
        key = self._claimed[claim.thread_id]
        self.delivered_keys.setdefault(key, []).append(claim.evaluation_key)
        if handle is not None and key not in self.threads:
            self.threads[key] = handle

    @property
    def remembered(self) -> list[MessageHandle]:
        return list(self.threads.values())


class TestDeliveryDispatch(SimpleTestCase):
    def _deliver(
        self, transport: FakeTransport, store: Any, announcement: Any = None, evaluation_key: str = "eval-1"
    ) -> Any:
        with patch("products.alerts_platform.backend.delivery.dispatch.record_delivery") as recorded:
            deliver(
                transport=transport,
                thread_store=store,
                team_id=2,
                configuration_id="cfg-1",
                evaluation_key=evaluation_key,
                target=TARGET,
                announcement=announcement or _announcement(),
            )
        return recorded

    def test_a_first_message_is_remembered_so_a_resolve_can_reply_to_it(self) -> None:
        store = RecordingThreadStore()
        transport = FakeTransport()

        self._deliver(transport, store)

        assert [handle.external_ref for handle in store.remembered] == [{"ts": "1"}]

    def test_a_refused_send_is_counted_rather_than_passed_over(self) -> None:
        transport = FakeTransport(error=DeliveryError("nope"))

        with patch("products.alerts_platform.backend.delivery.dispatch.record_delivery") as recorded:
            with pytest.raises(DeliveryError):
                deliver(
                    transport=transport,
                    thread_store=NullThreadStore(),
                    team_id=2,
                    configuration_id="cfg-1",
                    evaluation_key="eval-1",
                    target=TARGET,
                    announcement=_announcement(),
                )

        assert recorded.call_args.kwargs["succeeded"] is False

    def test_a_resolve_replies_under_its_own_firing_rather_than_an_earlier_one(self) -> None:
        store = RecordingThreadStore()
        first = FakeTransport(handle=MessageHandle(external_ref={"ts": "morning"}))
        self._deliver(first, store, _announcement(AlertEventKind.FIRING, FIRST_FIRING), "eval-1")

        resolve = FakeTransport(handle=MessageHandle(external_ref={"ts": "resolve"}))
        self._deliver(resolve, store, _announcement(AlertEventKind.RESOLVED, FIRST_FIRING), "eval-2")

        second = FakeTransport(handle=MessageHandle(external_ref={"ts": "evening"}))
        self._deliver(second, store, _announcement(AlertEventKind.FIRING, SECOND_FIRING), "eval-3")

        assert [handle for _, handle in resolve.sends] == [MessageHandle(external_ref={"ts": "morning"})]
        assert [handle for _, handle in second.sends] == [None]

    def test_two_groups_firing_together_do_not_share_a_thread(self) -> None:
        store = RecordingThreadStore()
        transport = FakeTransport()
        announcement = EvaluationAnnouncement(
            configuration_id="cfg-1",
            alert_name="API errors",
            consecutive_failures=0,
            transitions=(_transition(grouping_key="checkout"), _transition(grouping_key="search")),
        )

        self._deliver(transport, store, announcement)

        assert [handle for _, handle in transport.sends] == [None, None]
        assert len(store.threads) == 2

    def test_a_retried_evaluation_does_not_send_a_second_copy(self) -> None:
        store = RecordingThreadStore()
        self._deliver(FakeTransport(), store, evaluation_key="eval-1")

        retry = FakeTransport()
        self._deliver(retry, store, evaluation_key="eval-1")

        assert retry.sends == []

    def test_a_check_that_never_fired_starts_no_conversation(self) -> None:
        store = RecordingThreadStore()
        transport = FakeTransport()

        self._deliver(transport, store, _announcement(AlertEventKind.ERRORED, None))

        assert store.threads == {}

    def test_a_provider_outage_is_counted_as_a_failed_delivery(self) -> None:
        transport = FakeTransport(error=ConnectionError("slack unreachable"))

        with patch("products.alerts_platform.backend.delivery.dispatch.record_delivery") as recorded:
            with pytest.raises(ConnectionError):
                deliver(
                    transport=transport,
                    thread_store=NullThreadStore(),
                    team_id=2,
                    configuration_id="cfg-1",
                    evaluation_key="eval-1",
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
        with patch("products.alerts_platform.backend.delivery.telemetry.get_producer") as producer:
            record_delivery(team_id=2, configuration_id="cfg-1", provider="slack", succeeded=True)

        payload = producer.return_value.produce.call_args.kwargs["data"]
        assert payload["app_source"] == "alert"
        assert payload["app_source_id"] == "cfg-1"
        assert (payload["metric_kind"], payload["metric_name"]) == ("success", "succeeded")

    def test_a_broken_producer_does_not_fail_a_send_that_already_happened(self) -> None:
        with patch(
            "products.alerts_platform.backend.delivery.telemetry.get_producer", side_effect=RuntimeError("down")
        ):
            record_delivery(team_id=2, configuration_id="cfg-1", provider="slack", succeeded=True)
