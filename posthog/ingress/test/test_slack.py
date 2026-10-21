import json
from typing import Any
from urllib.parse import urlencode

from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.ingress.providers import InvalidPayload
from posthog.ingress.slack.provider import build_slack_interactivity_provider

URL = "/webhooks/slack/interactivity"
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


def _form_request(payload_field: str, headers: dict[str, str] | None = None) -> Any:
    return RequestFactory().post(
        URL,
        data=urlencode({"payload": payload_field}),
        content_type=FORM_CONTENT_TYPE,
        headers=headers or {},
    )


class TestSlackInteractivityProvider(SimpleTestCase):
    def setUp(self) -> None:
        self.provider = build_slack_interactivity_provider(secret_getter=lambda: "slack-signing-secret")

    def test_the_signed_payload_field_reaches_the_consumer_unaltered(self) -> None:
        # A consumer hashes these exact bytes for its idempotency key, and the parsed mapping
        # cannot be serialized back into them: this spacing does not survive the round trip.
        raw_payload = '{"type":"block_actions", "team":{"id":"T123"}}'
        request = _form_request(raw_payload)

        delivery = self.provider.deliveries(request, self.provider.parse(request), {})[0]

        self.assertEqual(delivery.context["raw_payload"], raw_payload)
        # The payload stays what Slack sent inside the field. Carrying the raw string in it
        # instead would put a key of ours in the receipt the consumer stores.
        self.assertEqual(delivery.payload, {"type": "block_actions", "team": {"id": "T123"}})

    @parameterized.expand(
        [
            ("a field that is not JSON", _form_request("{")),
            ("a field that is not an object", _form_request("null")),
            ("a form with no payload field", RequestFactory().post(URL, data="", content_type=FORM_CONTENT_TYPE)),
        ]
    )
    def test_a_body_this_provider_cannot_read_is_an_invalid_payload(self, _name: str, request: Any) -> None:
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
