import json
from dataclasses import replace
from typing import Any, cast

import pytest

from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from products.alerts_platform.backend.delivery.incident_io import IncidentIoTransport
from products.alerts_platform.backend.delivery.message import AlertMessage
from products.alerts_platform.backend.delivery.transport import DeliveryError, DestinationRefused
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertEventKind,
    IncidentAction,
    MessageDetail,
)
from products.alerts_platform.backend.tests.delivery_messages import (
    ALERT_URL,
    alert_message,
    announced_transition,
    pinned_post,
)

SOURCE_ID = "01GW2G3V0S59R238FAHPDS1R66"
SECRET = "not-a-real-incident-io-secret"
TARGET = cast(
    AlertDestinationData,
    {"type": "incident_io", "incident_io_alert_source_config_id": SOURCE_ID, "incident_io_secret": SECRET},
)


def _message(action: IncidentAction | None, **transition: Any) -> AlertMessage:
    kind = AlertEventKind.RESOLVED if action == IncidentAction.RESOLVE else AlertEventKind.FIRING
    return alert_message(
        details=(MessageDetail(label="Value", value="312"),),
        transition=announced_transition(kind, labels={"service": "checkout"}, **transition),
        incident_action=action,
    )


class TestIncidentIoTransport(SimpleTestCase):
    def test_a_trigger_and_its_resolve_post_to_the_alert_source_under_one_key(self) -> None:
        with pinned_post(202) as adapter:
            for action in (IncidentAction.TRIGGER, IncidentAction.RESOLVE):
                # The labels routes match on reach incident.io, and the alert's annotations reach the description.
                message = replace(
                    _message(action),
                    labels={"team": "infra", "service": "checkout"},
                    rule_details=(MessageDetail(label="runbook", value="https://example.com/runbook"),),
                )
                handle = IncidentIoTransport().deliver(team_id=2, target=TARGET, message=message)

        trigger, resolve = adapter.sent
        assert handle is None
        assert trigger.url == f"https://api.incident.io/v2/alert_events/http/{SOURCE_ID}"
        assert trigger.headers["Authorization"] == f"Bearer {SECRET}"
        assert json.loads(trigger.body or b"") == {
            "title": "API errors is firing",
            "status": "firing",
            "deduplication_key": "cfg-1::2026-09-30T09:00:00+00:00",
            "source_url": ALERT_URL,
            "description": "**Value:** `312`\n**runbook:** `https://example.com/runbook`",
            "metadata": {
                "team": "infra",
                "service": "checkout",
                "posthog_configuration_id": "cfg-1",
                "posthog_source_kind": "logs",
            },
        }
        resolved = json.loads(resolve.body or b"")
        assert (resolved["status"], resolved["deduplication_key"]) == ("resolved", "cfg-1::2026-09-30T09:00:00+00:00")

    @parameterized.expand(
        [
            ("wrong_secret", 401, True),
            ("deleted_alert_source", 404, True),
            # A body incident.io rejected is PostHog's to fix.
            ("rejected_body", 422, False),
            ("throttled", 429, False),
        ]
    )
    def test_only_a_refusal_the_owner_can_fix_counts_as_theirs(self, _name: str, status: int, refused: bool) -> None:
        with pinned_post(status), pytest.raises(DeliveryError) as raised:
            IncidentIoTransport().deliver(team_id=2, target=TARGET, message=_message(IncidentAction.TRIGGER))

        assert isinstance(raised.value, DestinationRefused) is refused

    @parameterized.expand(
        [
            ("throttled", 429, None),
            ("unreachable", 0, requests.ConnectionError(f"headers were {{'Authorization': 'Bearer {SECRET}'}}")),
        ]
    )
    def test_a_failed_send_never_repeats_the_secret(self, _name: str, status: int, error: Exception | None) -> None:
        with pinned_post(status, error), pytest.raises(DeliveryError) as raised:
            IncidentIoTransport().deliver(team_id=2, target=TARGET, message=_message(IncidentAction.TRIGGER))

        assert SECRET not in str(raised.value)
        assert raised.value.__cause__ is None
        assert SECRET not in IncidentIoTransport().channel_target(TARGET)

    @parameterized.expand(
        [
            ("no_incident_action", TARGET, None),
            ("no_secret", cast(AlertDestinationData, {**TARGET, "incident_io_secret": ""}), IncidentAction.TRIGGER),
            # The ID is a path segment, so a stored value that walks the path must never be sent.
            (
                "id_that_walks_the_path",
                cast(AlertDestinationData, {**TARGET, "incident_io_alert_source_config_id": "../../v1/incidents"}),
                IncidentAction.TRIGGER,
            ),
        ]
    )
    def test_an_event_incident_io_cannot_take_is_refused_before_sending(
        self, _name: str, target: AlertDestinationData, action: IncidentAction | None
    ) -> None:
        with pinned_post() as adapter, pytest.raises(DeliveryError):
            IncidentIoTransport().deliver(team_id=2, target=target, message=_message(action))

        assert adapter.sent == []

    @parameterized.expand(
        [
            (
                "markdown_link",
                "[Open the runbook](https://evil.example/sso)",
                "`[Open the runbook](https://evil.example/sso)`",
            ),
            ("bare_url", "https://evil.example/sso", "`https://evil.example/sso`"),
            # A backtick in the value must not close the code span early.
            ("backticks", "a `b` https://evil.example", "``a `b` https://evil.example``"),
            (
                "carriage_returns",
                "checkout\r\r[Open the runbook](https://evil.example/sso)\r\r",
                "`checkout  [Open the runbook](https://evil.example/sso) `",
            ),
        ]
    )
    def test_a_detail_value_cannot_render_as_a_link(self, _name: str, value: str, rendered: str) -> None:
        message = alert_message(
            details=(MessageDetail(label="Service", value=value),),
            transition=announced_transition(AlertEventKind.FIRING),
            incident_action=IncidentAction.TRIGGER,
        )

        with pinned_post(202) as adapter:
            IncidentIoTransport().deliver(team_id=2, target=TARGET, message=message)

        assert json.loads(adapter.sent[0].body or b"")["description"] == f"**Service:** {rendered}"
