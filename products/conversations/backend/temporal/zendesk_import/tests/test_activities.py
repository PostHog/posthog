from __future__ import annotations

from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket, ZendeskImportJob
from products.conversations.backend.models.constants import Channel, Priority, Status
from products.conversations.backend.temporal.zendesk_import.activities import (
    ImportBatchInput,
    UpdateJobProgressInput,
    UpdateJobStatusInput,
    _import_ticket_batch_sync,
    _update_job_progress_sync,
    _update_job_status_sync,
)

M = "products.conversations.backend.temporal.zendesk_import.activities"


def _zd_ticket(
    tid: int,
    requester_id: int,
    *,
    status: str = "open",
    priority: str = "normal",
    subject: str = "Help",
    created_at: str = "2020-01-02T03:04:05Z",
    updated_at: str = "2020-01-03T04:05:06Z",
) -> dict[str, Any]:
    return {
        "id": tid,
        "requester_id": requester_id,
        "status": status,
        "priority": priority,
        "subject": subject,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _zd_user(uid: int, email: str, role: str = "end-user") -> dict[str, Any]:
    return {"id": uid, "email": email, "role": role}


def _zd_comment(
    cid: int,
    author_id: int,
    *,
    public: bool = True,
    body: str = "hello",
    created_at: str = "2020-01-02T03:04:05Z",
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": cid,
        "author_id": author_id,
        "public": public,
        "body": body,
        "html_body": "",
        "created_at": created_at,
        "attachments": attachments or [],
    }


class TestZendeskImportBatchActivity(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.job = ZendeskImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=ZendeskImportJob.Status.RUNNING,
            job_inputs={"subdomain": "acme", "email_address": "agent@acme.com", "api_token": "tok"},
        )

    def _run_batch(
        self,
        ticket_ids: list[int],
        *,
        tickets: list[dict[str, Any]],
        users: dict[int, dict[str, Any]],
        comments_by_ticket: dict[int, list[dict[str, Any]]],
        persons: dict[str, Any] | None = None,
        download: bytes = b"filebytes",
        download_raises: bool = False,
        save_return: str | None = "https://media.posthog.test/file",
    ) -> tuple[Any, MagicMock]:
        client = MagicMock()
        client.fetch_tickets.return_value = tickets
        client.fetch_users.side_effect = lambda ids: {uid: users[uid] for uid in ids if uid in users}
        client.fetch_comments.side_effect = lambda tid: comments_by_ticket.get(tid, [])
        if download_raises:
            client.download_attachment.side_effect = RuntimeError("boom")
        else:
            client.download_attachment.return_value = download

        with (
            patch(f"{M}.ZendeskImportClient", return_value=client),
            patch(f"{M}._get_persons_by_email", return_value=persons or {}),
            patch(f"{M}.save_file_to_uploaded_media", return_value=save_return),
        ):
            result = _import_ticket_batch_sync(
                ImportBatchInput(job_id=str(self.job.id), team_id=self.team.id, ticket_ids=ticket_ids)
            )
        return result, client

    def test_idempotency_skips_already_imported_tickets(self) -> None:
        # A ticket already synced (same zendesk_ticket_id) must not be re-fetched or re-inserted;
        # this guards the pre-filter that makes "run it again later" safe.
        Ticket.objects.create(
            team=self.team,
            ticket_number=1,
            widget_session_id="existing",
            distinct_id="d",
            zendesk_ticket_id=111,
        )

        result, client = self._run_batch(
            [111],
            tickets=[],
            users={},
            comments_by_ticket={},
        )

        self.assertEqual((result.imported, result.skipped, result.failed), (0, 1, 0))
        self.assertEqual(Ticket.objects.filter(team=self.team, zendesk_ticket_id=111).count(), 1)
        client.fetch_tickets.assert_not_called()

    def test_import_sets_counters_fields_and_historical_timestamps(self) -> None:
        # customer message, public agent reply, internal note → message_count 3,
        # unread_team_count counts the 1 customer message, unread_customer_count the 2 team messages.
        comments = [
            _zd_comment(1, 10, public=True, body="customer msg"),
            _zd_comment(2, 20, public=True, body="agent reply"),
            _zd_comment(3, 20, public=False, body="internal note"),
        ]
        result, _ = self._run_batch(
            [201],
            tickets=[_zd_ticket(201, 10)],
            users={10: _zd_user(10, "requester@x.com"), 20: _zd_user(20, "agent@x.com", role="agent")},
            comments_by_ticket={201: comments},
        )

        self.assertEqual((result.imported, result.skipped, result.failed), (1, 0, 0))
        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=201)
        self.assertEqual(ticket.message_count, 3)
        self.assertEqual(ticket.unread_team_count, 1)
        self.assertEqual(ticket.unread_customer_count, 2)
        self.assertEqual(ticket.status, Status.OPEN)
        self.assertEqual(ticket.priority, Priority.MEDIUM)
        self.assertEqual(ticket.channel_source, Channel.EMAIL)
        self.assertEqual(ticket.email_subject, "Help")
        self.assertEqual(ticket.email_from, "requester@x.com")
        self.assertEqual(ticket.last_message_text, "internal note")
        # auto_now_add must not clobber the Zendesk creation date.
        self.assertEqual(ticket.created_at.year, 2020)

        stored = Comment.objects.filter(team=self.team, scope="conversations_ticket", item_id=str(ticket.id))
        self.assertEqual(stored.count(), 3)
        self.assertEqual(stored.order_by("created_at").first().created_at.year, 2020)

    @parameterized.expand(
        [
            ("matched_person", ["person-distinct-1"], "person-distinct-1"),
            ("no_match_falls_back_to_email", None, "requester@x.com"),
        ]
    )
    def test_person_match_sets_distinct_id(self, _name: str, distinct_ids: list[str] | None, expected: str) -> None:
        persons: dict[str, Any] = {}
        if distinct_ids is not None:
            person = MagicMock()
            person.distinct_ids = distinct_ids
            persons = {"requester@x.com": person}

        self._run_batch(
            [202],
            tickets=[_zd_ticket(202, 10)],
            users={10: _zd_user(10, "requester@x.com")},
            comments_by_ticket={202: []},
            persons=persons,
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=202)
        self.assertEqual(ticket.distinct_id, expected)

    def test_ticket_numbers_are_unique_and_gap_free_within_batch(self) -> None:
        # Pre-existing ticket sets MAX(ticket_number)=5; the batch must assign 6,7,8 under one lock
        # without colliding on unique_ticket_number_per_team.
        Ticket.objects.create(team=self.team, ticket_number=5, widget_session_id="s", distinct_id="d")

        self._run_batch(
            [301, 302, 303],
            tickets=[_zd_ticket(301, 10), _zd_ticket(302, 10), _zd_ticket(303, 10)],
            users={10: _zd_user(10, "requester@x.com")},
            comments_by_ticket={},
        )

        numbers = sorted(
            Ticket.objects.filter(team=self.team, zendesk_ticket_id__in=[301, 302, 303]).values_list(
                "ticket_number", flat=True
            )
        )
        self.assertEqual(numbers, [6, 7, 8])

    def test_image_attachment_embedded_in_rich_content(self) -> None:
        comment = _zd_comment(
            1,
            10,
            body="see image",
            attachments=[{"content_url": "http://zd/a", "file_name": "shot.png", "content_type": "image/png"}],
        )
        self._run_batch(
            [401],
            tickets=[_zd_ticket(401, 10)],
            users={10: _zd_user(10, "requester@x.com")},
            comments_by_ticket={401: [comment]},
            save_return="https://media.posthog.test/shot.png",
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=401)
        stored = Comment.objects.get(team=self.team, scope="conversations_ticket", item_id=str(ticket.id))
        self.assertIsNotNone(stored.rich_content)
        image_nodes = [n for n in stored.rich_content["content"] if n.get("type") == "image"]
        self.assertEqual(image_nodes[0]["attrs"]["src"], "https://media.posthog.test/shot.png")
        self.assertIn("https://media.posthog.test/shot.png", stored.content)

    def test_non_image_attachment_linked(self) -> None:
        comment = _zd_comment(
            1,
            10,
            body="report",
            attachments=[{"content_url": "http://zd/b", "file_name": "doc.pdf", "content_type": "application/pdf"}],
        )
        self._run_batch(
            [402],
            tickets=[_zd_ticket(402, 10)],
            users={10: _zd_user(10, "requester@x.com")},
            comments_by_ticket={402: [comment]},
            save_return="https://media.posthog.test/doc.pdf",
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=402)
        stored = Comment.objects.get(team=self.team, scope="conversations_ticket", item_id=str(ticket.id))
        self.assertIn("[doc.pdf](https://media.posthog.test/doc.pdf)", stored.content)
        self.assertIsNone(stored.rich_content)

    def test_failed_attachment_download_does_not_fail_the_ticket(self) -> None:
        comment = _zd_comment(
            1,
            10,
            body="body survives",
            attachments=[{"content_url": "http://zd/c", "file_name": "x.png", "content_type": "image/png"}],
        )
        result, _ = self._run_batch(
            [403],
            tickets=[_zd_ticket(403, 10)],
            users={10: _zd_user(10, "requester@x.com")},
            comments_by_ticket={403: [comment]},
            download_raises=True,
        )

        self.assertEqual((result.imported, result.failed), (1, 0))
        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=403)
        stored = Comment.objects.get(team=self.team, scope="conversations_ticket", item_id=str(ticket.id))
        self.assertEqual(stored.content, "body survives")


class TestZendeskImportJobUpdates(BaseTest):
    def _make_job(self, **kwargs: Any) -> ZendeskImportJob:
        return ZendeskImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=ZendeskImportJob.Status.PENDING,
            job_inputs={"subdomain": "acme", "email_address": "a@b.com", "api_token": "t"},
            **kwargs,
        )

    @parameterized.expand(
        [
            (ZendeskImportJob.Status.RUNNING, True, False, None),
            (ZendeskImportJob.Status.COMPLETED, False, True, None),
            (ZendeskImportJob.Status.FAILED, False, True, "kaboom"),
        ]
    )
    def test_status_update_persists_timestamps_and_error(
        self, status: str, started_set: bool, finished_set: bool, latest_error: str | None
    ) -> None:
        # Guards the narrowed update_fields: started_at / finished_at / latest_error must actually
        # be written, not silently dropped by an incomplete update_fields list.
        job = self._make_job()

        _update_job_status_sync(UpdateJobStatusInput(job_id=str(job.id), status=status, latest_error=latest_error))

        job.refresh_from_db()
        self.assertEqual(job.status, status)
        self.assertEqual(job.started_at is not None, started_set)
        self.assertEqual(job.finished_at is not None, finished_set)
        self.assertEqual(job.latest_error, latest_error)

    def test_progress_update_accumulates_counters_and_cursor(self) -> None:
        # F()-based increments must accumulate across batches (not overwrite) and persist the cursor.
        job = self._make_job()

        _update_job_progress_sync(
            UpdateJobProgressInput(job_id=str(job.id), total_delta=100, processed_delta=10, imported_delta=8)
        )
        _update_job_progress_sync(
            UpdateJobProgressInput(job_id=str(job.id), processed_delta=5, skipped_delta=2, export_cursor="c2")
        )

        job.refresh_from_db()
        self.assertEqual(job.total_tickets, 100)
        self.assertEqual(job.processed_tickets, 15)
        self.assertEqual(job.imported_tickets, 8)
        self.assertEqual(job.skipped_tickets, 2)
        self.assertEqual(job.export_cursor, "c2")
