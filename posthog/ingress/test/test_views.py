import hmac
import json

from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from posthog.ingress.github.provider import build_github_provider
from posthog.ingress.pandadoc.provider import build_pandadoc_provider
from posthog.ingress.slack.provider import build_slack_provider
from posthog.ingress.views import build_webhook_view

SECRET = "s3cret"


def _github_signature(body: bytes) -> str:
    return "sha256=" + hmac.digest(SECRET.encode(), body, "sha256").hex()


def _slack_signature(timestamp: str, body: bytes) -> str:
    return "v0=" + hmac.digest(SECRET.encode(), b"v0:" + timestamp.encode() + b":" + body, "sha256").hex()


class TestWebhookView(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.dispatcher = Mock()
        patcher = patch("posthog.ingress.views.get_dispatcher", return_value=self.dispatcher)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _github_view(self):
        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET):
            provider = build_github_provider("posthog")
        return build_webhook_view(provider)

    def _post(self, body: bytes, headers: dict[str, str]):
        return self.factory.post(
            "/webhooks/github/",
            data=body,
            content_type="application/json",
            headers=headers,
        )

    def test_a_non_post_is_refused_before_any_verification(self) -> None:
        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET) as secret:
            response = self._github_view()(self.factory.get("/webhooks/github/"))
        self.assertEqual(response.status_code, 405)
        secret.assert_not_called()
        self.dispatcher.dispatch.assert_not_called()

    def test_a_bad_signature_is_403_and_never_reaches_a_consumer(self) -> None:
        body = json.dumps({"action": "opened"}).encode()
        request = self._post(body, {"X-Hub-Signature-256": "sha256=" + "0" * 64, "X-GitHub-Event": "pull_request"})

        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET):
            response = self._github_view()(request)

        self.assertEqual(response.status_code, 403)
        self.dispatcher.dispatch.assert_not_called()

    def test_an_unparseable_body_is_400(self) -> None:
        body = b"{not json"
        request = self._post(body, {"X-Hub-Signature-256": _github_signature(body), "X-GitHub-Event": "push"})

        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET):
            response = self._github_view()(request)

        self.assertEqual(response.status_code, 400)
        self.dispatcher.dispatch.assert_not_called()

    def test_a_verified_delivery_is_202_whatever_the_consumers_did(self) -> None:
        body = json.dumps({"action": "opened", "installation": {"id": 42}}).encode()
        request = self._post(
            body,
            {
                "X-Hub-Signature-256": _github_signature(body),
                "X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "delivery-1",
            },
        )

        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET):
            response = self._github_view()(request)

        self.assertEqual(response.status_code, 202)
        delivery = self.dispatcher.dispatch.call_args.args[0]
        self.assertEqual(delivery.event_type, "pull_request")
        self.assertEqual(delivery.delivery_id, "delivery-1")
        self.assertEqual(delivery.context, {"installation_id": "42"})

    def test_a_batched_body_becomes_several_deliveries_that_share_one_budget(self) -> None:
        body = json.dumps([{"event": "document_state_changed"}, {"event": "document_state_changed"}]).encode()
        request = self.factory.post(
            "/webhooks/pandadoc/",
            data=body,
            content_type="application/json",
            headers={"X-PandaDoc-Signature": hmac.digest(SECRET.encode(), body, "sha256").hex()},
        )

        with override_settings(PANDADOC_WEBHOOK_SECRET=SECRET):
            response = build_webhook_view(build_pandadoc_provider())(request)

        self.assertEqual(response.status_code, 202)
        calls = self.dispatcher.dispatch.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(len({id(call.kwargs["budget"]) for call in calls}), 1)

    def test_an_unconfigured_provider_is_500_rather_than_a_signature_failure(self) -> None:
        body = json.dumps({"action": "opened"}).encode()
        request = self._post(body, {"X-Hub-Signature-256": _github_signature(body), "X-GitHub-Event": "push"})

        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=""):
            response = build_webhook_view(build_github_provider("posthog"))(request)

        self.assertEqual(response.status_code, 500)

    def test_slack_url_verification_echoes_the_challenge_before_dispatch(self) -> None:
        body = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()
        timestamp = "1789000000"
        request = self.factory.post(
            "/slack/events/",
            data=body,
            content_type="application/json",
            headers={
                "X-Slack-Signature": _slack_signature(timestamp, body),
                "X-Slack-Request-Timestamp": timestamp,
            },
        )
        view = build_webhook_view(build_slack_provider(secret_getter=lambda: SECRET))

        with patch("posthog.ingress.verify.schemes.time.time", return_value=float(timestamp)):
            response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"challenge": "abc123"})
        self.dispatcher.dispatch.assert_not_called()

    def test_slack_event_callback_dispatches_the_inner_event_type(self) -> None:
        body = json.dumps(
            {
                "type": "event_callback",
                "event_id": "Ev1",
                "team_id": "T1",
                "event": {"type": "app_mention"},
            }
        ).encode()
        timestamp = "1789000000"
        request = self.factory.post(
            "/slack/events/",
            data=body,
            content_type="application/json",
            headers={
                "X-Slack-Signature": _slack_signature(timestamp, body),
                "X-Slack-Request-Timestamp": timestamp,
            },
        )
        view = build_webhook_view(build_slack_provider(secret_getter=lambda: SECRET))

        with patch("posthog.ingress.verify.schemes.time.time", return_value=float(timestamp)):
            response = view(request)

        self.assertEqual(response.status_code, 202)
        delivery = self.dispatcher.dispatch.call_args.args[0]
        self.assertEqual(delivery.event_type, "app_mention")
        self.assertEqual(delivery.delivery_id, "Ev1")
        self.assertEqual(delivery.context["slack_team_id"], "T1")
