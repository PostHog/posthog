import json
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

import requests
from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.comment import Comment
from posthog.models.instance_setting import override_instance_config
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from products.conversations.backend.api.posthog_support import CreatePostHogSupportTicketSerializer
from products.conversations.backend.models import SigningSecret, Ticket

SUPPORT_WIDGET_TOKEN = "support_widget_token"
SIGNING_SECRET = "support_signing_secret"

DELETION_QUERY = "SELECT uuid FROM events\nWHERE event = 'test_event' AND timestamp < '2026-10-01'"

DELETION_REQUEST = {
    "request_type": "data_deletion",
    "subject": "Delete test events",
    "description": "Test events sent from a staging build reached production.",
    "deletion_query": DELETION_QUERY,
    "expected_event_count": 120,
    "deletion_consent": True,
}


class TestCreatePostHogSupportTicketSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_query", {"deletion_query": ""}, "deletion_query"),
            ("no_count", {"expected_event_count": None}, "expected_event_count"),
            ("no_consent", {"deletion_consent": False}, "deletion_consent"),
        ]
    )
    def test_deletion_request_needs_query_count_and_consent(self, _name: str, change: dict, field: str) -> None:
        data = {key: value for key, value in {**DELETION_REQUEST, **change}.items() if value is not None}
        serializer = CreatePostHogSupportTicketSerializer(data=data)
        assert not serializer.is_valid()
        assert field in serializer.errors

    def test_ticket_over_widget_message_limit_is_rejected(self) -> None:
        data = {
            **DELETION_REQUEST,
            "description": "d" * 4000,
            "expected": "e" * 1000,
            "actual": "a" * 1000,
            "already_tried": "t" * 1000,
            "deletion_query": "q" * 4000,
        }
        serializer = CreatePostHogSupportTicketSerializer(data=data)
        assert not serializer.is_valid()
        assert "description" in serializer.errors


class TestPostHogSupportTicketAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        support_org = Organization.objects.create(name="Support")
        self.support_team = Team.objects.create(
            organization=support_org,
            conversations_enabled=True,
            conversations_settings={"widget_public_token": SUPPORT_WIDGET_TOKEN},
        )
        # The support project verifies with its own signing secret, which holds the same value as the instance setting.
        SigningSecret.objects.for_team(self.support_team.id).create(
            team_id=self.support_team.id, secret=SIGNING_SECRET, rotated_independently=True
        )
        self.user.is_email_verified = True
        self.user.save()
        self.url = f"/api/projects/{self.team.id}/posthog_support/tickets/"

    def _forward_to_widget(self, method: str, url: str, **kwargs: Any) -> Any:
        widget_response = self.client.generic(
            method,
            urlparse(url).path,
            data=json.dumps(kwargs["json"]),
            content_type="application/json",
            headers=kwargs["headers"],
        )
        response = MagicMock(status_code=widget_response.status_code, ok=widget_response.status_code < 400)
        response.json.return_value = widget_response.json()
        return response

    def _post(
        self,
        body: dict[str, Any],
        *,
        flag_on: bool = True,
        token: str = SUPPORT_WIDGET_TOKEN,
        network_error: bool = False,
        headers: dict[str, str] | None = None,
    ) -> Any:
        with (
            override_instance_config("CONVERSATIONS_SUPPORT_WIDGET_TOKEN", token),
            override_instance_config("CONVERSATIONS_HMAC_SIGNING_SECRET", SIGNING_SECRET),
            patch(
                "products.conversations.backend.api.posthog_support.posthoganalytics.feature_enabled",
                return_value=flag_on,
            ) as self.feature_enabled,
            patch(
                "products.conversations.backend.services.posthog_support.requests.request",
                side_effect=requests.ConnectionError() if network_error else self._forward_to_widget,
            ),
        ):
            return self.client.post(self.url, body, format="json", headers=headers or {})

    def _run_token_headers(self, scope: str, *, sandbox_task_id: Any = None) -> dict[str, str]:
        app = OAuthApplication.objects.create(
            name="sandbox",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=app,
            token=f"pha_{uuid4().hex}",
            scope=scope,
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[self.team.id],
            scoped_organizations=[],
            sandbox_task_id=sandbox_task_id,
        )
        self.client.logout()
        return {"Authorization": f"Bearer {token.token}"}

    def test_ticket_reaches_support_inbox_verified_as_the_user(self) -> None:
        response = self._post(DELETION_REQUEST)

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        ticket = Ticket.objects.get(team=self.support_team, id=response.json()["ticket_id"])
        assert ticket.identity_verified is True
        assert ticket.distinct_id == self.user.distinct_id
        assert ticket.session_context["project_id"] == str(self.team.id)
        assert ticket.session_context["request_type"] == "data_deletion"
        assert ticket.session_context["credential"] == "session"
        # The MCP server evaluates the flag with these groups, so an organization rollout must match.
        assert self.feature_enabled.call_args.kwargs["groups"] == {
            "organization": str(self.team.organization_id),
            "project": str(self.team.id),
        }
        message = Comment.objects.get(team=self.support_team, item_id=str(ticket.id)).content
        assert message is not None
        assert DELETION_QUERY in message
        assert "Expected event count: 120" in message

    @parameterized.expand(
        [
            ("flag_off", {"flag_on": False}, status.HTTP_403_FORBIDDEN),
            ("no_support_inbox", {"token": ""}, status.HTTP_503_SERVICE_UNAVAILABLE),
            ("support_inbox_rejects", {"token": "not_the_support_token"}, status.HTTP_502_BAD_GATEWAY),
            ("support_inbox_unreachable", {"network_error": True}, status.HTTP_502_BAD_GATEWAY),
        ]
    )
    def test_ticket_is_not_opened(self, _name: str, kwargs: dict[str, Any], expected_status: int) -> None:
        response = self._post(DELETION_REQUEST, **kwargs)

        assert response.status_code == expected_status
        assert not Ticket.objects.filter(team=self.support_team).exists()

    @parameterized.expand(
        [
            ("sandbox_origin_header", None, None),
            ("internal_run_token", "posthog_support:write internal_run:read", None),
            ("task_bound_token", "posthog_support:write", "11111111-1111-1111-1111-111111111111"),
        ]
    )
    def test_agent_run_cannot_open_a_ticket(self, _name: str, scope: str | None, sandbox_task_id: str | None) -> None:
        if scope is None:
            headers = {"X-PostHog-Sandbox-Origin": "1"}
        else:
            headers = self._run_token_headers(scope, sandbox_task_id=sandbox_task_id)

        response = self._post(DELETION_REQUEST, headers=headers)

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert not Ticket.objects.filter(team=self.support_team).exists()

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_rejected_requests_do_not_use_up_the_ticket_budget(self, _rate_limit_enabled: MagicMock) -> None:
        # The burst limit is 5 an hour. Agents retry on a 400, and those retries must not lock the user out.
        for _ in range(6):
            assert self._post({**DELETION_REQUEST, "deletion_consent": False}).status_code == 400

        statuses = [self._post(DELETION_REQUEST).status_code for _ in range(6)]

        assert statuses == [status.HTTP_201_CREATED] * 5 + [status.HTTP_429_TOO_MANY_REQUESTS]
