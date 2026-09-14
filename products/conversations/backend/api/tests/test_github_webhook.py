import json
import hashlib
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import RequestFactory

from parameterized import parameterized

from posthog.models.integration import Integration

from products.conversations.backend.api.github_events import dispatch_github_event, proxy_github_event_to_owning_region


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


class TestDispatchGithubEvent(BaseTest):
    """Tests for dispatch_github_event called directly (as the ingress consumer does)."""

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

    def _dispatch(self, payload: dict, event_type: str = "issues", delivery_id: str | None = "delivery-abc"):
        return dispatch_github_event(event_type, payload, delivery_id)

    def _request(self, payload: dict, event_type: str = "issues"):
        return self.factory.post(
            "/webhooks/github/",
            data=json.dumps(payload).encode(),
            content_type="application/json",
            HTTP_X_GITHUB_EVENT=event_type,
        )

    @patch("products.conversations.backend.api.github_events.process_github_event")
    def test_dispatches_issue_event_to_celery(self, mock_task):
        mock_task.delay = MagicMock()
        payload = _issue_event()
        self._dispatch(payload)

        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["event_type"] == "issues"
        assert call_kwargs["team_id"] == self.team.id
        assert call_kwargs["repo"] == "org/repo"

    @patch("products.conversations.backend.api.github_events.process_github_event")
    def test_falls_back_to_sha256_when_delivery_header_missing(self, mock_task):
        mock_task.delay = MagicMock()
        payload = _issue_event()
        expected_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]

        self._dispatch(payload, delivery_id=None)

        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["delivery_id"] == expected_hash

    @patch("products.conversations.backend.api.github_events.process_github_event")
    def test_no_installation_does_not_dispatch(self, mock_task):
        mock_task.delay = MagicMock()
        payload = _issue_event()
        del payload["installation"]
        self._dispatch(payload)
        mock_task.delay.assert_not_called()

    @parameterized.expand(
        [
            ("unknown_installation", 99999, {}, "no matching Integration row"),
            ("github_disabled", 12345, {"github_enabled": False}, "feature disabled"),
            ("no_integration_binding", 12345, {"github_integration_id": None}, "no explicit binding"),
        ]
    )
    @patch("products.conversations.backend.api.github_events.logger")
    @patch("products.conversations.backend.api.github_events.process_github_event")
    def test_no_dispatch(self, _name, installation_id, settings_override, _reason, mock_task, mock_logger):
        mock_task.delay = MagicMock()
        if settings_override:
            for key, val in settings_override.items():
                if val is None:
                    self.team.conversations_settings.pop(key, None)
                else:
                    self.team.conversations_settings[key] = val
            self.team.save()

        self._dispatch(_issue_event(installation_id=installation_id))
        mock_task.delay.assert_not_called()
        # The proxy owns the no-team report, so a copy here would fire on every delivery the
        # primary region correctly forwarded to the region that does own it.
        mock_logger.warning.assert_not_called()

    @parameterized.expand(
        [
            ("pull_request_is_never_proxied", "pull_request", 99999, True, False, False),
            ("installation_owned_here_stays_here", "issues", 12345, True, False, False),
            ("secondary_region_reports_instead_of_forwarding", "issues", 99999, False, False, True),
            ("unowned_installation_goes_to_the_other_region", "issues", 99999, True, True, False),
        ]
    )
    @patch("products.conversations.backend.api.github_events.logger")
    @patch("products.conversations.backend.api.github_events.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.github_events.is_primary_region")
    def test_regional_proxy(
        self, _name, event_type, installation_id, primary, proxied, warned, mock_primary, mock_proxy, mock_logger
    ):
        mock_primary.return_value = primary
        payload = _issue_event(installation_id=installation_id)

        response = proxy_github_event_to_owning_region(self._request(payload, event_type), payload)

        assert response is None
        assert mock_proxy.call_count == (1 if proxied else 0)
        warnings = [call.args[0] for call in mock_logger.warning.call_args_list]
        assert warnings == (["github_issues_webhook_no_team"] if warned else [])

    @patch("products.conversations.backend.api.github_events.capture_exception")
    @patch("products.conversations.backend.api.github_events.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.github_events._team_for_github_installation")
    def test_installation_lookup_failure_does_not_escape_to_the_view(self, mock_lookup, mock_proxy, mock_capture):
        mock_lookup.side_effect = OperationalError("canceling statement due to statement timeout")
        payload = _issue_event(installation_id=99999)

        assert proxy_github_event_to_owning_region(self._request(payload), payload) is None
        mock_proxy.assert_not_called()
        mock_capture.assert_called_once()
