from urllib.parse import urljoin

from django.conf import settings
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models import ExportedAsset


class ExportedAssetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team_link",
        "export_format",
        "created_at",
        "expires_after",
        "content_is_set",
        "content_location_link",
    )
    list_display_links = ("id",)
    list_filter = ("export_format",)
    search_fields = ("id", "team__name", "team__organization__name", "content_location")
    ordering = ("-id",)
    show_full_result_count = False
    list_select_related = ("team", "team__organization")

    @admin.display(description="Team")
    def team_link(self, asset: ExportedAsset):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[asset.team.pk]),
            asset.team.name,
        )

    readonly_fields = (
        "id",
        "team",
        "dashboard",
        "insight",
        "created_by",
        "export_format",
        "export_context",
        "created_at",
        "expires_after",
        "content_is_set",
        "content_location",
        "content_location_link",
        "exception",
        "exception_type",
        "failure_type",
    )

    fields = readonly_fields

    @admin.display(boolean=True, description="Content set")
    def content_is_set(self, obj: ExportedAsset) -> bool:
        return obj.has_content

    @admin.display(description="Content location URL")
    def content_location_link(self, obj: ExportedAsset) -> str:
        if not obj.content_location:
            return "-"

        if not settings.OBJECT_STORAGE_ENDPOINT:
            return "-"

        # Validate content_location to prevent open redirect attacks
        if obj.content_location.startswith("/") or "://" in obj.content_location:
            return "-"

        base = settings.OBJECT_STORAGE_ENDPOINT.rstrip("/") + "/"
        bucket_path = f"{settings.OBJECT_STORAGE_BUCKET}/{obj.content_location}"
        url = urljoin(base, bucket_path)
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', url, url)

    def get_queryset(self, request):
        return super().get_queryset(request).defer("content")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
