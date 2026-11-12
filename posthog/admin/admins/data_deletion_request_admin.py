from django.conf import settings
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models.data_deletion_request import DataDeletionRequest, build_deletion_count_query
from posthog.models.team import Team

# Dagster Cloud deployment slug per PostHog cloud environment. The admin runs on web pods, which
# don't carry DAGSTER_DOMAIN (only Dagster pods do), so the run URL is derived from CLOUD_DEPLOYMENT.
DAGSTER_DEPLOYMENT_BY_CLOUD = {"US": "prod-us", "EU": "prod-eu", "DEV": "dev"}


def dagster_run_url(run_id: str) -> str | None:
    """Link to a Dagster run, or None when the deployment can't be identified (local/self-hosted)."""
    if settings.DAGSTER_DOMAIN:
        return f"https://{settings.DAGSTER_DOMAIN}/runs/{run_id}"
    deployment = DAGSTER_DEPLOYMENT_BY_CLOUD.get((settings.CLOUD_DEPLOYMENT or "").upper())
    if deployment:
        return f"https://posthog.dagster.cloud/{deployment}/runs/{run_id}"
    return None


@admin.register(DataDeletionRequest)
class DataDeletionRequestAdmin(admin.ModelAdmin):
    """Read-only browsing. Staff create, edit, duplicate and run requests in PostHog Admin."""

    list_display = (
        "id",
        "team_id",
        "request_type",
        "status",
        "events",
        "start_time",
        "end_time",
        "created_by",
        "approved",
        "attempt_count",
        "last_executed_at",
        "created_at",
    )
    list_filter = ("request_type", "status", "requires_approval", "approved", "approved_automatically")
    search_fields = ("team_id", "events", "properties", "person_properties", "notes")
    readonly_fields = (
        "console_page",
        "team_details",
        "status",
        "count",
        "part_count",
        "parts_size",
        "parts_row_count",
        "min_timestamp",
        "max_timestamp",
        "stats_calculated_at",
        "hogql_query",
        "hogql_variables",
        "created_at",
        "created_by",
        "updated_at",
        "criteria_updated_by",
        "criteria_updated_at",
        "approved",
        "approved_automatically",
        "approved_by",
        "approved_at",
        "execution_mode",
        "attempt_count",
        "first_executed_at",
        "last_executed_at",
        "last_dagster_run",
        "rendered_count_query",
    )
    ordering = ("-created_at",)

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "console_page",
                    "team_id",
                    "request_type",
                    "status",
                    "start_time",
                    "end_time",
                    "events",
                    "delete_all_events",
                    "properties",
                    "person_properties",
                    "hogql_predicate",
                    "hogql_query",
                    "hogql_variables",
                    "notes",
                ),
            },
        ),
        (
            "ClickHouse stats",
            {
                "fields": (
                    "count",
                    "part_count",
                    "parts_size",
                    "parts_row_count",
                    "min_timestamp",
                    "max_timestamp",
                    "stats_calculated_at",
                    "rendered_count_query",
                ),
                "description": "Populated by executing a ClickHouse query. Not editable.",
            },
        ),
        (
            "Audit trail",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "criteria_updated_by",
                    "criteria_updated_at",
                    "updated_at",
                    "approved",
                    "approved_automatically",
                    "approved_by",
                    "approved_at",
                    "execution_mode",
                    "attempt_count",
                    "first_executed_at",
                    "last_executed_at",
                    "last_dagster_run",
                ),
            },
        ),
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="PostHog Admin")
    def console_page(self, obj: DataDeletionRequest) -> str:
        return format_html(
            '<a href="{}">Open this request in PostHog Admin &#8599;</a>',
            reverse("admin_console_deletion-request", kwargs={"pk": obj.pk}),
        )

    @admin.display(description="Team")
    def team_details(self, obj: DataDeletionRequest) -> str:
        team = Team.objects.select_related("organization").filter(id=obj.team_id).first()
        if team is None:
            return format_html("{} <em>(team not found)</em>", obj.team_id)
        return format_html(
            '<a href="{}">{}</a> {} · organization <a href="{}">{}</a> {}',
            reverse("admin:posthog_team_change", args=[team.pk]),
            team.pk,
            team.name,
            reverse("admin:posthog_organization_change", args=[team.organization_id]),
            team.organization_id,
            team.organization.name,
        )

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None:
            return fieldsets
        return [
            (name, {**options, "fields": tuple("team_details" if f == "team_id" else f for f in options["fields"])})
            for name, options in fieldsets
        ]

    @admin.display(description="Last Dagster run")
    def last_dagster_run(self, obj: DataDeletionRequest) -> str:
        """Link to the Dagster run of the latest execution attempt, for debugging in-flight requests."""
        if not obj.last_dagster_run_id:
            return "—"
        url = dagster_run_url(obj.last_dagster_run_id)
        if url is None:
            return obj.last_dagster_run_id
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, obj.last_dagster_run_id)

    @admin.display(description="Count query (ready to paste)")
    def rendered_count_query(self, obj: DataDeletionRequest) -> str:
        """Show the fully-substituted ClickHouse COUNT query operators can copy/paste."""
        from posthog.clickhouse.client.escape import substitute_params_for_display

        if obj.pk is None or not obj.team_id or not obj.start_time or not obj.end_time:
            return "—"
        try:
            template, params = build_deletion_count_query(obj)
            rendered = substitute_params_for_display(template, params)
        except Exception as exc:
            return format_html("<em>Could not render query: {}</em>", str(exc))
        return format_html(
            '<pre style="white-space: pre-wrap; background: #f5f5f5; padding: 8px;">{}</pre>',
            rendered,
        )
