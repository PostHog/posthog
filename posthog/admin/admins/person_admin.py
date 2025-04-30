from django.contrib import admin

from posthog.admin.paginators.no_count_paginator import NoCountPaginator


class PersonAdmin(admin.ModelAdmin):
    show_full_result_count = False  # prevent count() queries to show the no of filtered results
    paginator = NoCountPaginator  # prevent count() queries and return a fix page count instead
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
