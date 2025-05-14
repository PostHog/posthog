from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from posthog.models import Link


class LinkAdmin(admin.ModelAdmin):
    list_display = ("id", "destination_display", "team_link", "created_at", "updated_at")
    list_filter = ("team", "created_at", "updated_at")
    search_fields = ("id", "destination", "team__name")
    readonly_fields = ("id", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("id", "destination", "origin_domain", "origin_key", "team")}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
        ("Additional Info", {"fields": ("description", "tags", "comments")}),
    )

    def destination_display(self, obj: Link):
        return format_html('<a href="{}" target="_blank">{}</a>', obj.destination, obj.destination)

    destination_display.short_description = "Destination"

    def team_link(self, obj: Link):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[obj.team.pk]),
            obj.team.name,
        )

    team_link.short_description = "Team"


# Register with admin site
admin.site.register(Link, LinkAdmin)
