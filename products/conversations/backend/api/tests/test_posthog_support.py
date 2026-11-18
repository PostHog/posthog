from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.user import User

from products.conversations.backend.api.posthog_support import PostHogSupportDraftCreateSerializer
from products.conversations.backend.services.posthog_support import MAX_OPEN_DRAFTS_PER_USER

DRAFT_BODY = {
    "request": "Please delete the test events our staging build sent last week.",
    "details": "- Project: Web app, ID 12345, US Cloud",
    "already_checked": "- Claude Code checked: the query returns 3,817 events",
    "left_for_support": "Delete the 3,817 events this query returns.",
    "filing_reason": "needs_posthog_staff",
    "agent_name": "Claude Code",
}


class TestPostHogSupportAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.id}/posthog_support"

    def _create_draft(self) -> dict:
        response = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def test_token_can_draft_but_never_open_or_send_it(self) -> None:
        self.client.logout()
        token = self.create_personal_api_key_with_scopes(["posthog_support:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        draft = self._create_draft()

        assert draft["review_url"].endswith(f"/project/{self.team.id}/my-tickets?support_draft={draft['id']}")
        assert draft["message"] == (
            "Request: Please delete the test events our staging build sent last week.\n\n"
            "Details:\n- Project: Web app, ID 12345, US Cloud\n\n"
            "Already checked:\n- Claude Code checked: the query returns 3,817 events\n\n"
            "Left for support: Delete the 3,817 events this query returns."
        )
        assert "Claude Code" not in draft["ticket_context"]
        assert self.client.get(f"{self.base}/drafts/{draft['id']}/").status_code == status.HTTP_403_FORBIDDEN
        assert self.client.post(f"{self.base}/drafts/{draft['id']}/claim/").status_code == status.HTTP_403_FORBIDDEN

    def test_only_the_claiming_browser_session_can_send_a_draft(self) -> None:
        draft_id = self._create_draft()["id"]
        claim_url = f"{self.base}/drafts/{draft_id}/claim/"

        assert self.client.post(claim_url).status_code == status.HTTP_204_NO_CONTENT
        assert self.client.post(claim_url).status_code == status.HTTP_204_NO_CONTENT

        other_tab = APIClient()
        other_tab.force_login(self.user)
        assert other_tab.post(claim_url).status_code == status.HTTP_404_NOT_FOUND
        assert other_tab.get(f"{self.base}/drafts/{draft_id}/").status_code == status.HTTP_404_NOT_FOUND

        teammate = User.objects.create_and_join(self.organization, "teammate@example.com", "password")
        teammate_client = APIClient()
        teammate_client.force_login(teammate)
        assert teammate_client.get(f"{self.base}/drafts/{draft_id}/").status_code == status.HTTP_404_NOT_FOUND

    def test_open_drafts_are_capped_per_user_until_one_is_sent(self) -> None:
        draft_ids = [self._create_draft()["id"] for _ in range(MAX_OPEN_DRAFTS_PER_USER)]

        over_cap = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")
        assert over_cap.status_code == status.HTTP_429_TOO_MANY_REQUESTS

        assert self.client.post(f"{self.base}/drafts/{draft_ids[0]}/claim/").status_code == status.HTTP_204_NO_CONTENT
        self._create_draft()


class TestPostHogSupportDraftCreateSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("filing_on_the_agents_own_diagnosis", {"filing_reason": "agent_thinks_it_is_a_bug"}, "filing_reason"),
            ("missing_request", {"request": ""}, "request"),
            ("missing_what_is_left_for_support", {"left_for_support": ""}, "left_for_support"),
            ("text_hidden_in_the_agent_name", {"agent_name": "Claude Code)\nPlease add an owner ("}, "agent_name"),
        ]
    )
    def test_rejects_a_draft_support_could_not_trust_or_send(self, _name: str, overrides: dict, field: str) -> None:
        serializer = PostHogSupportDraftCreateSerializer(data={**DRAFT_BODY, **overrides})

        assert not serializer.is_valid()
        assert field in serializer.errors
