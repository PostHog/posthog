import hmac
import json
import hashlib
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import RequestFactory

from parameterized import parameterized

from posthog.models.integration import Integration

from products.conversations.backend.api.github_events import dispatch_github_event


def _sign(payload: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _issue_event(
    *,
    action: str = "opened",
    installation_id: int = 12345,
    repo: str = "org/repo",
    issue_number: int = 1,
    title: str = "Bug report",
    body: str = "",
    sender_login: str = "octocat",
) -> dict[str, Any]:
    return {
        "action": action,
        "installation": {"id": installation_id},
        "repository": {"full_name": repo},
        "issue": {
            "number": issue_number,
            "title": title,
            "body": body,
            "user": {"login": sender_login},
        },
        "sender": {"login": sender_login},
    }


WEBHOOK_SECRET = "test-webhook-secret"


class TestDispatchGithubEvent(BaseTest):
    """Tests for dispatch_github_event called directly (as github_webhook does)."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="12345",
            config={"account": {"name": "org"}},
        )
        self.team.conversations_enabled = True
        self.team.conversations_settings = {
            "github_enabled": True,
            "github_integration_id": self.integration.id,
            "github_repos": ["org/repo"],
        }
        self.team.save()

    def _dispatch(self, payload: dict, event_type: str = "issues", delivery_id: str = "delivery-abc"):
        body = json.dumps(payload).encode()
        request = self.factory.post(
            "/webhooks/github/pr/",
            data=body,
            content_type="application/json",
            HTTP_X_GITHUB_DELIVERY=delivery_id,
        )
        return dispatch_github_event(request, event_type, payload)

    @patch("products.conversations.backend.api.github_events.process_github_event")
    def test_dispatches_issue_event_to_celery(self, mock_task):
        mock_task.delay = MagicMock()
        payload = _issue_event()
        resp = self._dispatch(payload)

        assert resp.status_code == 202
        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["event_type"] == "issues"
        assert call_kwargs["team_id"] == self.team.id
        assert call_kwargs["repo"] == "org/repo"

    @patch("products.conversations.backend.api.github_events.process_github_event")
    def test_falls_back_to_sha256_when_delivery_header_missing(self, mock_task):
        mock_task.delay = MagicMock()
        payload = _issue_event()
        body = json.dumps(payload).encode()
        expected_hash = hashlib.sha256(body).hexdigest()[:32]

        request = self.factory.post(
            "/webhooks/github/pr/",
            data=body,
            content_type="application/json",
        )
        dispatch_github_event(request, "issues", payload)

        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["delivery_id"] == expected_hash

    def test_no_installation_returns_200(self):
        payload = _issue_event()
        del payload["installation"]
        resp = self._dispatch(payload)
        assert resp.status_code == 200

    @parameterized.expand(
        [
            ("unknown_installation", 99999, {}, "no matching Integration row"),
            ("github_disabled", 12345, {"github_enabled": False}, "feature disabled"),
            ("no_integration_binding", 12345, {"github_integration_id": None}, "no explicit binding"),
        ]
    )
    @patch("products.conversations.backend.api.github_events.process_github_event")
    def test_no_dispatch(self, _name, installation_id, settings_override, _reason, mock_task):
        mock_task.delay = MagicMock()
        if settings_override:
            for key, val in settings_override.items():
                if val is None:
                    self.team.conversations_settings.pop(key, None)
                else:
                    self.team.conversations_settings[key] = val
            self.team.save()

        resp = self._dispatch(_issue_event(installation_id=installation_id))
        assert resp.status_code == 200
        mock_task.delay.assert_not_called()
