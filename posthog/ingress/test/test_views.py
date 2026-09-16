import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, cast
from urllib.parse import urlencode

from unittest.mock import Mock, patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase, override_settings

import structlog.testing
from parameterized import parameterized
from requests import RequestException
from rest_framework.request import Request as DRFRequest
from rest_framework.throttling import BaseThrottle, ScopedRateThrottle

from posthog.ingress.contracts import (
    DeliveryDispatch,
    DeliveryOwnership,
    ProviderSpec,
    WebhookConsumer,
    WebhookDelivery,
)
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.forward import HOST_IDENTIFYING_HEADERS, forward_to_secondary_region
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.github.provider import GitHubProvider, build_github_provider
from posthog.ingress.pandadoc.provider import build_pandadoc_provider
from posthog.ingress.providers import WebhookProvider
from posthog.ingress.slack.provider import build_slack_provider
from posthog.ingress.verify.schemes import Verification, VerificationOutcome
from posthog.ingress.views import build_webhook_view
from posthog.regions import SECONDARY_REGION_DOMAIN

SECRET = "s3cret"


def _github_signature(body: bytes) -> str:
    return "sha256=" + hmac.digest(SECRET.encode(), body, "sha256").hex()


def _slack_signature(timestamp: str, body: bytes) -> str:
    return "v0=" + hmac.digest(SECRET.encode(), b"v0:" + timestamp.encode() + b":" + body, "sha256").hex()


GITHUB_SPEC = ProviderSpec(provider="github", app="posthog", event_types=frozenset({"issues"}))
PANDADOC_SPEC = ProviderSpec(provider="pandadoc", app="default", event_types=frozenset({"document_state_changed"}))

RAISES = object()


class _RedeliveringGitHubProvider(GitHubProvider):
    # Stands in for a provider that replays a delivery the endpoint did not accept, which GitHub
    # itself does not do.
    retry_status = 502


class _ClaimsGitHubProvider(GitHubProvider):
    # Stands in for a scheme that checks a signed token, which names the sender before the body
    # is parsed. The claims land in the delivery's context so the test can read them back.
    def verify(self, request: HttpRequest) -> Verification:
        return Verification(outcome=VerificationOutcome.VERIFIED, facts={"tenant_id": "t-1"})

    def deliveries(self, request: HttpRequest, payload: Any, facts: Mapping[str, Any]) -> Sequence[WebhookDelivery]:
        return [replace(delivery, context=dict(facts)) for delivery in super().deliveries(request, payload, facts)]


class _StubThrottle(BaseThrottle):
    allowed = False
    wait_seconds: float | None = None

    def allow_request(self, request: DRFRequest, view: object) -> bool:
        return self.allowed

    def wait(self) -> float | None:
        return self.wait_seconds


class _ThrottledGitHubProvider(GitHubProvider):
    # Stands in for a provider whose verification is expensive enough to cap in front of, the way
    # a JWT signing-key lookup is.
    throttle_class = _StubThrottle


class _ScopedThrottleGitHubProvider(GitHubProvider):
    throttle_class = ScopedRateThrottle


class _FormBodyGitHubProvider(GitHubProvider):
    # Stands in for a provider that posts a form rather than JSON, the way Slack's interactivity
    # payloads and Mailgun's events do.
    def parse(self, request: HttpRequest) -> Any:
        return json.loads(request.POST["payload"])


class TestWebhookView(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.dispatcher = Mock()
        self.dispatcher.ownership_of.return_value = (DeliveryOwnership.UNDECIDED, ())
        self.dispatcher.dispatch.return_value = DeliveryDispatch()
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

    @parameterized.expand(
        [
            ("a_throttle_that_says_how_long", 30.4, "31"),
            ("a_throttle_that_does_not", None, None),
        ]
    )
    def test_a_throttled_request_is_429_before_any_signature_is_checked(
        self, _name: str, wait_seconds: float | None, retry_after: str | None
    ) -> None:
        body = json.dumps({"action": "opened"}).encode()
        request = self._post(body, {"X-Hub-Signature-256": _github_signature(body), "X-GitHub-Event": "issues"})

        with (
            patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET) as secret,
            patch.object(_StubThrottle, "wait_seconds", wait_seconds),
            patch("posthog.ingress.views.observe_delivery") as observe,
        ):
            response = build_webhook_view(_ThrottledGitHubProvider("posthog"))(request)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), retry_after)
        self.assertEqual([call.kwargs["outcome"] for call in observe.call_args_list], ["throttled"])
        # The cap is worth having only if it lands before the signing key is read.
        secret.assert_not_called()
        self.dispatcher.dispatch.assert_not_called()

    def test_a_scoped_throttle_is_refused_when_the_view_is_built(self) -> None:
        with self.assertRaises(TypeError) as raised:
            build_webhook_view(_ScopedThrottleGitHubProvider("posthog"))

        # A scoped throttle finds no scope here and permits everything, so the endpoint would
        # look capped and answer 202 to every request.
        self.assertIn("github/posthog", str(raised.exception))
        self.assertIn("ScopedRateThrottle", str(raised.exception))

    def test_a_throttle_that_allows_the_request_changes_nothing(self) -> None:
        body = json.dumps({"action": "opened"}).encode()
        request = self._post(body, {"X-Hub-Signature-256": _github_signature(body), "X-GitHub-Event": "issues"})

        with (
            patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET),
            patch.object(_StubThrottle, "allowed", True),
        ):
            response = build_webhook_view(_ThrottledGitHubProvider("posthog"))(request)

        self.assertEqual(response.status_code, 202)
        self.dispatcher.dispatch.assert_called_once()

    def test_a_bad_signature_is_403_and_never_reaches_a_consumer(self) -> None:
        body = json.dumps({"action": "opened"}).encode()
        request = self._post(body, {"X-Hub-Signature-256": "sha256=" + "0" * 64, "X-GitHub-Event": "pull_request"})

        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET):
            response = self._github_view()(request)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.content, b"Invalid signature")
        self.dispatcher.dispatch.assert_not_called()

    def test_an_unparseable_body_is_400_and_logs_the_parser_error(self) -> None:
        body = b"{not json"
        request = self._post(body, {"X-Hub-Signature-256": _github_signature(body), "X-GitHub-Event": "push"})

        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET):
            with structlog.testing.capture_logs() as logs:
                response = self._github_view()(request)

        self.assertEqual(response.status_code, 400)
        self.dispatcher.dispatch.assert_not_called()
        warning = next(log for log in logs if log["event"] == "ingress_delivery_invalid_payload")
        self.assertEqual(warning["log_level"], "warning")
        self.assertEqual(warning["provider"], "github")
        self.assertEqual(warning["app"], "posthog")
        self.assertIn("Expecting property name", warning["error"])

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

    def test_what_the_signature_check_proved_reaches_deliveries(self) -> None:
        body = json.dumps({"action": "opened"}).encode()
        request = self._post(body, {"X-GitHub-Event": "issues"})

        response = build_webhook_view(_ClaimsGitHubProvider("posthog"))(request)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.dispatcher.dispatch.call_args.args[0].context, {"tenant_id": "t-1"})

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
        self.assertEqual(response.content, b"Webhook not configured")

    @parameterized.expand(
        [
            ("a_bad_signature", SECRET),
            ("a_missing_secret", ""),
        ]
    )
    def test_a_provider_that_withholds_its_existence_answers_an_empty_body(self, _name: str, secret: str) -> None:
        body = b'[{"event":"document_state_changed"}]'
        request = self.factory.post(
            "/webhooks/pandadoc/",
            data=body,
            content_type="application/json",
            headers={"X-PandaDoc-Signature": "0" * 64},
        )

        with override_settings(PANDADOC_WEBHOOK_SECRET=secret):
            response = build_webhook_view(build_pandadoc_provider())(request)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.dispatcher.dispatch.assert_not_called()

    def test_a_parse_override_reads_a_form_body_and_still_reaches_deliveries(self) -> None:
        body = urlencode({"payload": json.dumps({"action": "opened", "installation": {"id": 42}})}).encode()
        request = self.factory.post(
            "/webhooks/github/",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"X-Hub-Signature-256": _github_signature(body), "X-GitHub-Event": "pull_request"},
        )

        with patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET):
            response = build_webhook_view(_FormBodyGitHubProvider("posthog"))(request)

        self.assertEqual(response.status_code, 202)
        delivery = self.dispatcher.dispatch.call_args.args[0]
        self.assertEqual(delivery.payload, {"action": "opened", "installation": {"id": 42}})
        self.assertEqual(delivery.context, {"installation_id": "42"})

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


def _consumer(
    spec: ProviderSpec,
    *,
    name: str,
    handler: Mock,
    answer: object = None,
) -> WebhookConsumer:
    def ownership(delivery: WebhookDelivery) -> DeliveryOwnership:
        if answer is RAISES:
            raise RuntimeError("ownership lookup failed")
        return cast(DeliveryOwnership, answer)

    return WebhookConsumer(
        name=name,
        provider=spec.provider,
        app=spec.app,
        event_types=spec.event_types,
        handler=handler,
        ownership=None if answer is None else ownership,
    )


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class _DispatchingViewTestCase(SimpleTestCase):
    """A view driving the real dispatcher and registry, rather than a mocked one."""

    def setUp(self) -> None:
        cache.clear()
        self.factory = RequestFactory()
        self.handler = Mock()

        secret = patch("posthog.ingress.github.provider.get_instance_setting", return_value=SECRET)
        secret.start()
        self.addCleanup(secret.stop)

    def _view(self, consumers: list[WebhookConsumer], *, provider: WebhookProvider | None = None):
        registry = ConsumerRegistry(providers=[GITHUB_SPEC, PANDADOC_SPEC], consumers=consumers)
        dispatcher = patch("posthog.ingress.views.get_dispatcher", return_value=WebhookDispatcher(registry))
        dispatcher.start()
        self.addCleanup(dispatcher.stop)
        return build_webhook_view(provider if provider is not None else build_github_provider("posthog"))

    def _github_request(self):
        body = json.dumps({"action": "opened", "installation": {"id": 42}}).encode()
        return self.factory.post(
            "/webhooks/github/",
            data=body,
            content_type="application/json",
            headers={
                "X-Hub-Signature-256": _github_signature(body),
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "delivery-1",
            },
        )


class TestRegionalForwarding(_DispatchingViewTestCase):
    def setUp(self) -> None:
        super().setUp()
        forward = patch("posthog.ingress.dispatch.forward.requests.request")
        self.requests = forward.start()
        self.requests.return_value = Mock(ok=True, status_code=202)
        self.addCleanup(forward.stop)

    @parameterized.expand(
        [
            ("elsewhere_forwards_once", DeliveryOwnership.ELSEWHERE, 1, 0),
            ("local_forwards_nothing", DeliveryOwnership.LOCAL, 0, 0),
            ("undecided_forwards_nothing", DeliveryOwnership.UNDECIDED, 0, 0),
            ("a_lookup_that_raises_counts_as_undecided", RAISES, 0, 1),
        ]
    )
    def test_the_ownership_answer_decides_the_forward_and_never_the_local_dispatch(
        self, _name: str, answer: object, forwards: int, captures: int
    ) -> None:
        view = self._view([_consumer(GITHUB_SPEC, name="probe", handler=self.handler, answer=answer)])

        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.dispatch.dispatcher.capture_exception") as capture,
        ):
            response = view(self._github_request())

        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.requests.call_count, forwards)
        self.handler.assert_called_once()
        self.assertEqual(capture.call_count, captures)

    @parameterized.expand(
        [
            ("a_provider_that_redelivers_asks_for_one", _RedeliveringGitHubProvider, 502, "forward_failed", 0),
            ("a_provider_that_does_not_keeps_the_receipt", GitHubProvider, 202, "accepted", 1),
        ]
    )
    def test_a_failed_forward_answers_what_the_provider_needs_to_redeliver(
        self, _name: str, provider_class: type[GitHubProvider], status: int, outcome: str, dispatched: int
    ) -> None:
        self.requests.side_effect = RequestException("no route to the other region")
        view = self._view(
            [_consumer(GITHUB_SPEC, name="probe", handler=self.handler, answer=DeliveryOwnership.ELSEWHERE)],
            provider=provider_class("posthog"),
        )

        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.views.observe_delivery") as observe,
        ):
            response = view(self._github_request())

        self.assertEqual(response.status_code, status)
        self.assertEqual([call.kwargs["outcome"] for call in observe.call_args_list], [outcome])
        self.assertEqual(self.handler.call_count, dispatched)

    def test_the_secondary_region_reports_an_unowned_delivery_rather_than_forwarding_it_back(self) -> None:
        view = self._view(
            [_consumer(GITHUB_SPEC, name="probe", handler=self.handler, answer=DeliveryOwnership.ELSEWHERE)]
        )

        with (
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "eu.posthog.com"),
            patch("posthog.ingress.views.logger") as logger,
        ):
            response = view(self._github_request())

        self.assertEqual(response.status_code, 202)
        self.requests.assert_not_called()
        self.handler.assert_called_once()
        self.assertEqual([call.args[0] for call in logger.warning.call_args_list], ["ingress_delivery_unowned_here"])

    def test_a_batched_body_of_unowned_deliveries_forwards_the_request_once(self) -> None:
        view = self._view(
            [_consumer(PANDADOC_SPEC, name="probe", handler=self.handler, answer=DeliveryOwnership.ELSEWHERE)],
            provider=build_pandadoc_provider(),
        )
        body = json.dumps([{"event": "document_state_changed"}, {"event": "document_state_changed"}]).encode()
        request = self.factory.post(
            "/webhooks/pandadoc/",
            data=body,
            content_type="application/json",
            headers={"X-PandaDoc-Signature": hmac.digest(SECRET.encode(), body, "sha256").hex()},
        )

        with (
            override_settings(PANDADOC_WEBHOOK_SECRET=SECRET),
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
        ):
            response = view(request)

        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.requests.call_count, 1)
        self.assertEqual(self.handler.call_count, 2)


class TestUnacceptedDelivery(_DispatchingViewTestCase):
    @parameterized.expand(
        [
            ("a_provider_that_redelivers_asks_for_one", _RedeliveringGitHubProvider, 502, "retry_requested", ["probe"]),
            ("a_provider_that_does_not_keeps_the_receipt", GitHubProvider, 202, "accepted", None),
        ]
    )
    def test_a_consumer_that_raised_costs_the_receipt_only_where_that_buys_a_redelivery(
        self,
        _name: str,
        provider_class: type[GitHubProvider],
        status: int,
        outcome: str,
        warned_about: list[str] | None,
    ) -> None:
        self.handler.side_effect = RuntimeError("the consumer's durable write failed")
        view = self._view(
            [_consumer(GITHUB_SPEC, name="probe", handler=self.handler)],
            provider=provider_class("posthog"),
        )

        with (
            patch("posthog.ingress.dispatch.dispatcher.capture_exception"),
            patch("posthog.ingress.views.observe_delivery") as observe,
            patch("posthog.ingress.views.logger") as logger,
        ):
            response = view(self._github_request())

        self.assertEqual(response.status_code, status)
        self.assertEqual([call.kwargs["outcome"] for call in observe.call_args_list], [outcome])
        # The dispatcher already logged the consumer's own failure, so the view says only that
        # the request is not receipted, and names what cost it.
        warnings = {call.args[0]: call.kwargs for call in logger.warning.call_args_list}
        self.assertEqual(warnings.get("ingress_delivery_retry_requested", {}).get("consumers"), warned_about)

    def test_a_consumer_the_budget_skipped_costs_the_receipt_the_same_way(self) -> None:
        elapsed = {"seconds": 0.0}

        def spend_the_budget(delivery: WebhookDelivery) -> None:
            elapsed["seconds"] += 30.0

        skipped = Mock()
        view = self._view(
            [
                _consumer(GITHUB_SPEC, name="alpha", handler=Mock(side_effect=spend_the_budget)),
                _consumer(GITHUB_SPEC, name="zulu", handler=skipped),
            ],
            provider=_RedeliveringGitHubProvider("posthog"),
        )

        with (
            patch("time.monotonic", lambda: elapsed["seconds"]),
            patch("posthog.ingress.views.logger") as logger,
        ):
            response = view(self._github_request())

        self.assertEqual(response.status_code, 502)
        skipped.assert_not_called()
        warnings = {call.args[0]: call.kwargs for call in logger.warning.call_args_list}
        self.assertEqual(warnings["ingress_delivery_retry_requested"]["consumers"], ["zulu"])

    def test_a_duplicate_that_arrives_while_the_first_run_is_going_is_not_receipted(self) -> None:
        runs = {"count": 0}
        answered: list[int] = []

        def deliver_again_mid_run(delivery: WebhookDelivery) -> None:
            runs["count"] += 1
            if runs["count"] == 1:
                answered.append(view(self._github_request()).status_code)

        view = self._view(
            [_consumer(GITHUB_SPEC, name="probe", handler=Mock(side_effect=deliver_again_mid_run))],
            provider=_RedeliveringGitHubProvider("posthog"),
        )

        self.assertEqual(view(self._github_request()).status_code, 202)
        # The duplicate met a run that had not settled, so it asks for the delivery again rather
        # than receipting work that can still raise.
        self.assertEqual(answered, [502])
        self.assertEqual(runs["count"], 1)

    def test_the_redelivery_reaches_only_the_consumer_that_did_not_accept(self) -> None:
        accepted = Mock()
        self.handler.side_effect = RuntimeError("the consumer's durable write failed")
        view = self._view(
            [
                _consumer(GITHUB_SPEC, name="alpha", handler=accepted),
                _consumer(GITHUB_SPEC, name="zulu", handler=self.handler),
            ],
            provider=_RedeliveringGitHubProvider("posthog"),
        )

        with patch("posthog.ingress.dispatch.dispatcher.capture_exception"):
            self.assertEqual(view(self._github_request()).status_code, 502)
            self.handler.side_effect = None
            self.assertEqual(view(self._github_request()).status_code, 202)

        # The one that accepted is deduped on the replay, so the retry costs it nothing.
        accepted.assert_called_once()
        self.assertEqual(self.handler.call_count, 2)


class TestForwardToSecondaryRegion(SimpleTestCase):
    def setUp(self) -> None:
        self.body = json.dumps({"action": "opened"}).encode()
        self.request = RequestFactory().post(
            "/webhooks/github/",
            data=self.body,
            content_type="application/json",
            headers={
                "X-Hub-Signature-256": _github_signature(self.body),
                "X-GitHub-Event": "issues",
                "X-Forwarded-Host": "eu.posthog.com",
                "X-Forwarded-Proto": "https",
                "Forwarded": "host=eu.posthog.com;proto=https",
                "X-Forwarded-For": "140.82.115.1",
            },
        )

    @parameterized.expand(
        [
            ("a_2xx_is_a_forward", 202, None, True, "forwarded"),
            ("a_non_2xx_is_a_rejection", 500, None, False, "rejected"),
            ("a_transport_error_is_a_failure", None, RequestException("no route"), False, "failed"),
        ]
    )
    def test_only_a_2xx_from_the_other_region_counts_as_forwarded(
        self, _name: str, status_code: int | None, error: Exception | None, forwarded: bool, outcome: str
    ) -> None:
        response = Mock(ok=status_code is not None and status_code < 300, status_code=status_code)

        with (
            patch("posthog.ingress.dispatch.forward.requests.request", side_effect=error, return_value=response),
            patch("posthog.ingress.dispatch.forward.observe_forward") as observe,
        ):
            result = forward_to_secondary_region(self.request, provider="github", app="posthog")

        self.assertEqual(result, forwarded)
        self.assertEqual(observe.call_args.kwargs["outcome"], outcome)

    def test_the_replay_carries_the_signed_bytes_unchanged(self) -> None:
        with patch("posthog.ingress.dispatch.forward.requests.request") as request:
            request.return_value = Mock(ok=True, status_code=202)
            forward_to_secondary_region(self.request, provider="github", app="posthog")

        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["data"], self.body)
        self.assertEqual(kwargs["headers"]["X-Hub-Signature-256"], _github_signature(self.body))
        sent = {key.lower() for key in kwargs["headers"]}
        # The other region routes on the host it sees, so any host this region sends would send the
        # request straight back here and both regions would forward it in a loop.
        self.assertEqual(sent & HOST_IDENTIFYING_HEADERS, set())
        self.assertIn("x-forwarded-for", sent)
        self.assertIn(SECONDARY_REGION_DOMAIN, kwargs["url"])

    def test_a_multipart_request_read_as_a_form_is_rebuilt_from_its_fields_and_files(self) -> None:
        multipart = RequestFactory().post(
            "/webhooks/mailgun/",
            data={
                "token": "delivery-token",
                "recipient": "team-abc@example.com",
                "attachment-1": SimpleUploadedFile("note.txt", b"attached", content_type="text/plain"),
            },
        )
        # A form provider verifies through request.POST, which leaves no raw body to replay.
        self.assertEqual(multipart.POST["token"], "delivery-token")

        with patch("posthog.ingress.dispatch.forward.requests.request") as request:
            request.return_value = Mock(ok=True, status_code=202)
            forward_to_secondary_region(multipart, provider="mailgun", app="inbound")

        kwargs = request.call_args.kwargs
        self.assertIn(("token", "delivery-token"), kwargs["data"])
        self.assertIn(("recipient", "team-abc@example.com"), kwargs["data"])
        self.assertEqual(kwargs["files"], [("attachment-1", ("note.txt", b"attached", "text/plain"))])
        forwarded_header_names = {key.lower() for key in kwargs["headers"]}
        self.assertNotIn("content-type", forwarded_header_names)
        self.assertNotIn("content-length", forwarded_header_names)

    def test_a_urlencoded_form_read_still_replays_its_raw_bytes(self) -> None:
        body = b"token=delivery-token&recipient=team-abc%40example.com"
        urlencoded = RequestFactory().post(
            "/webhooks/mailgun/", data=body, content_type="application/x-www-form-urlencoded"
        )
        self.assertEqual(urlencoded.POST["token"], "delivery-token")

        with patch("posthog.ingress.dispatch.forward.requests.request") as request:
            request.return_value = Mock(ok=True, status_code=202)
            forward_to_secondary_region(urlencoded, provider="mailgun", app="inbound")

        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["data"], body)
        self.assertNotIn("files", kwargs)
