from collections.abc import Mapping
from typing import Any
from uuid import UUID

from django import forms
from django.contrib import messages
from django.db.models import Count
from django.http import HttpRequest, HttpResponse

import structlog

from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table, ToolOperation
from posthog.utils import pluralize

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.django_checkpoint.compaction import compact_conversation

logger = structlog.get_logger(__name__)

TOOL_KEY = "ai-conversation-checkpoints"
COMPACT_SKIP_REASON = "not idle, awaiting approval, or nothing to compact"


class CompactConversationsForm(forms.Form):
    conversations = forms.CharField(
        label="Conversation IDs",
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="One ID per line.",
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")

    def clean_conversations(self) -> list[str]:
        ids: list[str] = []
        for line in self.cleaned_data["conversations"].split():
            try:
                ids.append(str(UUID(line)))
            except ValueError:
                raise forms.ValidationError(f"{line} is not a conversation ID.")
        if not ids:
            raise forms.ValidationError("Enter at least one conversation ID.")
        return list(dict.fromkeys(ids))


def _unknown_ids(conversation_ids: list[str], found_ids: set[str]) -> list[str]:
    return [conversation_id for conversation_id in conversation_ids if conversation_id not in found_ids]


def _unknown_ids_error(unknown: list[str]) -> str:
    return f"No conversation has these IDs: {', '.join(unknown)}. Nothing was compacted."


def _preview_row(conversation: Mapping[str, Any]) -> Row:
    if conversation["status"] != Conversation.Status.IDLE:
        what_happens = "Skipped, the conversation is not idle"
    else:
        deletable = max(conversation["checkpoint_count"] - conversation["namespace_count"], 0)
        what_happens = f"Deletes up to {pluralize(deletable, 'checkpoint')} and their blobs"
    return Row(
        cells=(
            Cell(text=str(conversation["id"]), mono=True),
            Cell(text=str(conversation["team_id"]), mono=True),
            Cell(text=Conversation.Status(conversation["status"]).label),
            Cell(text=str(conversation["checkpoint_count"])),
            Cell(text=what_happens),
        )
    )


def preview_compaction(request: HttpRequest, form: forms.Form) -> Page:
    conversation_ids: list[str] = form.cleaned_data["conversations"]
    conversations = list(
        # nosemgrep: idor-lookup-without-team (staff-only PostHog Admin lookup across teams)
        Conversation.objects.filter(id__in=conversation_ids)
        .annotate(
            checkpoint_count=Count("checkpoints"),
            namespace_count=Count("checkpoints__checkpoint_ns", distinct=True),
        )
        .order_by("id")
        .values("id", "team_id", "status", "checkpoint_count", "namespace_count")
    )
    unknown = _unknown_ids(conversation_ids, {str(conversation["id"]) for conversation in conversations})
    if unknown:
        form.add_error("conversations", _unknown_ids_error(unknown))
        return Page(blocks=())
    return Page(
        blocks=(
            Notice(
                text=(
                    f"Compacts {pluralize(len(conversations), 'conversation')}. Each keeps the latest checkpoint "
                    "of every namespace. A conversation waiting for an approval is skipped when it runs."
                )
            ),
            Table(
                columns=("Conversation", "Team ID", "Status", "Checkpoints", "What happens"),
                rows=tuple(_preview_row(conversation) for conversation in conversations),
            ),
        )
    )


def compact(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    conversation_ids: list[str] = form.cleaned_data["conversations"]
    # Conversations can be deleted between the preview and the confirm.
    # nosemgrep: idor-lookup-without-team (staff-only PostHog Admin lookup across teams)
    existing = {str(pk) for pk in Conversation.objects.filter(id__in=conversation_ids).values_list("id", flat=True)}
    unknown = _unknown_ids(conversation_ids, existing)
    if unknown:
        form.add_error("conversations", _unknown_ids_error(unknown))
        return HttpResponse(status=404)
    compacted = skipped = checkpoints = blobs = 0
    for conversation_id in conversation_ids:
        # Skips the sweep's rollout allowlist on purpose, because staff chose these conversations.
        result = compact_conversation(conversation_id)
        logger.info(
            "admin_compact_conversation",
            conversation_id=conversation_id,
            compacted=result.compacted,
            checkpoints_deleted=result.checkpoints_deleted,
            blobs_deleted=result.blobs_deleted,
            namespaces=result.namespaces,
        )
        if result.compacted:
            compacted += 1
            checkpoints += result.checkpoints_deleted
            blobs += result.blobs_deleted
        else:
            skipped += 1
    if compacted:
        messages.success(
            request, f"Compacted {compacted} conversation(s). Removed {checkpoints} checkpoints and {blobs} blobs."
        )
    if skipped:
        messages.warning(request, f"Skipped {skipped} conversation(s) ({COMPACT_SKIP_REASON}).")
    return None


@console.register_tool
class ConversationCheckpointsTool(ConsoleTool):
    key = TOOL_KEY
    title = "AI conversation checkpoints"
    owner = DEV_EXPERIENCE
    group = "Data"
    description = "Compacts the stored checkpoints of PostHog AI conversations."

    def page(self, request: HttpRequest) -> Page:
        return Page(
            blocks=(
                Notice(
                    text=(
                        "Compacting keeps the latest checkpoint of each graph namespace and deletes the older ones "
                        "and their blobs. The conversation keeps working. A conversation that is running or waiting "
                        "for an approval is skipped. The checkpoint counts are on the conversation's Django admin page."
                    )
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        return [
            ToolOperation(
                key="compact",
                label="Compact checkpoints",
                handler=compact,
                preview=preview_compaction,
                danger=True,
                form_class=CompactConversationsForm,
                form_initial={"conversations": request.GET.get("conversation", "")},
                description="Deletes every checkpoint of each conversation except the latest one in each namespace.",
                undo_hint="This cannot be undone. The deleted checkpoints are gone, and the latest state stays.",
            )
        ]


console.register_moved_page(
    old_path="admin/posthog_ai/conversation/<uuid:pk>/compact/",
    title="Compacting a conversation",
    url="/admin/console/tools/ai-conversation-checkpoints/compact/?conversation={pk}",
)
