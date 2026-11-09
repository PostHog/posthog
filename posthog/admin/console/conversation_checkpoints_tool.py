from uuid import UUID

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse

import structlog

from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import ConsoleTool, Notice, Page, ToolOperation

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


def compact(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    conversation_ids: list[str] = form.cleaned_data["conversations"]
    # nosemgrep: idor-lookup-without-team (staff-only PostHog Admin lookup across teams)
    existing = {str(pk) for pk in Conversation.objects.filter(id__in=conversation_ids).values_list("id", flat=True)}
    unknown = [conversation_id for conversation_id in conversation_ids if conversation_id not in existing]
    if unknown:
        form.add_error("conversations", f"No conversation has these IDs: {', '.join(unknown)}. Nothing was compacted.")
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
                danger=True,
                form_class=CompactConversationsForm,
                form_initial={"conversations": request.GET.get("conversation", "")},
                description="Deletes every checkpoint of each conversation except the latest one in each namespace.",
                undo_hint="This cannot be undone. The deleted checkpoints are gone, and the latest state stays.",
            )
        ]
