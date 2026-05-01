import hmac
import json
import hashlib
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client

from parameterized import parameterized

from posthog.models.integration import Integration


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


class TestGithubIssuesWebhook(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()

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

    def _post_webhook(
        self,
        payload: dict,
        event_type: str = "issues",
        secret: str = WEBHOOK_SECRET,
        delivery_id: str = "delivery-abc",
        signature: str | None = None,
    ):
        body = json.dumps(payload).encode()
        headers: dict[str, str] = {
            "X-GitHub-Event": event_type,
            "X-GitHub-Delivery": delivery_id,
        }
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature
        else:
            headers["X-Hub-Signature-256"] = _sign(body, secret)

        return self.client.post(
            "/api/conversations/v1/github/events",
            body,
            content_type="application/json",
            headers=headers,
        )

    @parameterized.expand(
        [
            ("no_secret_returns_503", None, None, "issues", 503),
            ("bad_signature_returns_403", WEBHOOK_SECRET, "sha256=bad", "issues", 403),
            ("unhandled_event_returns_200", WEBHOOK_SECRET, None, "push", 200),
        ]
    )
    def test_error_responses(self, _name, secret_value, forced_sig, event_type, expected_status):
        with patch(
            "products.conversations.backend.api.github_events._get_github_webhook_secret",
            return_value=secret_value,
        ):
            resp = self._post_webhook(_issue_event(), event_type=event_type, signature=forced_sig)
            assert resp.status_code == expected_status

    @patch(
        "products.conversations.backend.api.github_events._get_github_webhook_secret",
        return_value=WEBHOOK_SECRET,
    )
    def test_returns_405_for_get(self, _mock):
        resp = self.client.get("/api/conversations/v1/github/events")
        assert resp.status_code == 405

    @patch("products.conversations.backend.api.github_events.process_github_event")
    @patch(
        "products.conversations.backend.api.github_events._get_github_webhook_secret",
        return_value=WEBHOOK_SECRET,
    )
    def test_dispatches_issue_event_to_celery(self, _mock_secret, mock_task):
        mock_task.delay = MagicMock()
        payload = _issue_event()
        resp = self._post_webhook(payload)

        assert resp.status_code == 202
        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["event_type"] == "issues"
        assert call_kwargs["team_id"] == self.team.id
        assert call_kwargs["repo"] == "org/repo"

    @patch("products.conversations.backend.api.github_events.process_github_event")
    @patch(
        "products.conversations.backend.api.github_events._get_github_webhook_secret",
        return_value=WEBHOOK_SECRET,
    )
    def test_falls_back_to_sha256_when_delivery_header_missing(self, _mock_secret, mock_task):
        mock_task.delay = MagicMock()
        payload = _issue_event()
        body = json.dumps(payload).encode()
        expected_hash = hashlib.sha256(body).hexdigest()[:32]

        self.client.post(
            "/api/conversations/v1/github/events",
            body,
            content_type="application/json",
            headers={
                "X-GitHub-Event": "issues",
                "X-Hub-Signature-256": _sign(body, WEBHOOK_SECRET),
            },
        )

        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["delivery_id"] == expected_hash

    @parameterized.expand(
        [
            # (name, installation_id, settings_override, reason)
            ("unknown_installation", 99999, {}, "no matching Integration row"),
            ("github_disabled", 12345, {"github_enabled": False}, "feature disabled"),
            ("no_integration_binding", 12345, {"github_integration_id": None}, "no explicit binding"),
        ]
    )
    @patch("products.conversations.backend.api.github_events.process_github_event")
    @patch(
        "products.conversations.backend.api.github_events._get_github_webhook_secret",
        return_value=WEBHOOK_SECRET,
    )
    def test_no_dispatch(self, _name, installation_id, settings_override, _reason, _mock_secret, mock_task):
        mock_task.delay = MagicMock()
        if settings_override:
            for key, val in settings_override.items():
                if val is None:
                    self.team.conversations_settings.pop(key, None)
                else:
                    self.team.conversations_settings[key] = val
            self.team.save()

        resp = self._post_webhook(_issue_event(installation_id=installation_id))
        assert resp.status_code == 200
        mock_task.delay.assert_not_called()
