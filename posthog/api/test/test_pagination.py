from urllib.parse import parse_qs, urlparse

from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.pagination import FacadeCursorPagination, StableCursorPagination, select_cursor_page
from posthog.paging import CursorPageRequest, Page

from products.annotations.backend.models.annotation import Annotation


class _AnnotationIdSerializer(serializers.Serializer):
    id = serializers.IntegerField()


class _AnnotationView(GenericAPIView):
    serializer_class = _AnnotationIdSerializer


class _ByDateMarker(FacadeCursorPagination):
    ordering = "-date_marker"
    page_size = 2


class _ByDateMarkerQueryset(StableCursorPagination):
    ordering = "-date_marker"
    page_size = 2


class TestCursorPagination(BaseTest):
    def _page(self, mode: str, cursor: str | None) -> dict:
        request = Request(APIRequestFactory().get("/annotations/", {"cursor": cursor} if cursor else {}))
        view = _AnnotationView()
        view.request = request
        view.format_kwarg = None
        queryset = Annotation.objects.filter(team=self.team)

        if mode == "facade":

            def fetch(page: CursorPageRequest) -> Page[Annotation]:
                return select_cursor_page(queryset, page, ordering_fields={"date_marker"})

            return _ByDateMarker().get_paginated_facade_response(request, view, fetch).data

        paginator = _ByDateMarkerQueryset()
        rows = paginator.paginate_queryset(queryset, request, view)
        return paginator.get_paginated_response(_AnnotationIdSerializer(rows, many=True).data).data

    @parameterized.expand([("queryset",), ("facade",)])
    def test_pages_through_rows_that_share_the_cursor_field_once(self, mode: str) -> None:
        shared_marker = Annotation.objects.create(team=self.team, content="first").date_marker
        for content in ["second", "third", "fourth", "fifth"]:
            Annotation.objects.create(team=self.team, content=content, date_marker=shared_marker)
        expected_ids = set(Annotation.objects.filter(team=self.team).values_list("id", flat=True))

        seen_ids: list[int] = []
        cursor = None
        while True:
            page = self._page(mode, cursor)
            assert page["count"] == 5
            seen_ids.extend(row["id"] for row in page["results"])
            if page["next"] is None:
                break
            cursor = parse_qs(urlparse(page["next"]).query)["cursor"][0]

        assert sorted(seen_ids) == sorted(expected_ids)
