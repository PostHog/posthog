from rest_framework.pagination import CursorPagination as RestCursorPagination


class CursorPagination(RestCursorPagination):
    ordering = "-created_at"
    page_size = 100
