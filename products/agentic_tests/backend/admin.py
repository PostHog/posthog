from django.contrib import admin
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from products.agentic_tests.backend.models import AgenticTest, AgenticTestRun


class AgenticTestRunInline(admin.TabularInline):
    model = AgenticTestRun
    extra = 0
    can_delete = False
    fields = ("id", "status", "started_at", "finished_at", "duration_ms", "error_message")
    readonly_fields = ("id", "status", "started_at", "finished_at", "duration_ms", "error_message")
    ordering = ("-started_at",)
    show_change_link = True

    def has_add_permission(self, request: HttpRequest, obj: object | None = None) -> bool:
        return False


class AgenticTestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "status",
        "team_link",
        "created_by_link",
        "target_url",
        "last_run_at",
        "next_run_at",
        "created_at",
    )
    list_filter = ("status", "created_at", "last_run_at", "next_run_at")
    search_fields = ("id", "name", "description", "target_url", "team__name", "created_by__email")
    readonly_fields = ("id", "created_at", "updated_at", "last_run_at", "next_run_at")
    autocomplete_fields = ("team", "created_by")
    inlines = (AgenticTestRunInline,)

    fieldsets = (
        (None, {"fields": ("id", "name", "description", "status")}),
        ("Team & User", {"fields": ("team", "created_by")}),
        ("Target", {"fields": ("target_url", "prompt", "source_replay_id")}),
        ("Assertions", {"fields": ("assertions",)}),
        (
            "Schedule",
            {
                "fields": (
                    "schedule_cron",
                    "next_run_at",
                    "last_run_at",
                )
            },
        ),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Team")
    def team_link(self, obj: AgenticTest) -> str:
        if obj.team:
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:posthog_team_change", args=[obj.team.pk]),
                obj.team.name,
            )
        return "-"

    @admin.display(description="Created by")
    def created_by_link(self, obj: AgenticTest) -> str:
        if obj.created_by:
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:posthog_user_change", args=[obj.created_by.pk]),
                obj.created_by.email,
            )
        return "-"


class AgenticTestRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agentic_test_link",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
    )
    list_filter = ("status", "started_at", "finished_at")
    search_fields = ("id", "agentic_test__name", "agentic_test__id", "external_session_id", "error_message")
    readonly_fields = ("id", "started_at", "finished_at", "duration_ms")
    autocomplete_fields = ("agentic_test",)

    fieldsets = (
        (None, {"fields": ("id", "agentic_test", "status")}),
        ("Timing", {"fields": ("started_at", "finished_at", "duration_ms")}),
        ("Result", {"fields": ("output", "error_message")}),
        ("Runner", {"fields": ("external_session_id", "screenshot_url")}),
    )

    @admin.display(description="Agentic test")
    def agentic_test_link(self, obj: AgenticTestRun) -> str:
        if obj.agentic_test:
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:agentic_tests_agentictest_change", args=[obj.agentic_test.pk]),
                obj.agentic_test.name,
            )
        return "-"
