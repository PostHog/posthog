# Test cases for no-unbounded-drf-paginator.
# ruff: noqa
from rest_framework import pagination
from rest_framework.pagination import CursorPagination, LimitOffsetPagination, PageNumberPagination

from posthog.api.pagination import BoundedLimitOffsetPagination, BoundedPageNumberPagination, StableCursorPagination


# ruleid: no-unbounded-drf-paginator
class ChannelListPagination(LimitOffsetPagination):
    default_limit = None


# ruleid: no-unbounded-drf-paginator
class ReportPagination(PageNumberPagination):
    page_size = 100


# ruleid: no-unbounded-drf-paginator
class EventCursorPagination(CursorPagination):
    ordering = "-created_at"


# ruleid: no-unbounded-drf-paginator
class QualifiedPagination(pagination.LimitOffsetPagination):
    default_limit = 50


# ruleid: no-unbounded-drf-paginator
class MixinPagination(SomeMixin, pagination.PageNumberPagination):
    page_size = 20


class UncappedPagination(BoundedLimitOffsetPagination):
    # ruleid: no-unbounded-drf-paginator
    max_limit = None


# ok: no-unbounded-drf-paginator
class OptInPagination(BoundedLimitOffsetPagination):
    default_limit = None


# ok: no-unbounded-drf-paginator
class NumberedPagination(BoundedPageNumberPagination):
    page_size = 100


# ok: no-unbounded-drf-paginator
class ActivityCursorPagination(StableCursorPagination):
    ordering = "-created_at"


class LargerPagination(BoundedLimitOffsetPagination):
    # ok: no-unbounded-drf-paginator
    max_limit = 5000


class ExportOptions:
    # ok: no-unbounded-drf-paginator
    max_limit = None
