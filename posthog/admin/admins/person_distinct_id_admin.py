from django.contrib import admin


class PersonDistinctIdAdmin(admin.ModelAdmin):
    list_display = ("id", "team", "distinct_id", "version")
    list_filter = ("version",)
    search_fields = ("id", "distinct_id")
