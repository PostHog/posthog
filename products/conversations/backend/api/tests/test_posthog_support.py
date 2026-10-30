import json
from typing import Any
from urllib.parse import urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.comment import Comment
from posthog.models.instance_setting import override_instance_config

from products.conversations.backend.api.posthog_support import CreatePostHogSupportTicketSerializer
from products.conversations.backend.models import SigningSecret, Ticket

SUPPORT_WIDGET_TOKEN = "support_widget_token"
SIGNING_SECRET = "support_signing_secret"

DELETION_REQUEST = {
    "request_type": "data_deletion",
    "subject": "Delete test events",
    "description": "Test events sent from a staging build reached production.",
    "deletion_query": "SELECT uuid FROM events\nWHERE event = 'test_event' AND timestamp < '2026-10-01'",
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
    ) -> Any:
        with (
            override_instance_config("CONVERSATIONS_SUPPORT_WIDGET_TOKEN", token),
            override_instance_config("CONVERSATIONS_HMAC_SIGNING_SECRET", SIGNING_SECRET),
            patch(
                "products.conversations.backend.api.posthog_support.posthoganalytics.feature_enabled",
                return_value=flag_on,
            ),
            patch(
                "products.conversations.backend.services.posthog_support.requests.request",
                side_effect=requests.ConnectionError() if network_error else self._forward_to_widget,
            ),
        ):
            return self.client.post(self.url, body, format="json")

    def test_ticket_reaches_support_inbox_verified_as_the_user(self) -> None:
        response = self._post(DELETION_REQUEST)

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        ticket = Ticket.objects.get(team=self.support_team, id=response.json()["ticket_id"])
        assert ticket.identity_verified is True
        assert ticket.distinct_id == self.user.distinct_id
        assert ticket.session_context["project_id"] == str(self.team.id)
        assert ticket.session_context["request_type"] == "data_deletion"
        message = Comment.objects.get(team=self.support_team, item_id=str(ticket.id)).content
        assert DELETION_REQUEST["deletion_query"] in message
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
