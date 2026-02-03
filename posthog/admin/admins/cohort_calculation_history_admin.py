from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html


class CohortCalculationHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cohort_link",
        "team_link",
        "started_at",
        "finished_at",
        "duration_seconds",
        "count",
        "is_successful",
        "total_query_ms",
    )
    list_display_links = ("id",)
    list_filter = ("is_successful", "started_at", "team")
    search_fields = ("cohort__name", "cohort__id", "team__name")
    list_select_related = ("cohort", "team")
    ordering = ("-started_at",)
    readonly_fields = (
        "id",
        "team",
        "cohort",
        "started_at",
        "finished_at",
        "duration_seconds",
        "is_completed",
        "is_successful",
        "queries_display",
    )

    fieldsets = (
        ("Basic Information", {"fields": ("id", "team", "cohort", "started_at", "finished_at", "duration_seconds")}),
        ("Results", {"fields": ("count", "is_completed", "is_successful", "error")}),
        (
            "Query Information",
            {"fields": ("queries_display",), "description": "Query execution information and performance metrics"},
        ),
        ("Filters", {"fields": ("filters",), "classes": ("collapse",)}),
    )

    @admin.display(description="Cohort")
    def cohort_link(self, obj):
        if obj.cohort:
            return format_html(
                '<a href="{}">{} ({})</a>',
                reverse("admin:posthog_cohort_change", args=[obj.cohort.pk]),
                obj.cohort.name,
                obj.cohort.pk,
            )
        return "-"

    @admin.display(description="Team")
    def team_link(self, obj):
        if obj.team:
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:posthog_team_change", args=[obj.team.pk]),
                obj.team.name,
            )
        return "-"

    @admin.display(description="Query Details")
    def queries_display(self, obj):
        if not obj.queries:
            return "No query information available"

        query_htmls = []
        for i, query in enumerate(obj.queries):
            query_id = query.get("query_id", "N/A")
            duration = query.get("query_ms", "N/A")
            memory = query.get("memory_mb", "N/A")
            read_rows = query.get("read_rows", "N/A")
            written_rows = query.get("written_rows", "N/A")

            query_html = format_html(
                """<div style="border: 1px solid #ddd; padding: 10px; margin: 5px 0; border-radius: 5px;">
                    <strong>Query #{}</strong><br>
                    <strong>ID:</strong> <code style="background: #f8f9fa; padding: 2px 4px; user-select: all;">{}</code><br>
                    <strong>Duration:</strong> {} ms<br>
                    <strong>Memory:</strong> {} MB<br>
                    <strong>Rows Read:</strong> {} | <strong>Written:</strong> {}
                </div>""",
                i + 1,
                query_id,
                duration,
                memory,
                f"{read_rows:,}" if isinstance(read_rows, int) else read_rows,
                f"{written_rows:,}" if isinstance(written_rows, int) else written_rows,
            )
            query_htmls.append(query_html)

        return format_html("{}".join(["{}"] * len(query_htmls)), *query_htmls)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
