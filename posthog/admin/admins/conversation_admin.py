from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.db.models.functions import Length
from django.http import HttpResponseNotAllowed
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.template.defaultfilters import filesizeformat
from django.urls import path, reverse
from django.utils.html import format_html

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.django_checkpoint.compaction import compact_thread

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

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        # Stash the request so checkpoint_storage can mint a CSRF token for its POST form.
        self._current_request = request
        return super().changeform_view(request, object_id, form_url, extra_context)

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
        # Blobs hold the bulk of a thread's bytes; query them via `thread`, not the `checkpoint` FK.
        blobs = conversation.blobs.aggregate(count=Count("id"), total_bytes=Sum(Length("blob")))
        request = getattr(self, "_current_request", None)
        # POST form rather than a link: compaction deletes rows, so it must not run on a GET.
        return format_html(
            "{} checkpoints, {} blobs ({}) &nbsp;"
            '<form method="post" action="{}" style="display: inline">'
            '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
            '<button type="submit" class="button">Compact now</button>'
            "</form>",
            conversation.checkpoints.count(),
            blobs["count"] or 0,
            filesizeformat(blobs["total_bytes"] or 0),
            reverse("admin:posthog_ai_conversation_compact", args=[conversation.pk]),
            get_token(request) if request is not None else "",
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
        result = compact_thread(str(conversation.id))
        if result.compacted:
            self.message_user(
                request,
                f"Compacted — reclaimed {result.checkpoints_deleted} checkpoints and {result.blobs_deleted} blobs.",
                messages.SUCCESS,
            )
        else:
            self.message_user(request, f"Nothing compacted ({_COMPACT_SKIP_REASON}).", messages.WARNING)
        return redirect("admin:posthog_ai_conversation_change", object_id)

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
            f"and {blobs} blobs. Skipped {skipped} ({_COMPACT_SKIP_REASON}).",
            messages.SUCCESS if compacted else messages.WARNING,
        )
