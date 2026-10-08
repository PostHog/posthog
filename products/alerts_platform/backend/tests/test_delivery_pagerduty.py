import json
from datetime import datetime
from typing import Any, cast

import pytest

from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from products.alerts_platform.backend.delivery.message import AlertMessage, MessageDetail
from products.alerts_platform.backend.delivery.pagerduty import PagerDutyTransport, pagerduty_body
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    IncidentAction,
    PagerDutySeverity,
)
from products.alerts_platform.backend.tests.delivery_messages import alert_message, announced_transition, pinned_post

ROUTING_KEY = "not-a-real-routing-key-0000000000"
TARGET = cast(AlertDestinationData, {"type": "pagerduty", "pagerduty_routing_key": ROUTING_KEY})


def _message(action: IncidentAction | None, **transition: Any) -> AlertMessage:
    kind = AlertEventKind.RESOLVED if action == IncidentAction.RESOLVE else AlertEventKind.FIRING
    return alert_message(
        details=(MessageDetail(label="Value", value="312"),),
        transition=announced_transition(kind, **transition),
        incident_action=action,
    )


class TestPagerDutyBody(SimpleTestCase):
    def test_a_trigger_names_the_platform_and_its_firing(self) -> None:
        body = pagerduty_body(
            _message(IncidentAction.TRIGGER), routing_key=ROUTING_KEY, severity=PagerDutySeverity.CRITICAL
        )

        assert body == {
            "routing_key": ROUTING_KEY,
            "event_action": "trigger",
            "dedup_key": "cfg-1::2026-09-30T09:00:00+00:00",
            "client": "PostHog",
            "payload": {
                "summary": "API errors is firing",
                "source": "PostHog alerts platform",
                "severity": "critical",
                "timestamp": "2026-09-30T10:00:00+00:00",
                "custom_details": {
                    "Value": "312",
                    "delivered_by": "PostHog alerts platform",
                    "configuration_id": "cfg-1",
                },
            },
        }

    def test_a_resolve_addresses_the_incident_its_trigger_opened(self) -> None:
        def key(action: IncidentAction, **transition: Any) -> str:
            body = pagerduty_body(
                _message(action, **transition), routing_key=ROUTING_KEY, severity=PagerDutySeverity.ERROR
            )
            return body["dedup_key"]

        trigger = key(IncidentAction.TRIGGER)
        # A naive start from ClickHouse is the same instant, and must not open a second incident.
        assert key(IncidentAction.RESOLVE, episode_started_at=datetime(2026, 9, 30, 9)) == trigger
        assert key(IncidentAction.TRIGGER, grouping_key="search") != trigger
        assert key(IncidentAction.TRIGGER, episode_started_at=datetime(2026, 9, 30, 11)) != trigger

    def test_an_oversized_key_stays_within_what_pagerduty_accepts(self) -> None:
        body = pagerduty_body(
            _message(IncidentAction.TRIGGER, grouping_key="g" * 300),
            routing_key=ROUTING_KEY,
            severity=PagerDutySeverity.ERROR,
        )

        assert len(body["dedup_key"]) <= 255


class TestPagerDutyTransport(SimpleTestCase):
    @parameterized.expand(
        [
            ("unset", None, "https://events.pagerduty.com/v2/enqueue"),
            ("us", "us", "https://events.pagerduty.com/v2/enqueue"),
            ("eu", "eu", "https://events.eu.pagerduty.com/v2/enqueue"),
        ]
    )
    def test_the_region_picks_the_endpoint(self, _name: str, region: str | None, endpoint: str) -> None:
        target = cast(AlertDestinationData, {**TARGET, **({"pagerduty_region": region} if region else {})})

        with pinned_post(202) as adapter:
            handle = PagerDutyTransport().deliver(team_id=2, target=target, message=_message(IncidentAction.TRIGGER))

        sent = json.loads(adapter.sent[-1].body or b"")
        assert handle is None
        assert adapter.sent[-1].url == endpoint
        assert sent["routing_key"] == ROUTING_KEY
        # The HogFunction path's default, so one firing pages at one severity on both paths.
        assert sent["payload"]["severity"] == "critical"

    @parameterized.expand(
        [
            ("bad_request", 400, None),
            ("throttled", 429, None),
            ("unreachable", 0, requests.ConnectionError(f"body was {{'routing_key': '{ROUTING_KEY}'}}")),
        ]
    )
    def test_a_failed_send_never_repeats_the_routing_key(
        self, _name: str, status: int, error: Exception | None
    ) -> None:
        with pinned_post(status, error):
            with pytest.raises(DeliveryError) as raised:
                PagerDutyTransport().deliver(team_id=2, target=TARGET, message=_message(IncidentAction.TRIGGER))

        assert ROUTING_KEY not in str(raised.value)
        assert raised.value.__cause__ is None

    @parameterized.expand(
        [
            ("no_incident_action", TARGET, None),
            ("no_routing_key", cast(AlertDestinationData, {"type": "pagerduty"}), IncidentAction.TRIGGER),
            (
                "unknown_region",
                cast(AlertDestinationData, {**TARGET, "pagerduty_region": "apac"}),
                IncidentAction.TRIGGER,
            ),
        ]
    )
    def test_an_event_pagerduty_cannot_route_is_refused_before_sending(
        self, _name: str, target: AlertDestinationData, action: IncidentAction | None
    ) -> None:
        with pinned_post() as adapter:
            with pytest.raises(DeliveryError):
                PagerDutyTransport().deliver(team_id=2, target=target, message=_message(action))

        assert adapter.sent == []

    def test_the_thread_store_never_holds_the_routing_key(self) -> None:
        assert ROUTING_KEY not in PagerDutyTransport().channel_target(TARGET)
