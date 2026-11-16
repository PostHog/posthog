import hmac
import json
import time

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.ingress.linear.provider import build_linear_provider
from posthog.ingress.views import build_webhook_view

SECRET = "linear-app-secret"


def _body(timestamp_ms: int | None) -> bytes:
    payload: dict[str, object] = {"type": "Issue", "action": "create", "organizationId": "org-1", "data": {}}
    if timestamp_ms is not None:
        payload["webhookTimestamp"] = timestamp_ms
    return json.dumps(payload).encode()


class TestLinearProvider(SimpleTestCase):
    def setUp(self) -> None:
        reset_consumer_registry()
        cache.clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)

    @parameterized.expand(
        [
            ("fresh", 0, SECRET, SECRET, 200),
            ("clock_skew_inside_the_window", -30, SECRET, SECRET, 200),
            ("replayed_after_the_window", -120, SECRET, SECRET, 400),
            ("sent_from_the_future", 120, SECRET, SECRET, 400),
            ("no_timestamp", None, SECRET, SECRET, 400),
            ("wrong_secret", 0, "another-secret", SECRET, 403),
            ("secret_unset", 0, SECRET, "", 403),
        ]
    )
    def test_answers_only_a_fresh_correctly_signed_body_with_the_200_linear_requires(
        self,
        _name: str,
        offset_seconds: int | None,
        signing_secret: str,
        configured_secret: str,
        expected_status: int,
    ) -> None:
        timestamp_ms = None if offset_seconds is None else int((time.time() + offset_seconds) * 1000)
        body = _body(timestamp_ms)
        request = RequestFactory().post(
            "/webhooks/linear/",
            data=body,
            content_type="application/json",
            headers={
                "Linear-Signature": hmac.digest(signing_secret.encode(), body, "sha256").hex(),
                "Linear-Delivery": "delivery-1",
                "Linear-Event": "Issue",
            },
        )

        with override_settings(LINEAR_APP_WEBHOOK_SECRET=configured_secret):
            response = build_webhook_view(build_linear_provider("posthog"))(request)

        self.assertEqual(response.status_code, expected_status)
        if expected_status == 403:
            self.assertEqual(response.content, b"")
