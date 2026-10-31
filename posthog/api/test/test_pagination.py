from base64 import b64encode
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.pagination import FacadeCursorPagination, StableCursorPagination
from posthog.paging import CursorPageRequest, Page
from posthog.queryset_paging import select_cursor_page

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

    def _cursor(self, link: str) -> str:
        return parse_qs(urlparse(link).query)["cursor"][0]

    @parameterized.expand([("queryset",), ("facade",)])
    def test_pages_both_ways_through_rows_that_share_the_cursor_field(self, mode: str) -> None:
        # A NULL sorts first in descending order, so the walk crosses from NULL rows into a tie group.
        shared_marker = datetime(2024, 1, 1, tzinfo=UTC)
        for marker in [None, None, shared_marker, shared_marker, shared_marker]:
            Annotation.objects.create(team=self.team, content="note", date_marker=marker)
        expected_ids = set(Annotation.objects.filter(team=self.team).values_list("id", flat=True))

        forward_pages: list[list[int]] = []
        page = self._page(mode, None)
        while True:
            assert page["count"] == 5
            forward_pages.append([row["id"] for row in page["results"]])
            if page["next"] is None:
                break
            page = self._page(mode, self._cursor(page["next"]))

        assert sorted(id for ids in forward_pages for id in ids) == sorted(expected_ids)

        backward_pages = [[row["id"] for row in page["results"]]]
        while page["previous"] is not None:
            page = self._page(mode, self._cursor(page["previous"]))
            backward_pages.append([row["id"] for row in page["results"]])

        assert backward_pages == list(reversed(forward_pages))

    @parameterized.expand([("queryset",), ("facade",)])
    def test_reads_a_cursor_in_drfs_format(self, mode: str) -> None:
        shared_marker = Annotation.objects.create(team=self.team, content="first").date_marker
        for content in ["second", "third"]:
            Annotation.objects.create(team=self.team, content=content, date_marker=shared_marker)
        ids_newest_first = list(
            Annotation.objects.filter(team=self.team).order_by("-date_marker", "-id").values_list("id", flat=True)
        )

        # DRF wrote "skip two rows from the start" as `o=2`; clients store such links.
        page = self._page(mode, b64encode(b"o=2").decode("ascii"))

        assert [row["id"] for row in page["results"]] == ids_newest_first[2:]
