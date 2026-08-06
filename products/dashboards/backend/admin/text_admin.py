from django.contrib import admin

from products.dashboards.backend.models.dashboard_tile import Text


@admin.register(Text)
class TextAdmin(admin.ModelAdmin):
    autocomplete_fields = ("created_by", "last_modified_by", "team")
    search_fields = ("id", "body", "team__name", "team__organization__name")
