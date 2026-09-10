from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import ContextLayerConfig


@admin.register(ContextLayerConfig)
class ContextLayerConfigAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "head_sha",
        "dreaming_paused",
        "dream_failure_streak",
        "last_dream_started_at",
        "purge_incomplete_at",
    )
    list_filter = ("dreaming_paused",)
    search_fields = ("organization__id",)
    raw_id_fields = ("organization", "created_by")
    readonly_fields = ("id", "head_sha", "created_at", "updated_at")
    ordering = ("-created_at",)
    show_full_result_count = False
    actions = ("unpause_dreaming",)

    @admin.action(description="Unpause dreaming")
    def unpause_dreaming(self, request: HttpRequest, queryset: QuerySet[ContextLayerConfig]) -> None:
        # Leave dream_failure_streak alone: the circuit breaker pauses on every
        # full threshold of consecutive failures, so a preserved streak gives an
        # unpaused lane a fresh threshold of attempts before re-pausing.
        queryset.update(dreaming_paused=False)
