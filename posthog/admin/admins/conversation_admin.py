from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.django_checkpoint.compaction import compact_thread


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "team_link", "user", "status", "type", "title", "updated_at")
    list_select_related = ("team", "user")
    list_filter = ("status", "type")
    search_fields = ("id", "team__name", "user__email")
    autocomplete_fields = ("team", "user")
    ordering = ("-updated_at",)
    actions = ["compact_checkpoints"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        # Conversation is soft-deleted by the app; don't expose a cascading hard-delete here.
        return False

    @admin.display(description="Team")
    def team_link(self, conversation: Conversation):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[conversation.team_id]),
            conversation.team.name,
        )

    @admin.action(description="Compact checkpoints (keep latest, reclaim storage)")
    def compact_checkpoints(self, request, queryset) -> None:
        # Bypasses the sweep's rollout allowlist — this is a deliberate staff override.
        compacted = skipped = checkpoints = blobs = 0
        for conversation in queryset:
            result = compact_thread(str(conversation.id))
            if result.compacted:
                compacted += 1
                checkpoints += result.checkpoints_deleted
                blobs += result.blobs_deleted
            else:
                skipped += 1
        self.message_user(
            request,
            f"Compacted {compacted} conversation(s) — reclaimed {checkpoints} checkpoints "
            f"and {blobs} blobs. Skipped {skipped} (not idle, awaiting approval, or nothing to compact).",
            messages.SUCCESS if compacted else messages.WARNING,
        )
