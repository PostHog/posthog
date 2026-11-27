import hmac
import json
from typing import Any

from unittest.mock import patch

from django.core.cache import cache, caches
from django.http.response import HttpResponseBase
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.ingress.dispatch.dedup import INGRESS_DEDUP_CACHE_ALIAS
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.github.provider import SPECS, build_github_provider
from posthog.ingress.views import build_webhook_view

from products.access_control.backend.webhook_consumers import WEBHOOK_CONSUMERS

WEBHOOK_SECRET = "test-access-control-webhook-secret"
ENQUEUE_TARGET = "products.access_control.backend.tasks.tasks.process_github_team_role_webhook.delay"


def _team_payload(action: str, *, scope: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action": action,
        "installation": {"id": 99844466},
        "organization": {"login": "PostHog"},
        "team": {"id": 12345, "slug": "team-cymbal", "name": "Team Cymbal"},
    }
    if scope is not None:
        payload["scope"] = scope
    return payload


class TestAccessControlGitHubWebhookConsumer(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_consumer_registry()
        cache.clear()
        caches[INGRESS_DEDUP_CACHE_ALIAS].clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)
        self.addCleanup(caches[INGRESS_DEDUP_CACHE_ALIAS].clear)
        dispatcher = WebhookDispatcher(ConsumerRegistry(providers=SPECS, consumers=WEBHOOK_CONSUMERS))
        for patcher in (
            patch("posthog.ingress.views.get_dispatcher", return_value=dispatcher),
            patch("posthog.credentials_service.instance_settings.get_instance_setting", return_value=WEBHOOK_SECRET),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.view = build_webhook_view(build_github_provider("posthog"))

    def _post(
        self,
        body: bytes,
        *,
        event: str = "team",
        signature: str | None = None,
        delivery_id: str = "delivery-1",
    ) -> HttpResponseBase:
        headers: dict[str, str] = {
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery_id,
        }
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature
        request = RequestFactory().post(
            "/webhooks/github/", data=body, content_type="application/json", headers=headers
        )
        return self.view(request)

    def _sign(self, body: bytes) -> str:
        return "sha256=" + hmac.digest(WEBHOOK_SECRET.encode("utf-8"), body, "sha256").hex()

    @parameterized.expand(
        [
            ("team_created", "team", "created", None, True),
            ("team_edited", "team", "edited", None, True),
            ("team_deleted", "team", "deleted", None, True),
            ("team_repo_grant_ignored", "team", "added_to_repository", None, False),
            ("membership_added", "membership", "added", "team", True),
            ("membership_removed", "membership", "removed", "team", True),
            ("membership_non_team_ignored", "membership", "added", "organization", False),
        ]
    )
    def test_dispatches_expected_team_and_membership_actions(
        self,
        _name: str,
        event: str,
        action: str,
        scope: str | None,
        should_enqueue: bool,
    ) -> None:
        body = json.dumps(_team_payload(action, scope=scope)).encode("utf-8")
        with patch(ENQUEUE_TARGET) as mock_delay:
            response = self._post(body, event=event, signature=self._sign(body))

        assert response.status_code == 202
        if should_enqueue:
            mock_delay.assert_called_once_with(
                installation_id="99844466",
                action=action,
                github_org_login="PostHog",
                github_team_id=12345,
                github_team_slug="team-cymbal",
                github_team_name="Team Cymbal",
            )
        else:
            mock_delay.assert_not_called()

    @parameterized.expand(
        [
            ("missing_signature", None),
            ("wrong_signature", "sha256=" + "0" * 64),
        ]
    )
    def test_rejects_invalid_signature(self, _name: str, signature: str | None) -> None:
        body = json.dumps(_team_payload("created")).encode("utf-8")
        with patch(ENQUEUE_TARGET) as mock_delay:
            response = self._post(body, signature=signature)

        assert response.status_code == 403
        mock_delay.assert_not_called()

    def test_rejects_non_post_and_malformed_json(self) -> None:
        get_request = RequestFactory().get("/webhooks/github/")
        assert self.view(get_request).status_code == 405

        bad_body = b"{not-json"
        response = self._post(bad_body, signature=self._sign(bad_body), delivery_id="delivery-bad")
        assert response.status_code == 400
