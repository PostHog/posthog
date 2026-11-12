from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Tag
from posthog.models.comment import Comment

from products.conversations.backend.models import (
    EmailChannel,
    EmailChannelKind,
    IntercomImportJob,
    PurgedTicketThread,
    Ticket,
)
from products.conversations.backend.models.constants import Priority, Status
from products.conversations.backend.models.purged_ticket_thread import ticket_thread_key
from products.conversations.backend.temporal.intercom_import.activities import (
    ImportBatchInput,
    UpdateJobProgressInput,
    _import_conversation_batch_sync,
    _update_job_progress_sync,
)
from products.conversations.backend.temporal.intercom_import.client import IntercomNotFoundError, IntercomRateLimitError

M = "products.conversations.backend.temporal.intercom_import.activities"

CREATED_AT = 1577934245  # 2020-01-02T03:04:05Z
UPDATED_AT = 1578024306  # 2020-01-03T04:05:06Z


def _part(
    pid: str,
    *,
    author_type: str = "admin",
    part_type: str = "comment",
    body: str | None = "reply",
    created_at: int = CREATED_AT + 60,
    name: str | None = "Agent Smith",
    email: str | None = "agent@example.com",
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": pid,
        "part_type": part_type,
        "body": body,
        "created_at": created_at,
        "author": {"type": author_type, "id": f"a-{pid}", "name": name, "email": email},
        "attachments": attachments or [],
    }


def _conversation(
    cid: str,
    *,
    state: str = "open",
    priority: str = "none",
    source_author: dict[str, Any] | None = None,
    source_body: str = "I need help",
    subject: str = "",
    title: str | None = "Help with billing",
    parts: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
    contacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "conversation",
        "id": cid,
        "title": title,
        "state": state,
        "priority": priority,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "source": {
            "id": f"src-{cid}",
            "type": "conversation",
            "subject": subject,
            "body": source_body,
            "author": source_author
            or {"type": "user", "id": "contact-1", "name": "Jane Customer", "email": "jane@example.com"},
            "attachments": [],
        },
        "contacts": {"contacts": contacts or [{"type": "contact", "id": "contact-1"}]},
        "tags": {"tags": [{"type": "tag", "id": str(i), "name": name} for i, name in enumerate(tags or [])]},
        "conversation_parts": {"conversation_parts": parts or [], "total_count": len(parts or [])},
    }


class TestIntercomImportBatchActivity(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.job = IntercomImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=IntercomImportJob.Status.RUNNING,
            job_inputs={"region": "us", "access_token": "fake-token"},
        )

    def _run_batch(
        self,
        conversations: list[dict[str, Any]],
        *,
        contacts: dict[str, Any] | None = None,
        default_email_channel_id: str | None = None,
    ) -> tuple[Any, MagicMock]:
        by_id = {c["id"]: c for c in conversations}
        client = MagicMock()
        client.fetch_conversation.side_effect = lambda cid: by_id[cid]

        def fetch_contact(contact_id: str) -> dict[str, Any]:
            contact = (contacts or {})[contact_id]
            if isinstance(contact, Exception):
                raise contact
            return contact

        client.fetch_contact.side_effect = fetch_contact
        client.download_attachment.return_value = b"filebytes"

        with (
            patch(f"{M}.IntercomImportClient", return_value=client),
            patch(f"{M}.save_file_to_uploaded_media", return_value="https://media.posthog.test/file"),
        ):
            result = _import_conversation_batch_sync(
                ImportBatchInput(
                    job_id=str(self.job.id),
                    team_id=self.team.id,
                    conversation_ids=list(by_id),
                    default_email_channel_id=default_email_channel_id,
                )
            )
        return result, client

    def _comments(self, ticket: Ticket) -> list[Comment]:
        return list(
            Comment.objects.filter(team_id=self.team.id, scope="conversations_ticket", item_id=str(ticket.id)).order_by(
                "created_at"
            )
        )

    def test_import_maps_conversation_thread_and_counters(self) -> None:
        conversation = _conversation(
            "101",
            priority="urgent",
            tags=["Billing", "VIP"],
            parts=[
                _part("p1", body="Looking into it"),
                _part("p2", part_type="note", body="Internal: refund approved", created_at=CREATED_AT + 120),
                _part("p3", part_type="assignment", body="", created_at=CREATED_AT + 130),
                _part(
                    "p5", part_type="side_conversation_reply", body="Vendor: ETA Friday", created_at=CREATED_AT + 150
                ),
                _part(
                    "p4",
                    author_type="user",
                    body="Thanks!",
                    name="Jane Customer",
                    email="jane@example.com",
                    created_at=CREATED_AT + 180,
                ),
            ],
        )

        result, _ = self._run_batch([conversation])

        assert (result.imported, result.skipped, result.failed) == (1, 0, 0)
        ticket = Ticket.objects.get(team_id=self.team.id, intercom_conversation_id="101")
        assert ticket.status == Status.OPEN
        assert ticket.priority == Priority.HIGH
        assert ticket.distinct_id == "jane@example.com"
        assert ticket.email_subject == "Help with billing"
        assert ticket.anonymous_traits == {"name": "Jane Customer", "email": "jane@example.com"}
        assert ticket.created_at == datetime.fromtimestamp(CREATED_AT, tz=UTC)

        comments = self._comments(ticket)
        # The empty assignment part is dropped; the opening message comes first.
        assert [c.content for c in comments] == [
            "I need help",
            "Looking into it",
            "Internal: refund approved",
            "Vendor: ETA Friday",
            "Thanks!",
        ]
        assert [(c.item_context or {})["author_type"] for c in comments] == [
            "customer",
            "support",
            "support",
            "support",
            "customer",
        ]
        # Notes and side conversations stay internal.
        assert [(c.item_context or {})["is_private"] for c in comments] == [False, False, True, True, False]
        assert comments[0].created_at == datetime.fromtimestamp(CREATED_AT, tz=UTC)

        # The note is excluded from every customer-facing counter and from last_message_text.
        assert ticket.message_count == 3
        assert ticket.last_message_text == "Thanks!"
        assert ticket.unread_team_count == 2
        assert ticket.unread_customer_count == 1
        assert set(Tag.objects.filter(team_id=self.team.id).values_list("name", flat=True)) == {"billing", "vip"}

    def test_closed_conversation_imports_resolved_and_read(self) -> None:
        self._run_batch([_conversation("102", state="closed", parts=[_part("p1")])])

        ticket = Ticket.objects.get(team_id=self.team.id, intercom_conversation_id="102")
        assert ticket.status == Status.RESOLVED
        assert (ticket.unread_team_count, ticket.unread_customer_count) == (0, 0)

    def test_rerun_skips_imported_and_purged_conversations(self) -> None:
        self._run_batch([_conversation("201")])
        PurgedTicketThread.objects.unscoped().create(
            team=self.team, thread_key=ticket_thread_key(intercom_conversation_id="202")
        )

        result, client = self._run_batch([_conversation("201"), _conversation("202"), _conversation("203")])

        assert (result.imported, result.skipped, result.failed) == (1, 2, 0)
        assert [c.args[0] for c in client.fetch_conversation.call_args_list] == ["203"]
        assert set(
            Ticket.all_objects.filter(team_id=self.team.id).values_list("intercom_conversation_id", flat=True)
        ) == {"201", "203"}

    def test_outbound_conversation_resolves_requester_from_contact(self) -> None:
        conversation = _conversation(
            "301",
            source_author={"type": "admin", "id": "9", "name": "Agent Smith", "email": "agent@example.com"},
            source_body="Hi, checking in",
            contacts=[{"type": "contact", "id": "contact-7"}],
        )

        self._run_batch(
            [conversation], contacts={"contact-7": {"id": "contact-7", "name": "Lee", "email": "lee@example.com"}}
        )

        ticket = Ticket.objects.get(team_id=self.team.id, intercom_conversation_id="301")
        assert ticket.distinct_id == "lee@example.com"
        assert (self._comments(ticket)[0].item_context or {})["author_type"] == "support"

    def test_default_email_channel_attached_and_backfilled_on_rerun(self) -> None:
        self._run_batch([_conversation("401")])
        channel = EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.SUPPORT,
            inbound_token="intercom-test-token",
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
        )

        self._run_batch([_conversation("401"), _conversation("402")], default_email_channel_id=str(channel.id))

        assert dict(
            Ticket.objects.filter(team_id=self.team.id).values_list("intercom_conversation_id", "email_config_id")
        ) == {"401": channel.id, "402": channel.id}

    def test_deleted_contact_imports_without_email_but_outage_retries(self) -> None:
        outbound = {"type": "admin", "id": "9", "name": "Agent Smith", "email": "agent@example.com"}
        deleted = _conversation("311", source_author=outbound, contacts=[{"type": "contact", "id": "gone1"}])

        result, _ = self._run_batch([deleted], contacts={"gone1": IntercomNotFoundError("gone")})

        assert (result.imported, result.failed) == (1, 0)
        assert Ticket.objects.get(team_id=self.team.id, intercom_conversation_id="311").email_from is None

        flaky = _conversation("312", source_author=outbound, contacts=[{"type": "contact", "id": "slow1"}])
        with pytest.raises(IntercomRateLimitError):
            self._run_batch([flaky], contacts={"slow1": IntercomRateLimitError("slow down")})
        assert not Ticket.objects.filter(team_id=self.team.id, intercom_conversation_id="312").exists()

    def test_rate_limited_fetch_propagates_so_temporal_retries_the_batch(self) -> None:
        client = MagicMock()
        client.fetch_conversation.side_effect = IntercomRateLimitError("slow down")

        with patch(f"{M}.IntercomImportClient", return_value=client), pytest.raises(IntercomRateLimitError):
            _import_conversation_batch_sync(
                ImportBatchInput(job_id=str(self.job.id), team_id=self.team.id, conversation_ids=["520"])
            )

    def test_failed_fetch_counts_failure_without_dropping_the_batch(self) -> None:
        client = MagicMock()
        good = _conversation("501")

        def fetch(cid: str) -> dict[str, Any]:
            if cid == "500":
                raise RuntimeError("boom")
            return good

        client.fetch_conversation.side_effect = fetch
        with patch(f"{M}.IntercomImportClient", return_value=client):
            result = _import_conversation_batch_sync(
                ImportBatchInput(job_id=str(self.job.id), team_id=self.team.id, conversation_ids=["500", "501"])
            )

        assert (result.imported, result.skipped, result.failed) == (1, 0, 1)

    def test_image_attachment_embedded_in_rich_content(self) -> None:
        conversation = _conversation(
            "601",
            parts=[
                _part(
                    "p1",
                    body="",
                    attachments=[
                        {"name": "shot.png", "url": "https://downloads.example.com/a", "content_type": "image/png"}
                    ],
                )
            ],
        )

        self._run_batch([conversation])

        ticket = Ticket.objects.get(team_id=self.team.id, intercom_conversation_id="601")
        image_comment = self._comments(ticket)[1]
        assert "https://media.posthog.test/file" in str(image_comment.rich_content)

    def test_attachment_names_are_sanitized_and_file_links_stay_clickable(self) -> None:
        conversation = _conversation(
            "602",
            parts=[
                _part(
                    "p1",
                    body="see attached",
                    attachments=[
                        {"name": "shot.png", "url": "https://downloads.example.com/a", "content_type": "image/png"},
                        {
                            "name": "invoice.pdf](https://evil.example)![x",
                            "url": "https://downloads.example.com/b",
                            "content_type": "application/pdf",
                        },
                    ],
                )
            ],
        )

        self._run_batch([conversation])

        comment = self._comments(Ticket.objects.get(team_id=self.team.id, intercom_conversation_id="602"))[1]
        content = comment.content or ""
        # The sanitizer strips the brackets and "!" the injection needs, so no attacker link target forms.
        assert "](https://evil.example)" not in content and "![x" not in content
        file_nodes = [
            node["content"][0]
            for node in (comment.rich_content or {})["content"]
            if node["type"] == "paragraph" and node["content"][0].get("marks")
        ]
        assert [n["marks"][0]["attrs"]["href"] for n in file_nodes] == ["https://media.posthog.test/file"]


class TestIntercomImportJobProgress(BaseTest):
    def test_replayed_progress_update_does_not_double_count(self) -> None:
        job = IntercomImportJob.objects.unscoped().create(team_id=self.team.id, status=IntercomImportJob.Status.RUNNING)
        progress = UpdateJobProgressInput(
            job_id=str(job.id), total=150, processed=50, imported=40, skipped=8, failed=2, export_cursor="c2"
        )

        _update_job_progress_sync(progress)
        _update_job_progress_sync(progress)

        job.refresh_from_db()
        assert (
            job.total_conversations,
            job.processed_conversations,
            job.imported_conversations,
            job.skipped_conversations,
            job.failed_conversations,
            job.export_cursor,
        ) == (150, 50, 40, 8, 2, "c2")
