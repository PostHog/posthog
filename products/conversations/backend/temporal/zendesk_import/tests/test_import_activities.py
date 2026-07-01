from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket, ZendeskImportJob
from products.conversations.backend.models.constants import Priority, Status
from products.conversations.backend.temporal.zendesk_import import activities
from products.conversations.backend.temporal.zendesk_import.activities import (
    ImportBatchInput,
    _import_ticket_batch_sync,
    _parse_zendesk_datetime,
)


class _FakeZendeskClient:
    def __init__(
        self,
        *,
        tickets: list[dict[str, Any]],
        users: dict[int, dict[str, Any]],
        comments: dict[int, list[dict[str, Any]]],
        attachment_bytes: dict[str, bytes] | None = None,
    ) -> None:
        self._tickets = {int(t["id"]): t for t in tickets}
        self._users = {int(uid): u for uid, u in users.items()}
        self._comments = comments
        self._attachment_bytes = attachment_bytes or {}

    def fetch_tickets(self, ticket_ids: list[int]) -> list[dict[str, Any]]:
        return [self._tickets[i] for i in ticket_ids if i in self._tickets]

    def fetch_users(self, user_ids: list[int]) -> dict[int, dict[str, Any]]:
        return {i: self._users[i] for i in user_ids if i in self._users}

    def fetch_comments(self, ticket_id: int) -> list[dict[str, Any]]:
        return self._comments.get(ticket_id, [])

    def download_attachment(self, content_url: str) -> bytes:
        if content_url in self._attachment_bytes:
            return self._attachment_bytes[content_url]
        raise RuntimeError("download failed")


def _comment(cid: int, author_id: int, body: str, created_at: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": cid,
        "author_id": author_id,
        "public": extra.pop("public", True),
        "body": body,
        "created_at": created_at,
        "attachments": extra.pop("attachments", []),
        **extra,
    }


class TestZendeskImportBatch(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.job = ZendeskImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=ZendeskImportJob.Status.RUNNING,
            job_inputs={"subdomain": "acme", "email_address": "agent@example.com", "api_token": "token"},
        )

    def _run(self, client: _FakeZendeskClient, ticket_ids: list[int], persons: dict | None = None):
        with (
            patch.object(activities, "ZendeskImportClient", return_value=client),
            patch.object(activities, "_get_persons_by_email", return_value=persons or {}),
        ):
            return _import_ticket_batch_sync(
                ImportBatchInput(job_id=str(self.job.id), team_id=self.team.id, ticket_ids=ticket_ids)
            )

    def test_import_sets_counters_and_historical_timestamps(self) -> None:
        client = _FakeZendeskClient(
            tickets=[
                {
                    "id": 100,
                    "requester_id": 1,
                    "status": "open",
                    "priority": "high",
                    "subject": "Help",
                    "created_at": "2020-01-01T00:00:00Z",
                    "updated_at": "2020-01-05T00:00:00Z",
                }
            ],
            users={
                1: {"id": 1, "email": "alice@example.com", "role": "end-user"},
                2: {"id": 2, "email": "agent@example.com", "role": "agent"},
            },
            comments={
                100: [
                    _comment(1, 1, "hi", "2020-01-01T00:00:00Z"),
                    _comment(2, 2, "hello", "2020-01-02T00:00:00Z"),
                    _comment(3, 1, "thanks", "2020-01-03T00:00:00Z"),
                ]
            },
        )
        result = self._run(client, [100])

        assert (result.imported, result.skipped, result.failed) == (1, 0, 0)
        ticket = Ticket.objects.filter(team_id=self.team.id).get(zendesk_ticket_id=100)
        assert ticket.status == Status.OPEN
        assert ticket.priority == Priority.HIGH
        assert ticket.email_from == "alice@example.com"
        # 2 customer messages hit unread_team_count, 1 support message hits unread_customer_count.
        assert ticket.message_count == 3
        assert ticket.unread_team_count == 2
        assert ticket.unread_customer_count == 1
        assert ticket.last_message_text == "thanks"
        assert ticket.last_message_at == _parse_zendesk_datetime("2020-01-03T00:00:00Z")
        assert ticket.created_at == _parse_zendesk_datetime("2020-01-01T00:00:00Z")
        assert ticket.updated_at == _parse_zendesk_datetime("2020-01-05T00:00:00Z")

        first = (
            Comment.objects.filter(team=self.team, scope="conversations_ticket", item_id=str(ticket.id))
            .order_by("created_at")
            .first()
        )
        assert first is not None
        assert first.created_at == _parse_zendesk_datetime("2020-01-01T00:00:00Z")

    def test_second_run_skips_already_imported(self) -> None:
        client = _FakeZendeskClient(
            tickets=[{"id": 200, "requester_id": 1, "status": "open", "created_at": "2020-01-01T00:00:00Z"}],
            users={1: {"id": 1, "email": "alice@example.com", "role": "end-user"}},
            comments={200: [_comment(1, 1, "hi", "2020-01-01T00:00:00Z")]},
        )
        first = self._run(client, [200])
        assert (first.imported, first.skipped) == (1, 0)

        second = self._run(client, [200])
        assert (second.imported, second.skipped) == (0, 1)
        assert Ticket.objects.filter(team_id=self.team.id).filter(zendesk_ticket_id=200).count() == 1

    def test_ticket_numbers_are_unique_and_sequential(self) -> None:
        client = _FakeZendeskClient(
            tickets=[
                {"id": tid, "requester_id": 1, "status": "open", "created_at": "2020-01-01T00:00:00Z"}
                for tid in (301, 302, 303)
            ],
            users={1: {"id": 1, "email": "alice@example.com", "role": "end-user"}},
            comments={},
        )
        result = self._run(client, [301, 302, 303])
        assert result.imported == 3

        numbers = sorted(
            Ticket.objects.filter(team_id=self.team.id)
            .filter(zendesk_ticket_id__in=[301, 302, 303])
            .values_list("ticket_number", flat=True)
        )
        assert len(set(numbers)) == 3
        assert numbers == list(range(numbers[0], numbers[0] + 3))

    def test_person_match_sets_distinct_id_with_email_fallback(self) -> None:
        client = _FakeZendeskClient(
            tickets=[
                {"id": 400, "requester_id": 1, "status": "open", "created_at": "2020-01-01T00:00:00Z"},
                {"id": 401, "requester_id": 2, "status": "open", "created_at": "2020-01-01T00:00:00Z"},
            ],
            users={
                1: {"id": 1, "email": "alice@example.com", "role": "end-user"},
                2: {"id": 2, "email": "bob@example.com", "role": "end-user"},
            },
            comments={},
        )
        self._run(client, [400, 401], persons={"alice@example.com": SimpleNamespace(distinct_ids=["person-1"])})

        matched = Ticket.objects.filter(team_id=self.team.id).get(zendesk_ticket_id=400)
        unmatched = Ticket.objects.filter(team_id=self.team.id).get(zendesk_ticket_id=401)
        assert matched.distinct_id == "person-1"
        assert unmatched.distinct_id == "bob@example.com"

    def test_attachments_embed_image_and_isolate_failed_download(self) -> None:
        client = _FakeZendeskClient(
            tickets=[{"id": 500, "requester_id": 1, "status": "open", "created_at": "2020-01-01T00:00:00Z"}],
            users={1: {"id": 1, "email": "alice@example.com", "role": "end-user"}},
            comments={
                500: [
                    _comment(
                        1,
                        1,
                        "see attached",
                        "2020-01-01T00:00:00Z",
                        attachments=[
                            {"content_url": "good", "content_type": "image/png", "file_name": "img.png"},
                            {"content_url": "bad", "content_type": "image/png", "file_name": "bad.png"},
                        ],
                    )
                ]
            },
            attachment_bytes={"good": b"imgdata"},
        )
        with patch.object(activities, "save_file_to_uploaded_media", return_value="http://media/img.png"):
            result = self._run(client, [500])

        assert (result.imported, result.failed) == (1, 0)
        ticket = Ticket.objects.filter(team_id=self.team.id).get(zendesk_ticket_id=500)
        comment = Comment.objects.get(team=self.team, scope="conversations_ticket", item_id=str(ticket.id))
        assert "http://media/img.png" in (comment.content or "")
        image_nodes = [n for n in (comment.rich_content or {}).get("content", []) if n.get("type") == "image"]
        assert len(image_nodes) == 1
        assert image_nodes[0]["attrs"]["src"] == "http://media/img.png"
