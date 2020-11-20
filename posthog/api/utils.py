from rest_framework.pagination import CursorPagination as BaseCursorPagination
from rest_framework_extensions.routers import ExtendedDefaultRouter


class CursorPagination(BaseCursorPagination):
    ordering = "-created_at"
    page_size = 100


class DefaultRouterPlusPlus(ExtendedDefaultRouter):
    """DefaultRouter with optional trailing slash and drf-extensions nesting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = r"/?"
