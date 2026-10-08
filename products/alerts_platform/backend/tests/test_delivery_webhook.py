from datetime import datetime
from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.security.pinned_requests import SSRFBlockedError

from products.alerts_platform.backend.delivery.dispatch import deliver
from products.alerts_platform.backend.delivery.message import MessageDetail
from products.alerts_platform.backend.delivery.thread_store import DatabaseThreadStore
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.delivery.webhook import WebhookTransport, alertmanager_body
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    EvaluationAnnouncement,
)
from products.alerts_platform.backend.models import PlatformAlertConfiguration, PlatformAlertThread
from products.alerts_platform.backend.tests.delivery_messages import alert_message, announced_transition, pinned_post

SECRET_URL = "https://hooks.example.com/services/T000/B000/not-a-real-token"
TARGET = cast(AlertDestinationData, {"type": "webhook", "webhook_url": SECRET_URL})


class TestAlertmanagerBody(SimpleTestCase):
    @override_settings(SITE_URL="https://us.posthog.com")
    def test_a_firing_is_one_alertmanager_alert(self) -> None:
        message = alert_message(
            headline="API errors is firing",
            details=(MessageDetail(label="Value", value="312"), MessageDetail(label="Threshold", value="> 300")),
            transition=announced_transition(
                value=312.0, grouping_key="checkout", labels={"service": "checkout", "alertname": "spoofed"}
            ),
        )

        body = alertmanager_body(message)

        labels = {
            "service": "checkout",
            "alertname": "API errors",
            "posthog_configuration_id": "cfg-1",
            "posthog_event_kind": "firing",
        }
        annotations = {"summary": "API errors is firing", "description": "Value: 312\nThreshold: > 300", "value": "312"}
        assert body == {
            "version": "4",
            "groupKey": "cfg-1:checkout",
            "truncatedAlerts": 0,
            "status": "firing",
            "receiver": "posthog",
            "groupLabels": {"alertname": "API errors", "posthog_configuration_id": "cfg-1"},
            "commonLabels": labels,
            "commonAnnotations": annotations,
            "externalURL": "https://us.posthog.com",
            "alerts": [
                {
                    "status": "firing",
                    "labels": labels,
                    "annotations": annotations,
                    "startsAt": "2026-09-30T09:00:00+00:00",
                    "endsAt": "0001-01-01T00:00:00Z",
                    "generatorURL": "",
                    "fingerprint": body["alerts"][0]["fingerprint"],
                }
            ],
        }

    @parameterized.expand(
        [
            ("resolved", AlertEventKind.RESOLVED, "resolved", "2026-09-30T09:00:00+00:00", "2026-09-30T10:00:00+00:00"),
            ("errored", AlertEventKind.ERRORED, "firing", "2026-09-30T10:00:00+00:00", "0001-01-01T00:00:00Z"),
            ("broken", AlertEventKind.BROKEN, "firing", "2026-09-30T10:00:00+00:00", "0001-01-01T00:00:00Z"),
        ]
    )
    def test_each_kind_maps_onto_an_alertmanager_status(
        self, _name: str, kind: AlertEventKind, status: str, starts_at: str, ends_at: str
    ) -> None:
        episode = (
            None
            if kind in (AlertEventKind.ERRORED, AlertEventKind.BROKEN)
            else announced_transition().episode_started_at
        )
        body = alertmanager_body(alert_message(transition=announced_transition(kind, episode_started_at=episode)))

        alert = body["alerts"][0]
        assert (body["status"], alert["status"]) == (status, status)
        assert (alert["startsAt"], alert["endsAt"]) == (starts_at, ends_at)
        assert alert["labels"]["posthog_event_kind"] == kind.value

    def test_a_naive_timestamp_from_clickhouse_is_sent_as_utc(self) -> None:
        naive = announced_transition(
            AlertEventKind.RESOLVED,
            episode_started_at=datetime(2026, 9, 30, 9),
            occurred_at=datetime(2026, 9, 30, 10),
        )

        alert = alertmanager_body(alert_message(transition=naive))["alerts"][0]

        assert (alert["startsAt"], alert["endsAt"]) == ("2026-09-30T09:00:00+00:00", "2026-09-30T10:00:00+00:00")

    def test_a_resolve_closes_its_own_firing_and_nothing_else(self) -> None:
        def fingerprint(kind: AlertEventKind, grouping_key: str = "checkout") -> str:
            transition = announced_transition(kind, grouping_key=grouping_key)
            return alertmanager_body(alert_message(transition=transition))["alerts"][0]["fingerprint"]

        # A receiver pairs a resolve with its firing by fingerprint, so the two must match.
        assert fingerprint(AlertEventKind.FIRING) == fingerprint(AlertEventKind.RESOLVED)
        # A failed check sent as firing would otherwise be closed by the breach's resolve.
        assert fingerprint(AlertEventKind.ERRORED) != fingerprint(AlertEventKind.FIRING)
        assert fingerprint(AlertEventKind.FIRING, "search") != fingerprint(AlertEventKind.FIRING)


class TestWebhookTransport(SimpleTestCase):
    @parameterized.expand([("ok", 200), ("accepted", 202)])
    def test_any_success_status_is_a_delivery(self, _name: str, status: int) -> None:
        with pinned_post(status) as adapter:
            handle = WebhookTransport().deliver(team_id=2, target=TARGET, message=alert_message())

        assert handle is None
        assert adapter.sent[-1].headers["X-PostHog-Webhook-Version"] == "2"

    def test_a_redirect_is_refused_without_reading_its_body(self) -> None:
        with pinned_post(302, headers={"Location": "https://elsewhere.example.com/"}, body=b"x" * 1_000_000) as adapter:
            with pytest.raises(DeliveryError):
                WebhookTransport().deliver(team_id=2, target=TARGET, message=alert_message())

        assert len(adapter.sent) == 1
        assert adapter.body.bytes_read == 0

    def test_a_plain_http_url_is_refused_before_anything_is_sent(self) -> None:
        target = cast(AlertDestinationData, {"type": "webhook", "webhook_url": "http://hooks.example.com/alerts"})

        with pinned_post() as adapter:
            with pytest.raises(DeliveryError):
                WebhookTransport().deliver(team_id=2, target=target, message=alert_message())

        assert adapter.sent == []

    @parameterized.expand(
        [
            ("refused", 410, None),
            ("redirected", 302, None),
            ("unreachable", 0, requests.ConnectionError(f"Max retries exceeded with url: {SECRET_URL}")),
            ("blocked", 0, SSRFBlockedError(f"{SECRET_URL} resolves to a private address")),
        ]
    )
    def test_a_failed_send_never_repeats_the_url(self, _name: str, status: int, error: Exception | None) -> None:
        with pinned_post(status, error):
            with pytest.raises(DeliveryError) as raised:
                WebhookTransport().deliver(team_id=2, target=TARGET, message=alert_message())

        # The URL is the credential. Temporal records the error and its cause chain.
        assert "not-a-real-token" not in str(raised.value)
        assert raised.value.__cause__ is None


class TestWebhookThreads(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={},
                threshold_count=10,
                threshold_operator="above",
                window_minutes=5,
                check_interval_minutes=10,
            )

    def _deliver(self, kind: AlertEventKind, evaluation_key: str) -> Any:
        announcement = EvaluationAnnouncement(
            configuration_id=str(self.configuration.id),
            alert_name="API errors",
            consecutive_failures=0,
            transitions=(announced_transition(kind),),
        )
        with pinned_post() as adapter, patch("products.alerts_platform.backend.delivery.dispatch.record_delivery"):
            deliver(
                transport=WebhookTransport(),
                thread_store=DatabaseThreadStore(self.team.id),
                team_id=self.team.id,
                configuration_id=str(self.configuration.id),
                evaluation_key=evaluation_key,
                target=TARGET,
                announcement=announcement,
            )
        return adapter

    def test_a_retry_posts_once_although_the_webhook_returns_nothing_to_reply_to(self) -> None:
        assert len(self._deliver(AlertEventKind.FIRING, "eval-1").sent) == 1
        assert len(self._deliver(AlertEventKind.FIRING, "eval-1").sent) == 0
        assert len(self._deliver(AlertEventKind.RESOLVED, "eval-2").sent) == 1

        with team_scope(self.team.id):
            thread = PlatformAlertThread.objects.get(configuration_id=self.configuration.id)
        assert thread.delivered_evaluation_keys == ["eval-1", "eval-2"]
        assert thread.external_ref == {}
        assert "not-a-real-token" not in thread.channel_target
