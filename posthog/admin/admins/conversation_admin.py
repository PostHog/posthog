from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.db.models.functions import Length
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.template.defaultfilters import filesizeformat
from django.urls import path, reverse
from django.utils.html import format_html

from structlog import get_logger

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.django_checkpoint.compaction import compact_conversation

logger = get_logger()

_COMPACT_SKIP_REASON = "not idle, awaiting approval, or nothing to compact"


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "team_link", "user", "status", "type", "title", "updated_at")
    list_select_related = ("team", "user")
    list_filter = ("status", "type")
    search_fields = ("id", "team__name", "user__email")
    autocomplete_fields = ("team", "user")
    # `task` uses raw_id rather than autocomplete: its admin lives in the tasks product and
    # isn't guaranteed registered when ConversationAdmin's system checks run (admin.E039).
    # raw_id_fields needs no registered target admin and still avoids the full-table <select>.
    raw_id_fields = ("task",)
    readonly_fields = ("checkpoint_storage",)
    ordering = ("-updated_at",)
    actions = ["compact_checkpoints"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        # Conversation is soft-deleted by the app; don't expose a cascading hard-delete here.
        return False

    def get_urls(self):
        compact_url = path(
            "<path:object_id>/compact/",
            self.admin_site.admin_view(self.compact_view),
            name="posthog_ai_conversation_compact",
        )
        return [compact_url, *super().get_urls()]

    @admin.display(description="Team")
    def team_link(self, conversation: Conversation):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[conversation.team_id]),
            conversation.team.name,
        )

    @admin.display(description="Checkpoint storage")
    def checkpoint_storage(self, conversation: Conversation):
        # Change-page only — do not add to list_display: the bytea Length() sum would run per row.
        # Blobs hold the bulk of a thread's bytes; query them via `thread`, not the `checkpoint` FK.
        checkpoints = conversation.checkpoints.aggregate(
            total=Count("id"), namespaces=Count("checkpoint_ns", distinct=True)
        )
        blobs = conversation.blobs.aggregate(count=Count("id"), total_bytes=Sum(Length("blob")))
        # A submit button in the admin's own <form> (not a nested one, which browsers won't submit):
        # formaction posts with the form's CSRF token, so this destructive action never runs on a GET.
        return format_html(
            "{} checkpoints across {} namespace(s), {} blobs ({}) &nbsp;"
            '<button type="submit" class="button" formmethod="post" formaction="{}" formnovalidate '
            'data-attr="conversation-admin-compact-now">Compact now</button>',
            checkpoints["total"],
            checkpoints["namespaces"],
            blobs["count"] or 0,
            filesizeformat(blobs["total_bytes"] or 0),
            reverse("admin:posthog_ai_conversation_compact", args=[conversation.pk]),
        )

    def compact_view(self, request, object_id: str):
        conversation = self.get_object(request, object_id)
        if conversation is None:
            self.message_user(request, "Conversation not found.", messages.ERROR)
            return redirect("admin:posthog_ai_conversation_changelist")
        if not self.has_change_permission(request, conversation):
            raise PermissionDenied
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        # Bypasses the sweep's rollout allowlist — this is a deliberate staff override.
        result = compact_conversation(str(conversation.id))
        logger.info(
            "admin_compact_conversation",
            conversation_id=str(conversation.id),
            compacted=result.compacted,
            checkpoints_deleted=result.checkpoints_deleted,
            blobs_deleted=result.blobs_deleted,
            namespaces=result.namespaces,
            triggered_by=request.user.email,
        )
        if result.compacted:
            self.message_user(
                request,
                f"Compacted — reclaimed {result.checkpoints_deleted} checkpoints and {result.blobs_deleted} blobs.",
                messages.SUCCESS,
            )
        else:
            self.message_user(request, f"Nothing compacted ({_COMPACT_SKIP_REASON}).", messages.WARNING)
        return redirect("admin:posthog_ai_conversation_change", conversation.id)

    @admin.action(description="Compact checkpoints (keep latest, reclaim storage)")
    def compact_checkpoints(self, request, queryset) -> None:
        # Bypasses the sweep's rollout allowlist — this is a deliberate staff override.
        compacted = skipped = checkpoints = blobs = 0
        for conversation in queryset:
            result = compact_conversation(str(conversation.id))
            if result.compacted:
                compacted += 1
                checkpoints += result.checkpoints_deleted
                blobs += result.blobs_deleted
            else:
                skipped += 1
        self.message_user(
            request,
            f"Compacted {compacted} conversation(s) — reclaimed {checkpoints} checkpoints "
            f"and {blobs} blobs. Skipped {skipped} ({_COMPACT_SKIP_REASON}).",
            messages.SUCCESS if compacted else messages.WARNING,
        )
