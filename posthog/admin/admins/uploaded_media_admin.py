from django.contrib import admin, messages
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

import structlog

from posthog.admin.paginators.no_count_paginator import NoCountPaginator
from posthog.models import UploadedMedia

logger = structlog.get_logger(__name__)

# Takedowns cover a handful of images. The cap stops a "select all" from changing every row in the
# table in one request.
MAX_IMAGES_PER_ACTION = 50


@admin.register(UploadedMedia)
class UploadedMediaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "file_name",
        "team_link",
        "purpose",
        "created_at",
        "archived_at",
        "serving_disabled_at",
        "has_stored_file",
    )
    # The table holds every dashboard image and toolbar screenshot, so look rows up by exact id
    # (the UUID in the public URL) or team id, and never count or sort the whole table.
    search_fields = ("id__exact", "team__id__exact")
    show_full_result_count = False
    paginator = NoCountPaginator
    # UUIDT ids sort by creation time, so this ordering uses the primary key index. created_at has none.
    ordering = ("-id",)
    actions = ["disable_serving", "enable_serving", "delete_stored_file"]
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

    def _bounded(self, request: HttpRequest, queryset: QuerySet[UploadedMedia]) -> list[UploadedMedia] | None:
        media = list(queryset[: MAX_IMAGES_PER_ACTION + 1])
        if len(media) > MAX_IMAGES_PER_ACTION:
            self.message_user(
                request,
                f"Select at most {MAX_IMAGES_PER_ACTION} images at a time. Nothing was changed.",
                messages.ERROR,
            )
            return None
        return media

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

    @admin.display(description="Stored file", boolean=True)
    def has_stored_file(self, obj: UploadedMedia) -> bool:
        return obj.media_location is not None

    def _report_urls_to_purge(self, request: HttpRequest, media: list[UploadedMedia]) -> None:
        # Earlier successful responses carry a years-long immutable cache header, so a CDN in front
        # of the media host keeps serving them until someone purges these URLs there.
        if not media:
            return
        urls = ", ".join(item.get_absolute_url() for item in media)
        self.message_user(
            request,
            f"Purge these URLs in the CDN so cached copies stop loading: {urls}. "
            "Copies already saved by browsers or email clients can't be recalled.",
            messages.WARNING,
        )

    @admin.action(description="Stop serving the selected images at their public URL")
    def disable_serving(self, request: HttpRequest, queryset: QuerySet[UploadedMedia]) -> None:
        media = self._bounded(request, queryset)
        if media is None:
            return
        for item in media:
            if item.stop_serving():
                self.log_change(request, item, "Stopped serving at the public URL.")
                logger.info("uploaded_media.serving_disabled", media_id=str(item.id), team_id=item.team_id)
        self.message_user(request, f"Stopped serving {len(media)} image(s).", messages.SUCCESS)
        self._report_urls_to_purge(request, media)

    @admin.action(description="Serve the selected images at their public URL again")
    def enable_serving(self, request: HttpRequest, queryset: QuerySet[UploadedMedia]) -> None:
        media = self._bounded(request, queryset)
        if media is None:
            return
        changed = [item for item in media if item.serving_disabled_at is not None and item.media_location is not None]
        for item in changed:
            item.serving_disabled_at = None
            item.save(update_fields=["serving_disabled_at"])
            self.log_change(request, item, "Resumed serving at the public URL.")
            logger.info("uploaded_media.serving_enabled", media_id=str(item.id), team_id=item.team_id)
        self.message_user(
            request,
            f"Resumed serving {len(changed)} image(s). Images whose stored file was deleted stay unavailable.",
            messages.SUCCESS if changed else messages.WARNING,
        )

    @admin.action(description="Delete the stored file of the selected images permanently")
    def delete_stored_file(self, request: HttpRequest, queryset: QuerySet[UploadedMedia]) -> None:
        media = self._bounded(request, queryset)
        if media is None:
            return
        # Stopping serving first is the confirmation step, because this delete can't be undone.
        stopped = [item for item in media if item.serving_disabled_at is not None]
        skipped = len(media) - len(stopped)
        deleted = UploadedMedia.delete_stored_files(stopped)
        failed = len(stopped) - len(deleted)
        for item in deleted:
            self.log_change(request, item, "Deleted the stored file permanently.")
            logger.info("uploaded_media.stored_file_deleted", media_id=str(item.id), team_id=item.team_id)

        if deleted:
            self.message_user(request, f"Deleted the stored file of {len(deleted)} image(s).", messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} image(s) that are still served. Stop serving them first, then delete.",
                messages.WARNING,
            )
        if failed:
            self.message_user(
                request,
                f"Could not delete the stored file of {failed} image(s). Their public URL stays off. Try again.",
                messages.ERROR,
            )
        self._report_urls_to_purge(request, deleted)
