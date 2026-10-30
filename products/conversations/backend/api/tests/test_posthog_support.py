import uuid
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.instance_setting import override_instance_config
from posthog.models.user import User

from products.conversations.backend.services.posthog_support import MAX_OPEN_DRAFTS_PER_USER

DRAFT_BODY = {
    "customer_words": "My funnel shows zero conversions since Tuesday",
    "filing_reason": "user_asked_for_support",
    "details": "Insight id 123, posthog-js 1.200.0",
}


def _widget_response(status_code: int, body: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = body or {}
    return response


@override_settings(
    POSTHOG_SUPPORT_WIDGET_TOKEN="widget-token", POSTHOG_SUPPORT_WIDGET_HOST="https://support.example.com"
)
class TestPostHogSupportAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.id}/posthog_support"

    def _token_headers(self, scopes: list[str]) -> dict[str, str]:
        self.client.logout()
        return {"HTTP_AUTHORIZATION": f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"}

    def test_token_can_draft_but_never_complete_a_send(self) -> None:
        headers = self._token_headers(["posthog_support:write"])

        created = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json", **headers)
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        draft = created.json()
        assert draft["sent"] is False
        assert draft["review_url"].endswith(f"/project/{self.team.id}/my-tickets?support_draft={draft['id']}")
        assert draft["message"].startswith("In my words:\nMy funnel shows zero conversions since Tuesday")

        claim_url = f"{self.base}/drafts/{draft['id']}/claim/"
        assert self.client.post(claim_url, **headers).status_code == status.HTTP_403_FORBIDDEN

        self.client.force_login(self.user)
        assert self.client.get(f"{self.base}/drafts/{draft['id']}/").status_code == status.HTTP_200_OK
        assert self.client.post(claim_url).status_code == status.HTTP_204_NO_CONTENT
        assert self.client.post(claim_url).status_code == status.HTTP_204_NO_CONTENT
        other_tab = APIClient()
        other_tab.force_login(self.user)
        assert other_tab.post(claim_url).status_code == status.HTTP_404_NOT_FOUND
        assert other_tab.get(f"{self.base}/drafts/{draft['id']}/").status_code == status.HTTP_404_NOT_FOUND

    def test_drafts_are_private_to_the_user_who_owns_them(self) -> None:
        draft_id = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json").json()["id"]

        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        self.client.force_login(teammate)

        assert self.client.get(f"{self.base}/drafts/{draft_id}/").status_code == status.HTTP_404_NOT_FOUND
        assert self.client.post(f"{self.base}/drafts/{draft_id}/discard/").status_code == status.HTTP_404_NOT_FOUND

    def test_open_drafts_are_capped_per_user(self) -> None:
        draft_ids = [
            self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json").json()["id"]
            for _ in range(MAX_OPEN_DRAFTS_PER_USER)
        ]

        assert self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json").status_code == 429

        assert self.client.post(f"{self.base}/drafts/{draft_ids[0]}/discard/").status_code == 204
        assert self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json").status_code == 201

    @parameterized.expand(
        [
            ("filing_on_agent_diagnosis", {**DRAFT_BODY, "filing_reason": "agent_thinks_it_is_a_bug"}),
            ("missing_customer_words", {"filing_reason": "user_asked_for_support"}),
        ]
    )
    def test_draft_requires_the_persons_words_and_a_human_driven_reason(self, _name: str, body: dict) -> None:
        assert self.client.post(f"{self.base}/drafts/", body, format="json").status_code == 400

    @patch("products.conversations.backend.services.posthog_support.requests.get")
    def test_lists_tickets_with_the_users_signed_identity(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _widget_response(
            200,
            {
                "count": 1,
                "results": [
                    {
                        "id": str(uuid.uuid4()),
                        "ticket_number": 42,
                        "status": "open",
                        "unread_count": 1,
                        "last_message": "We are looking into it",
                        "last_message_at": "2026-10-30T10:00:00Z",
                        "message_count": 2,
                        "created_at": "2026-10-29T10:00:00Z",
                    }
                ],
            },
        )

        with override_instance_config("CONVERSATIONS_HMAC_SIGNING_SECRET", "secret"):
            response = self.client.get(
                f"{self.base}/tickets/?status=open", **self._token_headers(["posthog_support:read"])
            )

        assert response.status_code == 200, response.json()
        assert response.json()["results"][0]["ticket_number"] == 42
        url = mock_get.call_args.args[0]
        params = mock_get.call_args.kwargs["params"]
        headers = mock_get.call_args.kwargs["headers"]
        assert url == "https://support.example.com/api/conversations/v1/widget/tickets"
        assert params["identity_distinct_id"] == self.user.distinct_id
        assert params["status"] == "open"
        assert params["widget_session_id"]
        assert headers["X-Conversations-Token"] == "widget-token"

    @parameterized.expand(
        [
            ("missing_ticket", 404, 200, status.HTTP_404_NOT_FOUND),
            ("another_persons_ticket", 403, 200, status.HTTP_404_NOT_FOUND),
            ("identity_rejected", 403, 403, 503),
        ]
    )
    @patch("products.conversations.backend.services.posthog_support.requests.get")
    def test_ticket_refusals_separate_not_found_from_a_broken_identity(
        self, _name: str, thread_status: int, list_status: int, expected_status: int, mock_get: MagicMock
    ) -> None:
        mock_get.side_effect = [
            _widget_response(thread_status, {"error": "Forbidden"}),
            _widget_response(
                list_status, {"count": 0, "results": []} if list_status == 200 else {"error": "Forbidden"}
            ),
        ]

        with override_instance_config("CONVERSATIONS_HMAC_SIGNING_SECRET", "secret"):
            response = self.client.get(f"{self.base}/tickets/{uuid.uuid4()}/messages/")

        assert response.status_code == expected_status

    def test_tickets_are_unavailable_without_identity_signing(self) -> None:
        with override_instance_config("CONVERSATIONS_HMAC_SIGNING_SECRET", ""):
            response = self.client.get(f"{self.base}/tickets/")

        assert response.status_code == 503
