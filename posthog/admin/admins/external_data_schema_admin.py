from django.conf import settings
from django.contrib import admin
from django.core.paginator import Paginator
from django.urls import reverse
from django.utils.html import format_html

from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


class ExternalDataSchemaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "status",
        "should_sync",
        "sync_type",
        "source_type",
        "team_link",
        "last_synced_at",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization", "source")
    list_filter = ("status", "should_sync", "sync_type")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team",)
    raw_id_fields = ("table", "source")
    readonly_fields = ("table", "source", "created_by")
    ordering = ("-created_at",)

    change_form_template = "admin/data_warehouse/externaldataschema/change_form.html"

    JOBS_PER_PAGE = 20

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            jobs_qs = ExternalDataJob.objects.filter(schema=obj).order_by("-created_at")
            paginator = Paginator(jobs_qs, self.JOBS_PER_PAGE)
            page_number = request.GET.get("page", 1)
            page_obj = paginator.get_page(page_number)

            extra_context["page_obj"] = page_obj
            extra_context["temporal_ui_host"] = settings.TEMPORAL_UI_HOST
            extra_context["temporal_namespace"] = settings.TEMPORAL_NAMESPACE
            extra_context["site_url"] = settings.SITE_URL
            extra_context["team_id"] = obj.team_id
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    @admin.display(description="Team")
    def team_link(self, schema: ExternalDataSchema):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[schema.team.pk]),
            schema.team.name,
        )

    @admin.display(description="Source type")
    def source_type(self, schema: ExternalDataSchema):
        return schema.source.source_type
