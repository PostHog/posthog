from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

import requests
from parameterized import parameterized
from rest_framework import status

from posthog.models import ActivityLog, Integration, Organization, Team
from posthog.models.github_integration_base import GitHubIntegrationError

from products.conversations.backend.github_link_metadata import METADATA_STALE_AFTER
from products.conversations.backend.github_references import GithubReference, parse_github_reference
from products.conversations.backend.models import Ticket, TicketGithubLink, TicketGithubLinkType
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.tasks import refresh_ticket_github_links

GITHUB_INTEGRATION_CLASS = "products.conversations.backend.github_link_metadata.GitHubIntegration"

ISSUE_URL = "https://github.com/PostHog/posthog/issues/123"
PR_URL = "https://github.com/PostHog/posthog/pull/456"


class TestParseGithubReference(SimpleTestCase):
    @parameterized.expand(
        [
            (ISSUE_URL, GithubReference(repo="PostHog/posthog", number=123, link_type=TicketGithubLinkType.ISSUE)),
            (PR_URL, GithubReference(repo="PostHog/posthog", number=456, link_type=TicketGithubLinkType.PULL_REQUEST)),
            (
                "  https://www.github.com/owner/repo.js/pull/7/files?diff=split#diff-abc  ",
                GithubReference(repo="owner/repo.js", number=7, link_type=TicketGithubLinkType.PULL_REQUEST),
            ),
            (
                "http://github.com/owner/repo/pulls/9",
                GithubReference(repo="owner/repo", number=9, link_type=TicketGithubLinkType.PULL_REQUEST),
            ),
            ("https://gitlab.com/owner/repo/issues/1", None),
            ("https://github.com/owner/repo", None),
            ("https://github.com/owner/repo/commit/abc123", None),
            ("https://github.com/owner/repo/issues/abc", None),
            ("https://github.com/owner/repo/issues/0", None),
            (
                "https://github.com/owner/repo/issues/1",
                GithubReference(repo="owner/repo", number=1, link_type=TicketGithubLinkType.ISSUE),
            ),
            ("PostHog/posthog#123", GithubReference(repo="PostHog/posthog", number=123, link_type=None)),
            (" owner/repo.js#7 ", GithubReference(repo="owner/repo.js", number=7, link_type=None)),
            ("PostHog/posthog#0", None),
            ("posthog#123", None),
            ("owner/repo/extra#1", None),
            ("javascript:alert(1)", None),
        ]
    )
    def test_parse(self, url: str, expected: GithubReference | None) -> None:
        assert parse_github_reference(url) == expected


def github_issue_payload(
    *, title: str = "Fix the thing", pull_request: bool = False, state: str = "open", merged: bool = False
):
    payload: dict = {"title": title, "state": state}
    if pull_request:
        payload["pull_request"] = {"merged_at": "2026-08-20T10:00:00Z" if merged else None}
    return payload


class TestTicketGithubLinksAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-1",
            distinct_id="user-1",
            status=Status.NEW,
        )
        self.links_url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/github_links/"

    def _add_github_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id=str(Integration.objects.count() + 1),
            config={"account": {"name": "org"}},
        )

    def test_link_list_and_unlink_round_trip(self) -> None:
        created = self.client.post(self.links_url, {"url": PR_URL})
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        body = created.json()
        assert body["repo"] == "PostHog/posthog"
        assert body["number"] == 456
        assert body["link_type"] == "pull_request"
        assert body["url"] == PR_URL
        assert body["title"] is None
        assert body["link_state"] is None
        assert body["created_by"]["id"] == self.user.id

        listed = self.client.get(self.links_url)
        assert listed.status_code == status.HTTP_200_OK
        assert [link["id"] for link in listed.json()] == [body["id"]]

        removed = self.client.delete(f"{self.links_url}{body['id']}/")
        assert removed.status_code == status.HTTP_204_NO_CONTENT
        assert self.client.get(self.links_url).json() == []

        actions = list(
            ActivityLog.objects.filter(scope="Ticket", item_id=str(self.ticket.id))
            .order_by("created_at")
            .values_list("detail__changes__0__action", flat=True)
        )
        assert actions == ["created", "deleted"]

    @parameterized.expand(
        [(ISSUE_URL + "#issuecomment-1",), ("posthog/posthog#123",), ("https://github.com/posthog/POSTHOG/issues/123",)]
    )
    def test_linking_the_same_issue_twice_returns_the_existing_link(self, second_value: str) -> None:
        first = self.client.post(self.links_url, {"url": ISSUE_URL})
        second = self.client.post(self.links_url, {"url": second_value})
        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_200_OK
        assert second.json()["id"] == first.json()["id"]
        assert TicketGithubLink.objects.for_team(self.team.id).count() == 1

    def test_rejects_non_github_url(self) -> None:
        response = self.client.post(self.links_url, {"url": "https://example.com/owner/repo/issues/1"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "url"

    def test_links_are_scoped_to_the_ticket_and_team(self) -> None:
        other_ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="session-2",
            distinct_id="user-2",
            status=Status.NEW,
        )
        other_url = f"/api/projects/{self.team.id}/conversations/tickets/{other_ticket.id}/github_links/"
        link_id = self.client.post(other_url, {"url": ISSUE_URL}).json()["id"]

        assert self.client.get(self.links_url).json() == []
        assert self.client.delete(f"{self.links_url}{link_id}/").status_code == status.HTTP_404_NOT_FOUND
        assert TicketGithubLink.objects.for_team(self.team.id).filter(id=link_id).exists()

        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other team")
        foreign = self.client.post(
            f"/api/projects/{other_team.id}/conversations/tickets/{self.ticket.id}/github_links/",
            {"url": ISSUE_URL},
        )
        assert foreign.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

    @parameterized.expand(
        [
            ("PostHog/posthog#42", github_issue_payload(title="Add a thing"), "issue", "open"),
            ("PostHog/posthog#42", github_issue_payload(title="Add a thing", state="closed"), "issue", "closed"),
            ("PostHog/posthog#42", github_issue_payload(title="Fix it", pull_request=True), "pull_request", "open"),
            (
                "PostHog/posthog#42",
                github_issue_payload(title="Fix it", pull_request=True, state="closed", merged=True),
                "pull_request",
                "merged",
            ),
            (ISSUE_URL, github_issue_payload(title="From URL", pull_request=True), "pull_request", "open"),
        ]
    )
    @patch(GITHUB_INTEGRATION_CLASS)
    def test_link_resolves_title_state_and_type_from_github(
        self, value: str, payload: dict, expected_type: str, expected_state: str, github_cls: MagicMock
    ) -> None:
        self._add_github_integration()
        github_cls.return_value.get_issue.return_value = payload

        body = self.client.post(self.links_url, {"url": value}).json()

        github_cls.return_value.get_issue.assert_called_once_with(
            "PostHog/posthog", body["number"], timeout=5, retry_transient=False
        )
        assert body["title"] == payload["title"]
        assert body["link_type"] == expected_type
        assert body["link_state"] == expected_state
        expected_path = "pull" if expected_type == "pull_request" else "issues"
        assert body["url"] == f"https://github.com/PostHog/posthog/{expected_path}/{body['number']}"

    @patch(GITHUB_INTEGRATION_CLASS)
    def test_lookup_moves_on_to_the_next_integration_when_the_first_cannot_see_the_repo(
        self, github_cls: MagicMock
    ) -> None:
        self._add_github_integration()
        self._add_github_integration()
        blind, sighted = MagicMock(), MagicMock()
        blind.get_issue.side_effect = GitHubIntegrationError("not found", status_code=404)
        sighted.get_issue.return_value = github_issue_payload(title="Seen by the second app")
        github_cls.side_effect = [blind, sighted]

        body = self.client.post(self.links_url, {"url": ISSUE_URL}).json()
        assert body["title"] == "Seen by the second app"

    def test_shorthand_without_integration_is_stored_as_an_issue(self) -> None:
        body = self.client.post(self.links_url, {"url": "PostHog/posthog#77"}).json()
        assert body["link_type"] == "issue"
        assert body["url"] == "https://github.com/PostHog/posthog/issues/77"
        assert body["title"] is None

    @parameterized.expand(
        [
            (GitHubIntegrationError("server error", status_code=502),),
            (requests.ConnectionError("github unreachable"),),
        ]
    )
    @patch(GITHUB_INTEGRATION_CLASS)
    def test_github_failure_still_creates_a_bare_link(self, error: Exception, github_cls: MagicMock) -> None:
        self._add_github_integration()
        github_cls.return_value.get_issue.side_effect = error

        response = self.client.post(self.links_url, {"url": PR_URL})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["title"] is None
        assert response.json()["link_type"] == "pull_request"

    @patch("products.conversations.backend.tasks.refresh_ticket_github_links.delay")
    def test_list_schedules_one_background_refresh_for_stale_links_only(self, delay: MagicMock) -> None:
        link_id = self.client.post(self.links_url, {"url": ISSUE_URL}).json()["id"]

        self.client.get(self.links_url)
        delay.assert_not_called()

        TicketGithubLink.objects.for_team(self.team.id).filter(id=link_id).update(
            metadata_synced_at=timezone.now() - METADATA_STALE_AFTER * 2
        )
        self.client.get(self.links_url)
        self.client.get(self.links_url)
        delay.assert_called_once_with(team_id=self.team.id, ticket_id=str(self.ticket.id))

    @patch(GITHUB_INTEGRATION_CLASS)
    def test_refresh_task_updates_stale_links_and_leaves_fresh_ones(self, github_cls: MagicMock) -> None:
        self._add_github_integration()
        github_cls.return_value.get_issue.return_value = github_issue_payload(title="Old title")
        stale_id = self.client.post(self.links_url, {"url": ISSUE_URL}).json()["id"]
        fresh_id = self.client.post(self.links_url, {"url": PR_URL}).json()["id"]
        TicketGithubLink.objects.for_team(self.team.id).filter(id=stale_id).update(
            metadata_synced_at=timezone.now() - METADATA_STALE_AFTER * 2
        )
        github_cls.return_value.get_issue.reset_mock()
        github_cls.return_value.get_issue.return_value = github_issue_payload(title="New title", state="closed")

        refresh_ticket_github_links(self.team.id, str(self.ticket.id))

        github_cls.return_value.get_issue.assert_called_once()
        by_id = {str(link.id): link for link in TicketGithubLink.objects.for_team(self.team.id)}
        assert (by_id[stale_id].title, by_id[stale_id].link_state) == ("New title", "closed")
        assert by_id[fresh_id].title == "Old title"
