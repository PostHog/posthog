from django.contrib import admin, messages
from django.core.cache import cache
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.text import Truncator

import structlog

from posthog.models.team import Team

from products.aeo.backend.models import AEOPrompt
from products.aeo.backend.tasks.tasks import citation_tracking_skip_reason, run_aeo_citation_checks_for_team_task

logger = structlog.get_logger(__name__)

RUN_NOW_COOLDOWN_SECONDS = 60 * 60


@admin.register(AEOPrompt)
class AEOPromptAdmin(admin.ModelAdmin):
    list_display = ("short_prompt", "team_id", "topic", "prompt_source", "active", "last_checked_at", "created_at")
    list_filter = ("active", "prompt_source", "topic")
    search_fields = ("prompt", "=team__id")
    ordering = ("team_id", "topic", "-created_at")
    readonly_fields = (
        "id",
        "team",
        "created_by",
        "prompt",
        "prompt_hash",
        "prompt_source",
        "evidence",
        "topic",
        "rank",
        "active",
        "last_checked_at",
        "created_at",
        "updated_at",
    )
    show_full_result_count = False
    actions = ["run_citation_checks_now"]

    @admin.display(description="Prompt")
    def short_prompt(self, obj: AEOPrompt) -> str:
        return Truncator(obj.prompt).chars(80)

    def get_queryset(self, request: HttpRequest) -> QuerySet[AEOPrompt]:
        return AEOPrompt.objects.unscoped()

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: AEOPrompt | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: AEOPrompt | None = None) -> bool:
        return False

    @admin.action(description="Run AEO citation checks now for the selected prompts' teams")
    def run_citation_checks_now(self, request: HttpRequest, queryset: QuerySet[AEOPrompt]) -> None:
        team_ids = queryset.order_by("team_id").values_list("team_id", flat=True).distinct()
        for team_id in team_ids:
            self._queue_run(request, team_id)

    def _queue_run(self, request: HttpRequest, team_id: int) -> None:
        active_prompts = AEOPrompt.objects.for_team(team_id).filter(active=True).count()
        cooldown_key = f"aeo_citation_admin_run:{team_id}"
        reason = self._skip_reason(team_id, active_prompts, cooldown_key)
        if reason is not None:
            self.message_user(request, f"Team {team_id} skipped: {reason}.", level=messages.WARNING)
            return

        try:
            run_aeo_citation_checks_for_team_task.delay(team_id)
        except Exception:
            cache.delete(cooldown_key)
            logger.exception("aeo_citation_admin_run_failed", team_id=team_id)
            self.message_user(
                request, f"Couldn't queue AEO citation checks for team {team_id}. Try again.", level=messages.ERROR
            )
            return

        logger.info(
            "aeo_citation_admin_run_queued",
            team_id=team_id,
            prompts=active_prompts,
            triggered_by=request.user.pk,
        )
        self.message_user(
            request,
            f"Queued AEO citation checks for team {team_id} ({active_prompts} active prompts). "
            "Results appear in system.aeo_citation_checks as each prompt finishes.",
            level=messages.SUCCESS,
        )

    def _skip_reason(self, team_id: int, active_prompts: int, cooldown_key: str) -> str | None:
        team = Team.objects.filter(id=team_id).first()
        if team is None:
            return "it no longer exists"
        if reason := citation_tracking_skip_reason(team):
            return reason
        if active_prompts == 0:
            return "it has no active prompts"
        if not cache.add(cooldown_key, True, timeout=RUN_NOW_COOLDOWN_SECONDS):
            return "a run was already queued from admin in the last hour"
        return None
