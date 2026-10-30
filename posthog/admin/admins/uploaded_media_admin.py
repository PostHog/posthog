from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

import structlog

from posthog.models import UploadedMedia

logger = structlog.get_logger(__name__)


@admin.register(UploadedMedia)
class UploadedMediaAdmin(admin.ModelAdmin):
    list_display = ("id", "file_name", "team_link", "purpose", "created_at", "archived_at", "serving_disabled_at")
    # The table holds every dashboard image and toolbar screenshot, so look rows up by exact id
    # (the UUID in the public URL) or team id, and skip the full count on each page.
    search_fields = ("id__exact", "team__id__exact")
    show_full_result_count = False
    ordering = ("-created_at",)
    actions = ["disable_serving", "enable_serving"]
    fields = (
        "id",
        "file_name",
        "public_url",
        "team_link",
        "created_by_link",
        "purpose",
        "content_type",
        "size_bytes",
        "media_location",
        "created_at",
        "archived_at",
        "serving_disabled_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: UploadedMedia | None = None) -> bool:
        return False

    @admin.display(description="Team")
    def team_link(self, obj: UploadedMedia) -> str:
        url = reverse("admin:posthog_team_change", args=[obj.team_id])
        return format_html('<a href="{}">{}</a>', url, obj.team_id)

    @admin.display(description="Created by")
    def created_by_link(self, obj: UploadedMedia) -> str:
        if not obj.created_by_id:
            return "-"
        url = reverse("admin:posthog_user_change", args=[obj.created_by_id])
        return format_html('<a href="{}">{}</a>', url, obj.created_by_id)

    @admin.display(description="Public URL")
    def public_url(self, obj: UploadedMedia) -> str:
        url = obj.get_absolute_url()
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', url, url)

    @admin.action(description="Stop serving the selected images at their public URL")
    def disable_serving(self, request: HttpRequest, queryset: QuerySet[UploadedMedia]) -> None:
        changed = list(queryset.filter(serving_disabled_at__isnull=True))
        now = timezone.now()
        for media in changed:
            media.serving_disabled_at = now
            media.save(update_fields=["serving_disabled_at"])
            self.log_change(request, media, "Stopped serving at the public URL.")
            logger.info("uploaded_media.serving_disabled", media_id=str(media.id), team_id=media.team_id)
        self.message_user(
            request,
            f"Stopped serving {len(changed)} image(s). Copies that CDNs or browsers already cached "
            "can still load until those caches are purged.",
            messages.SUCCESS if changed else messages.WARNING,
        )

    @admin.action(description="Serve the selected images at their public URL again")
    def enable_serving(self, request: HttpRequest, queryset: QuerySet[UploadedMedia]) -> None:
        changed = list(queryset.filter(serving_disabled_at__isnull=False))
        for media in changed:
            media.serving_disabled_at = None
            media.save(update_fields=["serving_disabled_at"])
            self.log_change(request, media, "Resumed serving at the public URL.")
            logger.info("uploaded_media.serving_enabled", media_id=str(media.id), team_id=media.team_id)
        self.message_user(
            request,
            f"Resumed serving {len(changed)} image(s).",
            messages.SUCCESS if changed else messages.WARNING,
        )
