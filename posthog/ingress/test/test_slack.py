import json
from typing import Any
from urllib.parse import urlencode

from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.ingress.providers import InvalidPayload
from posthog.ingress.slack.provider import SLACK_RAW_PAYLOAD_KEY, build_slack_interactivity_provider

URL = "/api/conversations/v1/slack/interactivity"


def _form_request(payload_field: str, headers: dict[str, str] | None = None) -> Any:
    return RequestFactory().post(
        URL,
        data=urlencode({"payload": payload_field}),
        content_type="application/x-www-form-urlencoded",
        headers=headers or {},
    )


class TestSlackInteractivityProvider(SimpleTestCase):
    def setUp(self) -> None:
        self.provider = build_slack_interactivity_provider(secret_getter=lambda: "slack-signing-secret")

    def test_the_signed_payload_field_reaches_the_consumer_unaltered(self) -> None:
        # A consumer hashes these exact bytes for its idempotency key, and the parsed mapping
        # cannot be serialized back into them.
        raw_payload = '{"type":"block_actions", "team":{"id":"T123"}}'

        payload = self.provider.parse(_form_request(raw_payload))

        self.assertEqual(payload[SLACK_RAW_PAYLOAD_KEY], raw_payload)

    @parameterized.expand(
        [
            ("a field that is not JSON", "{"),
            ("a field that is not an object", "null"),
        ]
    )
    def test_a_payload_field_this_provider_cannot_read_is_an_invalid_payload(self, _name: str, field: str) -> None:
        with self.assertRaises(InvalidPayload):
            self.provider.parse(_form_request(field))

    def test_a_form_without_a_payload_field_is_an_invalid_payload(self) -> None:
        request = RequestFactory().post(URL, data="", content_type="application/x-www-form-urlencoded")

        with self.assertRaises(InvalidPayload):
            self.provider.parse(request)

    def test_a_delivery_reads_the_interactive_payload_shape(self) -> None:
        raw_payload = json.dumps({"type": "block_actions", "team": {"id": "T123"}, "actions": [{"action_id": "open"}]})
        request = _form_request(raw_payload, headers={"X-Slack-Retry-Num": "2", "X-Slack-Retry-Reason": "http_timeout"})

        deliveries = self.provider.deliveries(request, self.provider.parse(request), {})

        self.assertEqual(len(deliveries), 1)
        delivery = deliveries[0]
        self.assertEqual(delivery.app, "supporthog_interactivity")
        self.assertEqual(delivery.event_type, "block_actions")
        # Slack sends no id with a click, so dedup has nothing to key on.
        self.assertIsNone(delivery.delivery_id)
        self.assertEqual(delivery.context["slack_team_id"], "T123")
        self.assertEqual(delivery.context["retry_num"], "2")
        self.assertEqual(delivery.context["retry_reason"], "http_timeout")
