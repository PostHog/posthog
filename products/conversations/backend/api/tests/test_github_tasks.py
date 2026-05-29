from typing import Any

from posthog.test.base import BaseTest

from django.core.cache import cache

from parameterized import parameterized

from posthog.models.comment import Comment
from posthog.models.integration import Integration

from products.conversations.backend.models import GithubCommentMapping, Ticket
from products.conversations.backend.models.constants import Status
from products.conversations.backend.tasks import process_github_event


def _issue_payload(
    *,
    action: str = "opened",
    installation_id: int = 12345,
    repo: str = "org/repo",
    issue_number: int = 42,
    title: str = "Bug report",
    body: str = "Description",
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


def _comment_payload(
    *,
    issue_number: int = 42,
    comment_id: int = 7001,
    comment_body: str = "A comment",
    comment_login: str = "contributor",
    repo: str = "org/repo",
    performed_via_github_app: dict | None = None,
) -> dict[str, Any]:
    comment: dict[str, Any] = {
        "id": comment_id,
        "body": comment_body,
        "user": {"login": comment_login},
    }
    if performed_via_github_app is not None:
        comment["performed_via_github_app"] = performed_via_github_app
    return {
        "action": "created",
        "installation": {"id": 12345},
        "repository": {"full_name": repo},
        "issue": {
            "number": issue_number,
            "title": "Bug report",
            "body": "",
            "user": {"login": "octocat"},
        },
        "comment": comment,
        "sender": {"login": comment_login},
    }


class TestProcessGithubEvent(BaseTest):
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
        cache.clear()

    def _run(self, payload: dict, event_type: str = "issues", delivery_id: str = "d-1"):
        process_github_event(
            event_type=event_type,
            action=payload["action"],
            payload=payload,
            delivery_id=delivery_id,
            team_id=self.team.id,
            repo=payload["repository"]["full_name"],
        )

    def test_creates_ticket_on_issue_opened(self):
        self._run(_issue_payload())

        ticket = Ticket.objects.get(team=self.team, github_repo="org/repo", github_issue_number=42)
        assert ticket.channel_source == "github"
        assert ticket.channel_detail == "github_issue"
        assert ticket.status == Status.NEW

        comment = Comment.objects.get(team=self.team, item_id=str(ticket.id))
        assert comment.content is not None
        assert "**Bug report**" in comment.content
        assert "Description" in comment.content

    def test_does_not_create_duplicate_ticket(self):
        self._run(_issue_payload(), delivery_id="d-1")
        self._run(_issue_payload(), delivery_id="d-2")

        assert Ticket.objects.filter(team=self.team, github_repo="org/repo", github_issue_number=42).count() == 1

    @parameterized.expand(
        [
            # (name, actions_sequence, expected_status)
            ("opened_then_closed", ["opened", "closed"], Status.RESOLVED),
            ("opened_closed_reopened", ["opened", "closed", "reopened"], Status.OPEN),
            ("opened_stays_new", ["opened"], Status.NEW),
        ]
    )
    def test_status_transitions(self, _name, actions, expected_status):
        for idx, action in enumerate(actions):
            self._run(_issue_payload(action=action), delivery_id=f"d-{idx}")

        ticket = Ticket.objects.get(team=self.team, github_repo="org/repo", github_issue_number=42)
        assert ticket.status == expected_status

    @parameterized.expand(
        [
            ("unmonitored_repo", {"repo": "other/repo"}, {}),
            ("github_disabled", {}, {"github_enabled": False}),
        ]
    )
    def test_event_ignored(self, _name, payload_kwargs, settings_override):
        if settings_override:
            self.team.conversations_settings.update(settings_override)
            self.team.save()

        self._run(_issue_payload(**payload_kwargs))
        assert Ticket.objects.filter(team=self.team, github_repo=payload_kwargs.get("repo", "org/repo")).count() == 0

    def test_idempotency_skips_duplicate_delivery(self):
        self._run(_issue_payload(), delivery_id="dup-1")
        initial_count = Ticket.objects.filter(team=self.team).count()

        self._run(_issue_payload(issue_number=99), delivery_id="dup-1")
        assert Ticket.objects.filter(team=self.team).count() == initial_count


class TestHandleGithubCommentEvent(BaseTest):
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
        cache.clear()

        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source="github",
            channel_detail="github_issue",
            widget_session_id="",
            distinct_id="github:octocat",
            github_repo="org/repo",
            github_issue_number=42,
        )

    def _run(self, payload: dict, delivery_id: str = "d-1"):
        process_github_event(
            event_type="issue_comment",
            action=payload["action"],
            payload=payload,
            delivery_id=delivery_id,
            team_id=self.team.id,
            repo=payload["repository"]["full_name"],
        )

    def test_creates_comment_on_existing_ticket(self):
        self._run(_comment_payload())

        comment = Comment.objects.get(team=self.team, item_id=str(self.ticket.id))
        assert comment.content == "A comment"
        assert GithubCommentMapping.objects.filter(github_comment_id=7001, team=self.team).exists()

    @parameterized.expand(
        [
            (
                "duplicate_mapping",
                {"comment_id": 7001},
                {"comment_id": 7001},
                True,
                1,
            ),
            (
                "app_echo",
                {"comment_id": 8001, "performed_via_github_app": {"id": 123, "slug": "my-app"}},
                None,
                False,
                0,
            ),
        ]
    )
    def test_comment_skipped(self, _name, first_kwargs, second_kwargs, mapping_exists, expected_comments):
        self._run(_comment_payload(**first_kwargs), delivery_id="d-1")
        if second_kwargs:
            self._run(_comment_payload(**second_kwargs), delivery_id="d-2")

        assert Comment.objects.filter(team=self.team, item_id=str(self.ticket.id)).count() == expected_comments
        if mapping_exists:
            assert GithubCommentMapping.objects.filter(
                github_comment_id=first_kwargs["comment_id"], team=self.team
            ).exists()

    def test_lazy_creates_ticket_for_unknown_issue(self):
        self._run(_comment_payload(issue_number=99, comment_id=9001))

        ticket = Ticket.objects.get(team=self.team, github_repo="org/repo", github_issue_number=99)
        assert ticket.channel_source == "github"
        assert Comment.objects.filter(team=self.team, item_id=str(ticket.id)).count() >= 1
