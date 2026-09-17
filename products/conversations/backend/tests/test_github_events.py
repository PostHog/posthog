import json
import hashlib
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import InterfaceError, OperationalError

from parameterized import parameterized

from posthog.ingress.contracts import DeliveryOwnership, WebhookDelivery
from posthog.models.integration import Integration

from products.conversations.backend.facade import api as conversations_facade

GITHUB_EVENTS_MODULE = "products.conversations.backend.services.github_events"


def _issue_event(
    *,
    action: str = "opened",
    installation_id: int | None = 12345,
    repo: str = "org/repo",
    issue_number: int = 1,
    title: str = "Bug report",
    body: str = "",
    sender_login: str = "octocat",
) -> dict[str, Any]:
    return {
        "action": action,
        # GitHub sends `"installation": null` for a delivery outside an App installation.
        "installation": {"id": installation_id} if installation_id is not None else None,
        "repository": {"full_name": repo},
        "issue": {
            "number": issue_number,
            "title": title,
            "body": body,
            "user": {"login": sender_login},
        },
        "sender": {"login": sender_login},
    }


def _delivery(
    payload: dict[str, Any],
    *,
    event_type: str = "issues",
    delivery_id: str | None = "delivery-abc",
) -> WebhookDelivery:
    return WebhookDelivery(
        provider="github",
        app="posthog",
        delivery_id=delivery_id,
        event_type=event_type,
        payload=payload,
        received_at=datetime(2026, 9, 15, tzinfo=UTC),
        context={},
    )


class TestConversationsGitHubDeliveries(BaseTest):
    def setUp(self):
        super().setUp()

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

    def _disable(self, settings_override: dict[str, Any]) -> None:
        for key, value in settings_override.items():
            if value is None:
                self.team.conversations_settings.pop(key, None)
            else:
                self.team.conversations_settings[key] = value
        self.team.save()

    @parameterized.expand(
        [
            ("an_installation_connected_here", "issues", 12345, {}, DeliveryOwnership.LOCAL),
            ("an_installation_no_team_here_has", "issues", 99999, {}, DeliveryOwnership.ELSEWHERE),
            ("github_turned_off_for_the_team", "issues", 12345, {"github_enabled": False}, DeliveryOwnership.ELSEWHERE),
            (
                "no_explicit_integration_binding",
                "issues",
                12345,
                {"github_integration_id": None},
                DeliveryOwnership.ELSEWHERE,
            ),
            ("an_event_type_this_product_ignores", "pull_request", 99999, {}, DeliveryOwnership.UNDECIDED),
            ("a_delivery_outside_an_installation", "issues", None, {}, DeliveryOwnership.UNDECIDED),
        ]
    )
    def test_ownership_answers_where_the_installations_team_lives(
        self,
        _name: str,
        event_type: str,
        installation_id: int | None,
        settings_override: dict[str, Any],
        expected: DeliveryOwnership,
    ):
        self._disable(settings_override)
        delivery = _delivery(_issue_event(installation_id=installation_id), event_type=event_type)

        assert conversations_facade.github_delivery_ownership(delivery) == expected

    @parameterized.expand(
        [
            ("a_cancelled_statement", OperationalError("canceling statement due to statement timeout")),
            ("a_connection_that_went_away", OperationalError("server closed the connection unexpectedly")),
            ("a_driver_that_reports_the_connection_gone", InterfaceError("connection already closed")),
        ]
    )
    @patch(f"{GITHUB_EVENTS_MODULE}.Integration.objects.filter")
    def test_a_lookup_that_never_answered_forwards_rather_than_claiming_the_delivery(
        self, _name: str, error: Exception, mock_filter
    ):
        # Forwarding is the recoverable answer: the other region repeats the lookup and no-ops if
        # it does not own the installation, while claiming it here would drop the delivery.
        # Undecided is what a re-raise buys, and that forwards nothing on a receipted delivery.
        mock_filter.side_effect = error

        answer = conversations_facade.github_delivery_ownership(_delivery(_issue_event()))

        assert answer == DeliveryOwnership.ELSEWHERE

    @patch(f"{GITHUB_EVENTS_MODULE}.process_github_event")
    @patch(f"{GITHUB_EVENTS_MODULE}.Integration.objects.filter")
    def test_a_lookup_that_hits_its_timeout_fails_the_dispatch_rather_than_receipting_it(self, mock_filter, mock_task):
        # Swallowing it would return quietly, the dispatcher would mark the delivery done for 24
        # hours, and GitHub does not redeliver a receipted event, so the issue event is lost here.
        mock_task.delay = MagicMock()
        mock_filter.side_effect = OperationalError("canceling statement due to statement timeout")

        with self.assertRaises(OperationalError):
            conversations_facade.accept_github_event(_delivery(_issue_event()))

        mock_task.delay.assert_not_called()

    @patch(f"{GITHUB_EVENTS_MODULE}.process_github_event")
    def test_accepting_a_delivery_enqueues_it_for_the_owning_team(self, mock_task):
        mock_task.delay = MagicMock()

        conversations_facade.accept_github_event(_delivery(_issue_event()))

        call_kwargs = mock_task.delay.call_args[1]
        assert call_kwargs["event_type"] == "issues"
        assert call_kwargs["team_id"] == self.team.id
        assert call_kwargs["repo"] == "org/repo"
        assert call_kwargs["delivery_id"] == "delivery-abc"

    @patch(f"{GITHUB_EVENTS_MODULE}.process_github_event")
    def test_falls_back_to_sha256_when_delivery_header_missing(self, mock_task):
        mock_task.delay = MagicMock()
        payload = _issue_event()
        expected_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]

        conversations_facade.accept_github_event(_delivery(payload, delivery_id=None))

        assert mock_task.delay.call_args[1]["delivery_id"] == expected_hash

    @parameterized.expand(
        [
            ("github_turned_off_for_the_team", 12345, {"github_enabled": False}),
            ("a_delivery_outside_an_installation", None, {}),
        ]
    )
    @patch(f"{GITHUB_EVENTS_MODULE}.process_github_event")
    def test_a_delivery_this_region_does_not_own_enqueues_nothing(
        self, _name: str, installation_id: int | None, settings_override: dict[str, Any], mock_task
    ):
        mock_task.delay = MagicMock()
        self._disable(settings_override)

        conversations_facade.accept_github_event(_delivery(_issue_event(installation_id=installation_id)))

        mock_task.delay.assert_not_called()
