from django.contrib import admin


class PluginAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "organization_id", "is_global")
    list_display_links = ("id", "name")
    list_filter = ("plugin_type", "is_global")
    autocomplete_fields = ("organization",)
    search_fields = ("name",)
    ordering = ("-created_at",)
