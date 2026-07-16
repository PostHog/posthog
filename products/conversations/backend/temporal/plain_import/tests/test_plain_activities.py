from __future__ import annotations

from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models.comment import Comment

from products.conversations.backend.models import EmailChannel, PlainImportJob, Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.temporal.plain_import.activities import (
    ImportBatchInput,
    UpdateJobProgressInput,
    UpdateJobStatusInput,
    _import_thread_batch_sync,
    _update_job_progress_sync,
    _update_job_status_sync,
)

M = "products.conversations.backend.temporal.plain_import.activities"


def _plain_thread(
    tid: str,
    *,
    status: str = "TODO",
    priority: int = 2,
    title: str = "Help",
    email: str = "customer@example.com",
    name: str = "Customer",
    message_source: str = "EMAIL",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": tid,
        "ref": "T-1",
        "title": title,
        "priority": priority,
        "status": status,
        "createdAt": {"iso8601": "2020-01-02T03:04:05Z"},
        "customer": {
            "id": "c_1",
            "fullName": name,
            "email": {"email": email, "isVerified": True},
        },
        "labels": [{"labelType": {"name": n}} for n in (labels or [])],
        "firstInboundMessageInfo": {"messageSource": message_source},
    }


def _timeline_entry(
    eid: str,
    *,
    actor: str = "CustomerActor",
    entry_typename: str = "EmailEntry",
    body: str = "hello",
    is_note: bool = False,
) -> dict[str, Any]:
    if is_note:
        entry: dict[str, Any] = {"__typename": "NoteEntry", "markdown": body, "text": body, "attachments": []}
    elif entry_typename == "EmailEntry":
        entry = {
            "__typename": "EmailEntry",
            "subject": None,
            "fullMarkdownContent": body,
            "fullTextContent": body,
            "from": {"name": "Customer", "email": "customer@example.com"},
            "to": {"name": "Support", "email": "support@example.com"},
            "attachments": [],
        }
    else:
        entry = {"__typename": entry_typename, "text": body, "attachments": []}
    return {
        "id": eid,
        "actor": {"__typename": actor},
        "timestamp": {"iso8601": "2020-01-02T03:04:05Z"},
        "entry": entry,
    }


class TestPlainImportBatchActivity(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.job = PlainImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=PlainImportJob.Status.RUNNING,
            job_inputs={"api_key": "key", "region": "uk"},
        )

    def _run_batch(
        self,
        thread_ids: list[str],
        *,
        threads: dict[str, dict[str, Any]],
        timeline_by_thread: dict[str, list[dict[str, Any]]],
        default_email_channel_id: str | None = None,
        dry_run: bool = False,
    ) -> tuple[Any, MagicMock]:
        client = MagicMock()
        client.fetch_thread.side_effect = lambda tid: threads[tid]
        client.fetch_timeline_entries.side_effect = lambda tid: timeline_by_thread.get(tid, [])

        with (
            patch(f"{M}.PlainImportClient", return_value=client),
            patch(f"{M}.save_file_to_uploaded_media", return_value=None),
        ):
            result = _import_thread_batch_sync(
                ImportBatchInput(
                    job_id=str(self.job.id),
                    team_id=self.team.id,
                    thread_ids=thread_ids,
                    default_email_channel_id=default_email_channel_id,
                    dry_run=dry_run,
                )
            )
        return result, client

    def test_idempotency_skips_already_imported_threads(self) -> None:
        Ticket.objects.create(
            team=self.team,
            ticket_number=1,
            widget_session_id="existing",
            distinct_id="d",
            plain_thread_id="t_111",
        )

        result, client = self._run_batch(
            ["t_111"],
            threads={},
            timeline_by_thread={},
        )

        self.assertEqual((result.imported, result.skipped, result.failed), (0, 1, 0))
        self.assertEqual(Ticket.objects.filter(team=self.team, plain_thread_id="t_111").count(), 1)
        client.fetch_thread.assert_not_called()

    def test_dry_run_does_not_persist(self) -> None:
        result, _client = self._run_batch(
            ["t_1"],
            threads={"t_1": _plain_thread("t_1")},
            timeline_by_thread={},
            dry_run=True,
        )
        self.assertEqual(result.imported, 1)
        self.assertEqual(Ticket.objects.filter(team=self.team, plain_thread_id="t_1").count(), 0)

    def test_imports_thread_with_comments_and_tags(self) -> None:
        from posthog.models import Tag
        from posthog.models.tagged_item import TaggedItem

        result, _client = self._run_batch(
            ["t_1"],
            threads={"t_1": _plain_thread("t_1", labels=["billing", "urgent"])},
            timeline_by_thread={
                "t_1": [
                    _timeline_entry("e1", actor="CustomerActor", body="Need help"),
                    _timeline_entry("e2", actor="UserActor", body="On it"),
                    _timeline_entry("e3", actor="UserActor", body="Internal", is_note=True),
                ]
            },
        )
        self.assertEqual((result.imported, result.skipped, result.failed), (1, 0, 0))
        ticket = Ticket.objects.get(team=self.team, plain_thread_id="t_1")
        self.assertEqual(ticket.status, Status.OPEN)
        self.assertEqual(ticket.channel_source, Channel.EMAIL)
        self.assertEqual(ticket.distinct_id, "customer@example.com")
        self.assertEqual(ticket.message_count, 2)  # note excluded
        comments = list(Comment.objects.filter(team=self.team, item_id=str(ticket.id)).order_by("created_at"))
        self.assertEqual(len(comments), 3)
        private = [c for c in comments if (c.item_context or {}).get("is_private")]
        self.assertEqual(len(private), 1)
        tag_names = set(
            Tag.objects.filter(
                id__in=TaggedItem.objects.filter(ticket=ticket).values_list("tag_id", flat=True)
            ).values_list("name", flat=True)
        )
        self.assertEqual(tag_names, {"billing", "urgent"})

    def test_assigns_default_email_channel_for_email_threads_only(self) -> None:
        channel = EmailChannel.objects.create(
            team=self.team,
            inbound_token="plain-import-test",
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
            domain_verified=True,
        )
        result, _client = self._run_batch(
            ["t_email", "t_slack"],
            threads={
                "t_email": _plain_thread("t_email", message_source="EMAIL"),
                "t_slack": _plain_thread("t_slack", message_source="SLACK", email="slack@example.com"),
            },
            timeline_by_thread={},
            default_email_channel_id=str(channel.id),
        )
        self.assertEqual(result.imported, 2)
        email_ticket = Ticket.objects.get(team=self.team, plain_thread_id="t_email")
        slack_ticket = Ticket.objects.get(team=self.team, plain_thread_id="t_slack")
        self.assertEqual(email_ticket.email_config_id, channel.id)
        self.assertIsNone(slack_ticket.email_config_id)
        self.assertEqual(slack_ticket.channel_source, Channel.SLACK)


class TestPlainImportJobUpdates(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.job = PlainImportJob.objects.unscoped().create(
            team_id=self.team.id,
            status=PlainImportJob.Status.PENDING,
            job_inputs={"api_key": "key", "region": "uk"},
        )

    def test_update_job_status_sets_started_and_finished(self) -> None:
        _update_job_status_sync(UpdateJobStatusInput(job_id=str(self.job.id), status=PlainImportJob.Status.RUNNING))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, PlainImportJob.Status.RUNNING)
        self.assertIsNotNone(self.job.started_at)

        _update_job_status_sync(UpdateJobStatusInput(job_id=str(self.job.id), status=PlainImportJob.Status.COMPLETED))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, PlainImportJob.Status.COMPLETED)
        self.assertIsNotNone(self.job.finished_at)

    def test_update_job_progress_sets_absolute_counters_idempotently(self) -> None:
        payload = UpdateJobProgressInput(
            job_id=str(self.job.id),
            processed=2,
            imported=1,
            skipped=1,
            failed=0,
            total=5,
            export_cursor="cursor-1",
        )
        _update_job_progress_sync(payload)
        # Reapplying the identical payload (e.g. an activity retry after the commit but before
        # completion is acknowledged) must not double-count — counters are absolute, not additive.
        _update_job_progress_sync(payload)
        self.job.refresh_from_db()
        self.assertEqual(self.job.processed_tickets, 2)
        self.assertEqual(self.job.imported_tickets, 1)
        self.assertEqual(self.job.skipped_tickets, 1)
        self.assertEqual(self.job.failed_tickets, 0)
        self.assertEqual(self.job.total_tickets, 5)
        self.assertEqual(self.job.export_cursor, "cursor-1")
