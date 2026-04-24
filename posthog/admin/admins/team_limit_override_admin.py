from django.contrib import admin


class TeamLimitOverrideAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "team",
        "limit_key",
        "value",
        "granted_by",
        "granted_at",
    )
    list_filter = ("limit_key",)
    search_fields = (
        "team__name",
        "team__id",
        "team__organization__name",
        "team__organization__id",
        "limit_key",
        "reason",
    )
    autocomplete_fields = ("team", "granted_by")
    readonly_fields = ("granted_at",)
    ordering = ("-granted_at",)
