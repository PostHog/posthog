# Test cases for no-hand-set-paginator-state.
# ruff: noqa
from rest_framework.pagination import LimitOffsetPagination

from posthog.api.pagination import BoundedLimitOffsetPagination


def facade_list(self, request, page):
    paginator = self.paginator
    # ruleid: no-hand-set-paginator-state
    paginator.count = page.count
    # ruleid: no-hand-set-paginator-state
    paginator.limit = paginator.get_limit(request)
    # ruleid: no-hand-set-paginator-state
    paginator.offset = paginator.get_offset(request)
    # ruleid: no-hand-set-paginator-state
    paginator.request = request
    return paginator.get_paginated_response(page.results)


def view_list(self, request, rows):
    # ruleid: no-hand-set-paginator-state
    self.paginator.page = rows
    # ruleid: no-hand-set-paginator-state
    self.paginator.has_next = False


def schema_check(view):
    pagination = view.pagination_class()
    # ruleid: no-hand-set-paginator-state
    pagination.has_previous = False
    run_paginator = view.paginator
    # ruleid: no-hand-set-paginator-state
    run_paginator.ordering = ("-created_at",)


class ReportListPagination(BoundedLimitOffsetPagination):
    def paginate_queryset(self, queryset, request, view=None):
        # ok: no-hand-set-paginator-state
        self.limit = self.get_limit(request)
        # ok: no-hand-set-paginator-state
        self.request = request
        return list(queryset[: self.limit])


class BoundedListPagination(LimitOffsetPagination):
    # ok: no-hand-set-paginator-state
    default_limit = 100
    # ok: no-hand-set-paginator-state
    max_limit = 500


def precounted_list(self, rows, total):
    # ok: no-hand-set-paginator-state
    self.paginator.set_count(total)
    page = self.paginate_queryset(rows)
    return self.get_paginated_response(page)


class ExportRunner:
    def __init__(self, request, limit):
        # ok: no-hand-set-paginator-state
        self.request = request
        # ok: no-hand-set-paginator-state
        self.limit = limit


def summary(stats):
    # ok: no-hand-set-paginator-state
    stats.count = 0
    # ok: no-hand-set-paginator-state
    paginator_options = {"limit": 10}
