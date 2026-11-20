from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Tag
from posthog.models.comment import Comment

from products.conversations.backend.models import (
    EmailChannel,
    EmailChannelKind,
    PurgedTicketThread,
    PylonImportJob,
    Ticket,
)
from products.conversations.backend.models.constants import Priority, Status
from products.conversations.backend.models.purged_ticket_thread import ticket_thread_key
from products.conversations.backend.services.attachments import AttachmentStorageError
from products.conversations.backend.temporal.pylon_import.activities import (
    ImportBatchInput,
    ImportBatchOutput,
    UpdateJobProgressInput,
    _import_issue_batch_sync,
    _update_job_progress_sync,
)
from products.conversations.backend.temporal.pylon_import.client import PylonNotFoundError, PylonRateLimitError
from products.conversations.backend.temporal.ticket_import.attachment_download import (
    AttachmentTooLargeError,
    DownloadedAttachment,
)

M = "products.conversations.backend.temporal.pylon_import.activities"

CREATED_AT = "2020-01-02T03:04:05Z"
UPDATED_AT = "2020-01-03T04:05:06Z"
CUSTOMER = {"name": "Jane Customer", "contact": {"id": "contact-1", "email": "jane@example.com"}}
AGENT = {"name": "Agent Smith", "user": {"id": "user-1", "email": "agent@example.com"}}


def _message(
    mid: str,
    *,
    author: dict[str, Any] | None = None,
    html: str = "<p>reply</p>",
    is_private: bool = False,
    timestamp: str = "2020-01-02T03:05:05Z",
    file_urls: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": mid,
        "author": AGENT if author is None else author,
        "message_html": html,
        "is_private": is_private,
        "timestamp": timestamp,
        "file_urls": file_urls or [],
    }


def _issue(
    issue_id: str,
    *,
    state: str = "waiting_on_you",
    priority: str | None = None,
    title: str = "Refund escalation for VIP account",
    customer_portal_title: str | None = "Help with billing",
    tags: list[str] | None = None,
    requester: dict[str, Any] | None = None,
    workspace_email: str | None = None,
    body_html: str = "<p>I need help</p>",
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "number": 7,
        "title": title,
        "customer_portal_title": customer_portal_title,
        "state": state,
        "body_html": body_html,
        "created_at": CREATED_AT,
        "updated_at": UPDATED_AT,
        "requester": {"id": "contact-1", "email": "jane@example.com"} if requester is None else requester,
        "tags": tags or [],
        "custom_fields": {"priority": {"slug": "priority", "value": priority}} if priority else {},
        "workspace_email": workspace_email,
        "attachment_urls": [],
    }


def _opening(html: str = "<p>I need help</p>") -> dict[str, Any]:
    return _message("m0", author=CUSTOMER, html=html, timestamp=CREATED_AT)


class TestPylonImportBatchActivity(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.job = PylonImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=PylonImportJob.Status.RUNNING,
            job_inputs={"region": "us", "api_token": "fake-token"},
        )

    def _client(
        self,
        issues: list[dict[str, Any]],
        messages: dict[str, list[dict[str, Any]]] | None = None,
        contacts: dict[str, Any] | None = None,
    ) -> MagicMock:
        by_id = {issue["id"]: issue for issue in issues}
        client = MagicMock()
        client.fetch_issue.side_effect = lambda issue_id: by_id[issue_id]
        client.fetch_messages.side_effect = lambda issue_id: (messages or {}).get(issue_id, [_opening()])

        def fetch_contact(contact_id: str) -> dict[str, Any]:
            contact = (contacts or {}).get(contact_id, {"id": contact_id})
            if isinstance(contact, Exception):
                raise contact
            return contact

        client.fetch_contact.side_effect = fetch_contact
        client.issue_status_categories.return_value = {"escalated": "on_hold"}
        client.download_attachment.return_value = DownloadedAttachment(content=b"filebytes", content_type="")
        return client

    def _run_batch(
        self,
        issues: list[dict[str, Any]],
        *,
        messages: dict[str, list[dict[str, Any]]] | None = None,
        contacts: dict[str, Any] | None = None,
        default_email_channel_id: str | None = None,
    ) -> tuple[ImportBatchOutput, MagicMock]:
        client = self._client(issues, messages, contacts)
        with (
            patch(f"{M}.PylonImportClient", return_value=client),
            patch(f"{M}.save_file_to_uploaded_media", return_value="https://media.posthog.test/file") as save,
        ):
            result = _import_issue_batch_sync(
                ImportBatchInput(
                    job_id=str(self.job.id),
                    team_id=self.team.id,
                    issue_ids=[issue["id"] for issue in issues],
                    default_email_channel_id=default_email_channel_id,
                )
            )
        client.save = save
        return result, client

    def _comments(self, ticket: Ticket) -> list[Comment]:
        return list(
            Comment.objects.filter(team_id=self.team.id, scope="conversations_ticket", item_id=str(ticket.id)).order_by(
                "created_at"
            )
        )

    def _email_channel(self, address: str) -> EmailChannel:
        return EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.SUPPORT,
            inbound_token=f"pylon-test-{address}",
            from_email=address,
            from_name="Support",
            domain=address.split("@")[1],
        )

    def test_import_maps_issue_thread_and_counters(self) -> None:
        issue = _issue("i-101", priority="urgent", tags=["Billing", "VIP"])
        messages = [
            _opening("<p>I need help</p><p>See <a href='https://example.com/invoice'>my invoice</a></p>"),
            _message("m1", html="<div>Looking into it</div>", timestamp="2020-01-02T03:05:05Z"),
            _message("m2", html="<p>Internal: refund approved</p>", is_private=True, timestamp="2020-01-02T03:06:05Z"),
            _message("m3", html="  ", timestamp="2020-01-02T03:07:05Z"),
            _message("m4", author={"name": "Autoresponder"}, html="<p>We got it</p>", timestamp="2020-01-02T03:08:05Z"),
            _message("m5", author=CUSTOMER, html="<p>Thanks!</p>", timestamp="2020-01-02T03:09:05Z"),
        ]

        result, client = self._run_batch([issue], messages={"i-101": messages})

        assert (result.imported, result.skipped, result.failed) == (1, 0, 0)
        ticket = Ticket.objects.get(team_id=self.team.id, pylon_issue_id="i-101")
        assert ticket.status == Status.OPEN
        assert ticket.priority == Priority.HIGH
        # The unverified email is kept for display and replies but never becomes the access identity.
        assert ticket.distinct_id == "pylon:contact-1"
        assert (ticket.email_from, ticket.identity_verified) == ("jane@example.com", False)
        assert ticket.email_subject == "Help with billing"
        assert ticket.anonymous_traits == {"name": "Jane Customer", "email": "jane@example.com"}
        assert ticket.created_at == datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
        # The requester's own message names them, so no contact lookup is spent.
        client.fetch_contact.assert_not_called()
        client.issue_status_categories.assert_not_called()

        comments = self._comments(ticket)
        # The whitespace-only message is dropped. HTML keeps its paragraph breaks and link targets.
        assert [c.content for c in comments] == [
            "I need help\n\nSee [my invoice](https://example.com/invoice)",
            "Looking into it",
            "Internal: refund approved",
            "We got it",
            "Thanks!",
        ]
        assert [(c.item_context or {})["author_type"] for c in comments] == [
            "customer",
            "support",
            "support",
            "support",
            "customer",
        ]
        assert [(c.item_context or {})["is_private"] for c in comments] == [False, False, True, False, False]
        assert (comments[1].item_context or {})["author_email"] == "agent@example.com"
        assert comments[0].created_at == datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)

        # The note is excluded from every customer-facing counter and from last_message_text.
        assert ticket.message_count == 4
        assert ticket.last_message_text == "Thanks!"
        assert ticket.unread_team_count == 2
        assert ticket.unread_customer_count == 2
        assert set(Tag.objects.filter(team_id=self.team.id).values_list("name", flat=True)) == {"billing", "vip"}

    def test_custom_status_resolves_through_its_category_and_closed_imports_read(self) -> None:
        _, client = self._run_batch([_issue("i-110", state="escalated"), _issue("i-111", state="closed")])

        tickets = {t.pylon_issue_id: t for t in Ticket.objects.filter(team_id=self.team.id)}
        assert tickets["i-110"].status == Status.ON_HOLD
        assert tickets["i-111"].status == Status.RESOLVED
        assert (tickets["i-111"].unread_team_count, tickets["i-111"].unread_customer_count) == (0, 0)
        client.issue_status_categories.assert_called_once()

    def test_internal_title_never_becomes_the_reply_subject(self) -> None:
        self._run_batch([_issue("i-130", customer_portal_title=None)])

        assert Ticket.objects.get(team_id=self.team.id, pylon_issue_id="i-130").email_subject is None

    def test_issue_body_is_kept_when_the_messages_list_is_empty(self) -> None:
        self._run_batch([_issue("i-120", body_html="<p>Opening text</p>")], messages={"i-120": []})

        comments = self._comments(Ticket.objects.get(team_id=self.team.id, pylon_issue_id="i-120"))
        assert [(c.content, (c.item_context or {})["author_type"]) for c in comments] == [("Opening text", "customer")]

    def test_rerun_skips_imported_and_purged_issues(self) -> None:
        self._run_batch([_issue("i-201")])
        PurgedTicketThread.objects.unscoped().create(
            team=self.team, thread_key=ticket_thread_key(pylon_issue_id="i-202")
        )

        result, client = self._run_batch([_issue("i-201"), _issue("i-202"), _issue("i-203")])

        assert (result.imported, result.skipped, result.failed) == (1, 2, 0)
        assert [c.args[0] for c in client.fetch_issue.call_args_list] == ["i-203"]
        assert set(Ticket.all_objects.filter(team_id=self.team.id).values_list("pylon_issue_id", flat=True)) == {
            "i-201",
            "i-203",
        }

    def test_requester_who_never_wrote_is_resolved_from_the_contact(self) -> None:
        issue = _issue("i-301", requester={"id": "contact-7"})
        messages = {"i-301": [_message("m1", html="<p>Hi, checking in</p>")]}

        self._run_batch(
            [issue],
            messages=messages,
            contacts={"contact-7": {"id": "contact-7", "name": "Lee", "email": "lee@example.com"}},
        )

        ticket = Ticket.objects.get(team_id=self.team.id, pylon_issue_id="i-301")
        assert (ticket.distinct_id, ticket.email_from) == ("pylon:contact-7", "lee@example.com")
        assert ticket.anonymous_traits == {"name": "Lee", "email": "lee@example.com"}

    def test_deleted_contact_imports_without_email_but_outage_retries(self) -> None:
        messages = [_message("m1")]
        deleted = _issue("i-311", requester={"id": "gone1"})

        result, _ = self._run_batch(
            [deleted], messages={"i-311": messages}, contacts={"gone1": PylonNotFoundError("gone")}
        )

        assert (result.imported, result.failed) == (1, 0)
        assert Ticket.objects.get(team_id=self.team.id, pylon_issue_id="i-311").email_from is None

        flaky = _issue("i-312", requester={"id": "slow1"})
        with pytest.raises(PylonRateLimitError):
            self._run_batch([flaky], messages={"i-312": messages}, contacts={"slow1": PylonRateLimitError("slow down")})
        assert not Ticket.objects.filter(team_id=self.team.id, pylon_issue_id="i-312").exists()

    def test_ticket_joins_the_channel_of_its_support_address_or_the_default(self) -> None:
        self._run_batch([_issue("i-401")])
        default = self._email_channel("support@example.com")
        billing = self._email_channel("billing@example.com")

        self._run_batch(
            [_issue("i-401"), _issue("i-402"), _issue("i-403", workspace_email="Billing@Example.com")],
            default_email_channel_id=str(default.id),
        )

        # i-401 was imported earlier without a channel, so the rerun backfills the default.
        assert dict(Ticket.objects.filter(team_id=self.team.id).values_list("pylon_issue_id", "email_config_id")) == {
            "i-401": default.id,
            "i-402": default.id,
            "i-403": billing.id,
        }

    @parameterized.expand(
        [
            ("rate_limit", PylonRateLimitError("slow down")),
            ("database_connection", OperationalError("server closed the connection unexpectedly")),
        ]
    )
    def test_transient_failure_propagates_so_temporal_retries_the_batch(self, _name: str, error: Exception) -> None:
        client = self._client([_issue("i-520")])
        client.fetch_messages.side_effect = error

        with patch(f"{M}.PylonImportClient", return_value=client), pytest.raises(type(error)):
            _import_issue_batch_sync(
                ImportBatchInput(job_id=str(self.job.id), team_id=self.team.id, issue_ids=["i-520"])
            )

    def test_failed_fetch_counts_failure_without_dropping_the_batch(self) -> None:
        client = self._client([_issue("i-501")])
        good = client.fetch_issue.side_effect

        def fetch(issue_id: str) -> dict[str, Any]:
            if issue_id == "i-500":
                raise RuntimeError("boom")
            return good(issue_id)

        client.fetch_issue.side_effect = fetch
        with patch(f"{M}.PylonImportClient", return_value=client):
            result = _import_issue_batch_sync(
                ImportBatchInput(job_id=str(self.job.id), team_id=self.team.id, issue_ids=["i-500", "i-501"])
            )

        assert (result.imported, result.skipped, result.failed) == (1, 0, 1)

    def test_file_names_and_types_come_from_the_url_and_names_are_sanitized(self) -> None:
        file_urls = [
            "https://files.example.com/f/shot.png?signature=abc",
            "https://files.example.com/f/invoice.pdf%5D%28https%3A%2F%2Fevil.example%29%21%5Bx?signature=abc",
        ]
        messages = {"i-601": [_opening(), _message("m1", html="<p>see attached</p>", file_urls=file_urls)]}

        _, client = self._run_batch([_issue("i-601")], messages=messages)

        # Storage served no content type, so the extension decides which file is an inline image.
        saved = [(c.args[1], c.args[2], c.kwargs["validate_images"]) for c in client.save.call_args_list]
        assert saved[0] == ("shot.png", "image/png", True)
        assert saved[1][1:] == ("application/octet-stream", False)
        comment = self._comments(Ticket.objects.get(team_id=self.team.id, pylon_issue_id="i-601"))[1]
        content = comment.content or ""
        # The sanitizer strips the brackets and "!" the injection needs, so no attacker link target forms.
        assert "](https://evil.example)" not in content and "![x" not in content
        assert "https://media.posthog.test/file" in str(comment.rich_content)

    def _attachment_issue(self, issue_id: str, files: int = 1) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        file_urls = [f"https://files.example.com/{issue_id}/f{i}.pdf" for i in range(files)]
        return _issue(issue_id), [_message("m1", html="<p>files</p>", file_urls=file_urls)]

    def _run_with_saves(
        self, issues: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], saves: list[Any]
    ) -> tuple[ImportBatchOutput | AttachmentStorageError, MagicMock]:
        client = self._client(
            [issue for issue, _ in issues.values()], {issue_id: messages for issue_id, (_, messages) in issues.items()}
        )
        with (
            patch(f"{M}.PylonImportClient", return_value=client),
            patch(f"{M}.save_file_to_uploaded_media", side_effect=saves),
            patch(f"{M}.discard_rehosted_attachments") as discard,
        ):
            result: ImportBatchOutput | AttachmentStorageError
            try:
                result = _import_issue_batch_sync(
                    ImportBatchInput(job_id=str(self.job.id), team_id=self.team.id, issue_ids=list(issues))
                )
            except AttachmentStorageError as exc:
                result = exc
        return result, discard

    def test_storage_failure_retries_the_batch_and_deletes_staged_uploads(self) -> None:
        result, discard = self._run_with_saves(
            {"i-701": self._attachment_issue("i-701"), "i-702": self._attachment_issue("i-702")},
            ["https://media.posthog.test/701", AttachmentStorageError("storage down")],
        )

        assert isinstance(result, AttachmentStorageError)
        # The first issue's upload has no persisted comment, so a retry would duplicate it.
        assert [a["url"] for a in discard.call_args.args[1]] == ["https://media.posthog.test/701"]
        assert not Ticket.objects.filter(team_id=self.team.id, pylon_issue_id__in=["i-701", "i-702"]).exists()

    def test_non_retryable_failure_deletes_only_that_issues_uploads(self) -> None:
        result, discard = self._run_with_saves(
            {"i-711": self._attachment_issue("i-711"), "i-712": self._attachment_issue("i-712", files=2)},
            ["https://media.posthog.test/711", "https://media.posthog.test/712-a", ValueError("bad file")],
        )

        assert isinstance(result, ImportBatchOutput)
        assert (result.imported, result.failed) == (1, 1)
        assert [a["url"] for a in discard.call_args.args[1]] == ["https://media.posthog.test/712-a"]

    def test_oversized_streamed_downloads_count_against_the_issue_budget(self) -> None:
        issue, messages = self._attachment_issue("i-721", files=3)
        client = self._client([issue], {"i-721": messages})
        client.download_attachment.side_effect = AttachmentTooLargeError("too big", bytes_read=150)

        with (
            patch(f"{M}.MAX_ATTACHMENT_BYTES_PER_ISSUE", 200),
            patch(f"{M}.PylonImportClient", return_value=client),
            patch(f"{M}.save_file_to_uploaded_media"),
        ):
            _import_issue_batch_sync(
                ImportBatchInput(job_id=str(self.job.id), team_id=self.team.id, issue_ids=["i-721"])
            )

        # 150 bytes streamed per rejected file: the second leaves 50 of 200 spent below zero, so the
        # third is never downloaded.
        assert client.download_attachment.call_count == 2


class TestPylonImportJobProgress(BaseTest):
    def test_replayed_progress_update_does_not_double_count(self) -> None:
        job = PylonImportJob.objects.unscoped().create(team_id=self.team.id, status=PylonImportJob.Status.RUNNING)
        an_hour_ago = timezone.now() - timedelta(hours=1)
        PylonImportJob.objects.unscoped().filter(id=job.id).update(updated_at=an_hour_ago)
        progress = UpdateJobProgressInput(
            job_id=str(job.id), total=150, processed=50, imported=40, skipped=8, failed=2, export_cursor="c2"
        )

        _update_job_progress_sync(progress)
        _update_job_progress_sync(progress)

        job.refresh_from_db()
        assert (
            job.total_issues,
            job.processed_issues,
            job.imported_issues,
            job.skipped_issues,
            job.failed_issues,
            job.export_cursor,
        ) == (150, 50, 40, 8, 2, "c2")
        assert job.updated_at > an_hour_ago
