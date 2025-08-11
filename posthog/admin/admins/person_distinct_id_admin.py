from django.contrib import admin

from posthog.admin.paginators.no_count_paginator import NoCountPaginator


class PersonDistinctIdAdmin(admin.ModelAdmin):
    show_full_result_count = False  # prevent count() queries to show the no of filtered results
    paginator = NoCountPaginator  # prevent count() queries and return a fix page count instead
    list_display = ("id", "team", "distinct_id", "version")
    search_fields = ("id", "distinct_id")
    readonly_fields = ("person",)
    autocomplete_fields = ("team",)
