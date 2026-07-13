from __future__ import annotations

from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models import EmailChannel, Ticket, ZendeskImportJob
from products.conversations.backend.models.constants import Channel, Priority, Status
from products.conversations.backend.temporal.zendesk_import.activities import (
    ImportBatchInput,
    UpdateJobProgressInput,
    UpdateJobStatusInput,
    _import_ticket_batch_sync,
    _parse_zendesk_datetime,
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
    recipient: str | None = None,
) -> dict[str, Any]:
    ticket: dict[str, Any] = {
        "id": tid,
        "requester_id": requester_id,
        "status": status,
        "priority": priority,
        "subject": subject,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    if recipient is not None:
        ticket["recipient"] = recipient
    return ticket


def _zd_user(uid: int, email: str, role: str | None = "end-user", name: str | None = None) -> dict[str, Any]:
    return {"id": uid, "email": email, "role": role, "name": name}


def _zd_comment(
    cid: int,
    author_id: int,
    *,
    public: bool = True,
    body: str = "hello",
    created_at: str = "2020-01-02T03:04:05Z",
    attachments: list[dict[str, Any]] | None = None,
    via_from: dict[str, str] | None = None,
) -> dict[str, Any]:
    comment: dict[str, Any] = {
        "id": cid,
        "author_id": author_id,
        "public": public,
        "body": body,
        "html_body": "",
        "created_at": created_at,
        "attachments": attachments or [],
    }
    if via_from is not None:
        comment["via"] = {"source": {"from": via_from}}
    return comment


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
        download: bytes = b"filebytes",
        download_raises: bool = False,
        save_return: str | None = "https://media.posthog.test/file",
        default_email_channel_id: str | None = None,
        dry_run: bool = False,
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
            patch(f"{M}.save_file_to_uploaded_media", return_value=save_return),
        ):
            result = _import_ticket_batch_sync(
                ImportBatchInput(
                    job_id=str(self.job.id),
                    team_id=self.team.id,
                    ticket_ids=ticket_ids,
                    default_email_channel_id=default_email_channel_id,
                    dry_run=dry_run,
                )
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
        # customer message, public agent reply, internal note. The private note is dropped from
        # every customer-facing denormalized stat (matching the live signal path): message_count
        # counts the 2 public comments, unread_team_count the 1 customer message,
        # unread_customer_count the 1 public agent reply, and last_message_* skips the note.
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
        self.assertEqual(ticket.message_count, 2)
        self.assertEqual(ticket.unread_team_count, 1)
        self.assertEqual(ticket.unread_customer_count, 1)
        self.assertEqual(ticket.status, Status.OPEN)
        self.assertEqual(ticket.priority, Priority.MEDIUM)
        self.assertEqual(ticket.channel_source, Channel.EMAIL)
        self.assertEqual(ticket.email_subject, "Help")
        self.assertEqual(ticket.email_from, "requester@x.com")
        # The newest comment is a private note; the customer-facing summary must show the
        # latest *public* comment instead so internal note text never leaks to the widget.
        self.assertEqual(ticket.last_message_text, "agent reply")
        # auto_now_add / auto_now must not clobber the historical Zendesk timestamps.
        self.assertEqual(ticket.created_at, _parse_zendesk_datetime("2020-01-02T03:04:05Z"))
        self.assertEqual(ticket.updated_at, _parse_zendesk_datetime("2020-01-03T04:05:06Z"))
        self.assertEqual(ticket.last_message_at, _parse_zendesk_datetime("2020-01-02T03:04:05Z"))

        stored = Comment.objects.filter(team=self.team, scope="conversations_ticket", item_id=str(ticket.id))
        self.assertEqual(stored.count(), 3)
        self.assertEqual(stored.order_by("created_at").first().created_at.year, 2020)

    @parameterized.expand(
        [
            ("solved", "solved"),
            ("closed", "closed"),
            ("pending", "pending"),
            ("hold", "hold"),
        ]
    )
    def test_inactive_imported_tickets_have_no_unread_counts(self, _name: str, zendesk_status: str) -> None:
        # Alert-fatigue guard: a done/parked ticket (resolved/pending/on-hold) must import read —
        # no unread badge on the agent inbox or customer widget for years-old activity. Message
        # metadata still populates; only the unread counters are suppressed for non-active statuses.
        comments = [
            _zd_comment(1, 10, public=True, body="customer msg"),
            _zd_comment(2, 20, public=True, body="agent reply"),
        ]
        self._run_batch(
            [211],
            tickets=[_zd_ticket(211, 10, status=zendesk_status)],
            users={10: _zd_user(10, "requester@x.com"), 20: _zd_user(20, "agent@x.com", role="agent")},
            comments_by_ticket={211: comments},
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=211)
        self.assertEqual(ticket.message_count, 2)
        self.assertEqual(ticket.unread_team_count, 0)
        self.assertEqual(ticket.unread_customer_count, 0)

    def test_unmatched_requester_sets_anonymous_traits_for_display(self) -> None:
        # The customer must render as their Zendesk name/email (via anonymous_traits) instead of
        # "Anonymous user".
        self._run_batch(
            [205],
            tickets=[_zd_ticket(205, 10)],
            users={10: _zd_user(10, "requester@x.com", name="Ada Lovelace")},
            comments_by_ticket={205: []},
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=205)
        self.assertEqual(ticket.anonymous_traits, {"name": "Ada Lovelace", "email": "requester@x.com"})

    def _make_channel(self, from_email: str, token: str) -> EmailChannel:
        return EmailChannel.objects.create(
            team=self.team,
            inbound_token=token,
            from_email=from_email,
            from_name="Support",
            domain="acme.com",
        )

    @parameterized.expand(
        [
            # recipient matches a configured channel (case-insensitively) → that channel wins,
            # even when a different default is set.
            ("matched_wins_over_default", "Support@ACME.com", True, "matched"),
            # recipient is a *.zendesk.com / non-configured address → fall back to the default.
            ("unmatched_uses_default", "acme.support@acme.zendesk.com", True, "default"),
            # recipient absent → fall back to the default.
            ("null_uses_default", None, True, "default"),
            # no default configured and no match → leave email_config null (don't fabricate one).
            ("unmatched_no_default_stays_null", "acme.support@acme.zendesk.com", False, None),
        ]
    )
    def test_recipient_maps_to_email_channel(
        self, _name: str, recipient: str | None, use_default: bool, expected: str | None
    ) -> None:
        matched = self._make_channel("support@acme.com", "tok-matched")
        default = self._make_channel("fallback@acme.com", "tok-default")

        self._run_batch(
            [210],
            tickets=[_zd_ticket(210, 10, recipient=recipient)],
            users={10: _zd_user(10, "requester@x.com", name="Ada")},
            comments_by_ticket={210: []},
            default_email_channel_id=str(default.id) if use_default else None,
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=210)
        expected_id = {"matched": matched.id, "default": default.id, None: None}[expected]
        self.assertEqual(ticket.email_config_id, expected_id)

    @parameterized.expand(
        [
            # null channel (first import ran without a default) → adopt this run's default.
            ("null_channel_adopts_default", False, True, False, "default"),
            # a channel resolved by an earlier run must never be overwritten by a new default.
            ("existing_channel_kept", True, True, False, "existing"),
            # no default on this run either → stays null.
            ("no_default_stays_null", False, False, False, None),
            # dry run must not mutate previously imported tickets.
            ("dry_run_does_not_backfill", False, True, True, None),
        ]
    )
    def test_reimport_backfills_default_email_channel(
        self, _name: str, has_channel: bool, use_default: bool, dry_run: bool, expected: str | None
    ) -> None:
        existing_channel = self._make_channel("original@acme.com", "tok-original")
        default = self._make_channel("fallback@acme.com", "tok-default")
        ticket = Ticket.objects.create(
            team=self.team,
            ticket_number=1,
            widget_session_id="existing",
            distinct_id="d",
            zendesk_ticket_id=301,
            email_config=existing_channel if has_channel else None,
        )

        result, client = self._run_batch(
            [301],
            tickets=[],
            users={},
            comments_by_ticket={},
            default_email_channel_id=str(default.id) if use_default else None,
            dry_run=dry_run,
        )

        # The ticket is still skipped (never re-imported) and never re-fetched from Zendesk.
        self.assertEqual((result.imported, result.skipped, result.failed), (0, 1, 0))
        client.fetch_tickets.assert_not_called()
        ticket.refresh_from_db()
        expected_id = {"default": default.id, "existing": existing_channel.id, None: None}[expected]
        self.assertEqual(ticket.email_config_id, expected_id)

    def test_reimport_backfills_existing_and_imports_new_in_same_batch(self) -> None:
        # Guards the channel resolution feeding both paths: the previously imported null-channel
        # ticket is backfilled while the new ticket in the same batch imports with the default.
        default = self._make_channel("fallback@acme.com", "tok-default")
        existing = Ticket.objects.create(
            team=self.team,
            ticket_number=1,
            widget_session_id="existing",
            distinct_id="d",
            zendesk_ticket_id=401,
        )

        result, _ = self._run_batch(
            [401, 402],
            tickets=[_zd_ticket(402, 10)],
            users={10: _zd_user(10, "requester@x.com")},
            comments_by_ticket={402: []},
            default_email_channel_id=str(default.id),
        )

        self.assertEqual((result.imported, result.skipped, result.failed), (1, 1, 0))
        existing.refresh_from_db()
        self.assertEqual(existing.email_config_id, default.id)
        new_ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=402)
        self.assertEqual(new_ticket.email_config_id, default.id)

    def test_staff_reply_with_unresolved_role_is_not_attributed_to_customer(self) -> None:
        # Reported bug: a public agent reply whose author role can't be resolved (role=None) was
        # typed "customer" and rendered as the ticket's customer identity. It must map to support.
        comments = [
            _zd_comment(1, 10, public=True, body="customer question"),
            _zd_comment(2, 99, public=True, body="staff answer"),
        ]
        self._run_batch(
            [206],
            tickets=[_zd_ticket(206, 10)],
            users={
                10: _zd_user(10, "person@example.com", name="Person"),
                99: _zd_user(99, "staff@posthog.com", role=None),  # role unresolved
            },
            comments_by_ticket={206: comments},
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=206)
        by_body = {c.content: c for c in Comment.objects.filter(team=self.team, item_id=str(ticket.id))}
        self.assertEqual(by_body["customer question"].item_context["author_type"], "customer")
        self.assertEqual(by_body["staff answer"].item_context["author_type"], "support")
        # One customer message, one team message.
        self.assertEqual(ticket.unread_team_count, 1)
        self.assertEqual(ticket.unread_customer_count, 1)

    def test_second_end_user_reply_is_customer_not_staff(self) -> None:
        # person@example.com (requester) + person2@example.com (another end-user, not a CC) + staff.
        # person2 must classify as customer by role, not fall to the staff fallback.
        comments = [
            _zd_comment(1, 10, public=True, body="from requester"),
            _zd_comment(2, 11, public=True, body="from second end user"),
            _zd_comment(3, 20, public=True, body="from staff"),
        ]
        self._run_batch(
            [207],
            tickets=[_zd_ticket(207, 10)],
            users={
                10: _zd_user(10, "person@example.com", name="Person"),
                11: _zd_user(11, "person2@example.com", role="end-user"),
                20: _zd_user(20, "staff@posthog.com", role="agent"),
            },
            comments_by_ticket={207: comments},
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=207)
        by_body = {c.content: c for c in Comment.objects.filter(team=self.team, item_id=str(ticket.id))}
        self.assertEqual(by_body["from requester"].item_context["author_type"], "customer")
        self.assertEqual(by_body["from second end user"].item_context["author_type"], "customer")
        self.assertEqual(by_body["from staff"].item_context["author_type"], "support")
        # Each comment carries its own author identity so the thread doesn't show the ticket
        # requester on every message.
        self.assertEqual(by_body["from second end user"].item_context["author_email"], "person2@example.com")
        self.assertEqual(by_body["from staff"].item_context["author_email"], "staff@posthog.com")

    def test_deleted_staff_author_recovered_from_comment_via_sender(self) -> None:
        # Staff author id 88 doesn't resolve (deleted ex-agent, absent from `users`), so name/email
        # must come from the comment's own via.source.from sender rather than being dropped.
        comments = [
            _zd_comment(1, 10, public=True, body="customer"),
            _zd_comment(
                2,
                88,
                public=True,
                body="staff reply",
                via_from={"name": "Marcus", "address": "marcus@posthog.com"},
            ),
        ]
        self._run_batch(
            [208],
            tickets=[_zd_ticket(208, 10)],
            users={10: _zd_user(10, "person@example.com", name="Person")},  # 88 intentionally missing
            comments_by_ticket={208: comments},
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=208)
        staff = Comment.objects.get(team=self.team, item_id=str(ticket.id), content="staff reply")
        assert staff.item_context is not None
        self.assertEqual(staff.item_context["author_type"], "support")
        self.assertEqual(staff.item_context["author_name"], "Marcus")
        self.assertEqual(staff.item_context["author_email"], "marcus@posthog.com")

    def test_nul_bytes_are_stripped_from_persisted_fields(self) -> None:
        # A single NUL byte anywhere in the batch aborts the whole bulk_create with a Postgres
        # DataError (which then exhausts the activity's retries), so every Zendesk-sourced string
        # must be scrubbed. Cover the subject, requester name/email, comment body, and per-comment
        # author identity in one go.
        result, _ = self._run_batch(
            [209],
            tickets=[_zd_ticket(209, 10, subject="sub\x00ject")],
            users={10: _zd_user(10, "person\x00@example.com", name="Per\x00son")},
            comments_by_ticket={209: [_zd_comment(1, 10, public=True, body="hell\x00o")]},
        )

        self.assertEqual(result.imported, 1)
        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=209)
        self.assertEqual(ticket.email_subject, "subject")
        self.assertEqual(ticket.anonymous_traits, {"name": "Person", "email": "person@example.com"})
        comment = Comment.objects.get(team=self.team, item_id=str(ticket.id))
        self.assertEqual(comment.content, "hello")
        assert comment.item_context is not None
        self.assertEqual(comment.item_context["author_email"], "person@example.com")

    def test_distinct_id_is_the_zendesk_requester_email(self) -> None:
        # Access-control invariant: the imported ticket's distinct_id must be the Zendesk requester
        # email verbatim, never a distinct_id resolved from a PostHog person's `properties.email`.
        # That analytics field is attacker-settable, so resolving through it would let an attacker
        # seed a profile with a victim's email and inherit the victim's imported ticket history
        # (identity poisoning). The email comes from the authenticated Zendesk API, so it's trusted.
        self._run_batch(
            [202],
            tickets=[_zd_ticket(202, 10)],
            users={10: _zd_user(10, "requester@x.com")},
            comments_by_ticket={202: []},
        )

        ticket = Ticket.objects.get(team=self.team, zendesk_ticket_id=202)
        self.assertEqual(ticket.distinct_id, "requester@x.com")

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
        rich_content = stored.rich_content
        assert rich_content is not None
        image_nodes = [n for n in rich_content["content"] if n.get("type") == "image"]
        self.assertEqual(image_nodes[0]["attrs"]["src"], "https://media.posthog.test/shot.png")
        content = stored.content
        assert content is not None
        self.assertIn("https://media.posthog.test/shot.png", content)

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
        content = stored.content
        assert content is not None
        self.assertIn("[doc.pdf](https://media.posthog.test/doc.pdf)", content)
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
