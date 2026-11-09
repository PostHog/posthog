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


class CompactConversationForm(forms.Form):
    conversation = forms.UUIDField(label="Conversation ID")
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


def compact(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    conversation_id = str(form.cleaned_data["conversation"])
    # nosemgrep: idor-lookup-without-team (staff-only PostHog Admin lookup across teams)
    if not Conversation.objects.filter(id=conversation_id).exists():
        form.add_error("conversation", "No conversation has this ID.")
        return HttpResponse(status=404)
    # Skips the sweep's rollout allowlist on purpose, because staff run this for one conversation they chose.
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
        messages.success(
            request,
            f"Compacted the conversation. Removed {result.checkpoints_deleted} checkpoints "
            f"and {result.blobs_deleted} blobs.",
        )
    else:
        messages.warning(request, f"Nothing compacted ({COMPACT_SKIP_REASON}).")
    return None


@console.register_tool
class ConversationCheckpointsTool(ConsoleTool):
    key = TOOL_KEY
    title = "AI conversation checkpoints"
    owner = DEV_EXPERIENCE
    group = "Data"
    description = "Compacts the stored checkpoints of one PostHog AI conversation."

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
                form_class=CompactConversationForm,
                form_initial={"conversation": request.GET.get("conversation", "")},
                description="Deletes every checkpoint of the conversation except the latest one in each namespace.",
                undo_hint="This cannot be undone. The deleted checkpoints are gone, and the latest state stays.",
            )
        ]
