from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from posthog.models import ShortLink


class ShortLinkAdmin(admin.ModelAdmin):
    list_display = ("key", "destination_url_display", "team_link", "created_at", "updated_at", "expiration_date")
    list_filter = ("team", "created_at", "updated_at", "expiration_date")
    search_fields = ("key", "destination_url", "team__name")
    readonly_fields = ("key", "hashed_key", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("key", "hashed_key", "destination_url", "team")}),
        ("Dates", {"fields": ("created_at", "updated_at", "expiration_date")}),
    )

    def destination_url_display(self, obj: ShortLink):
        return format_html('<a href="{}" target="_blank">{}</a>', obj.destination_url, obj.destination_url)

    destination_url_display.short_description = "Destination URL"

    def team_link(self, obj: ShortLink):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[obj.team.pk]),
            obj.team.name,
        )

    team_link.short_description = "Team"


# Register with admin site
admin.site.register(ShortLink, ShortLinkAdmin)
