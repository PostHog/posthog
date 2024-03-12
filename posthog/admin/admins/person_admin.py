from django.contrib import admin


class PersonAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "distinct_ids",
        "created_at",
        "team",
        "is_user",
        "is_identified",
        "version",
    )
    list_filter = ("created_at", "is_identified", "version")
    search_fields = ("id",)
