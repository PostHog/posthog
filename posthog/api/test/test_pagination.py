from base64 import b64encode
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.filters import OrderingFilter
from rest_framework.generics import GenericAPIView
from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.pagination import FacadeCursorPagination, StableCursorPagination
from posthog.models.uploaded_media import UploadedMedia
from posthog.paging import CursorPageRequest, Page
from posthog.queryset_paging import select_cursor_page


class _MediaIdSerializer(serializers.Serializer):
    id = serializers.CharField()


class _MediaView(GenericAPIView):
    serializer_class = _MediaIdSerializer


class _OrderableMediaView(_MediaView):
    filter_backends = [OrderingFilter]
    ordering_fields = ["archived_at", "created_at", "file_name", "purpose", "id"]


class _ByArchivedAt(FacadeCursorPagination):
    ordering = "-archived_at"
    page_size = 2


class _ByArchivedAtQueryset(StableCursorPagination):
    ordering = "-archived_at"
    page_size = 2


class _ByArchivedAtOnDrf(CursorPagination):
    ordering = ("-archived_at", "-id")
    page_size = 2


class TestCursorPagination(BaseTest):
    def _page(self, mode: str, cursor: str | None) -> dict:
        request = Request(APIRequestFactory().get("/media/", {"cursor": cursor} if cursor else {}))
        view = _MediaView()
        view.request = request
        view.format_kwarg = None
        queryset = UploadedMedia.objects.filter(team=self.team)

        if mode == "facade":

            def fetch(page: CursorPageRequest) -> Page[UploadedMedia]:
                return select_cursor_page(queryset, page, ordering_fields={"archived_at"})

            return _ByArchivedAt().get_paginated_facade_response(request, view, fetch).data

        paginator = _ByArchivedAtQueryset()
        rows = paginator.paginate_queryset(queryset, request, view)
        return paginator.get_paginated_response(_MediaIdSerializer(rows, many=True).data).data

    def _drf_page_ids(self, cursor: str) -> list[str]:
        request = Request(APIRequestFactory().get("/media/", {"cursor": cursor}))
        rows = _ByArchivedAtOnDrf().paginate_queryset(UploadedMedia.objects.filter(team=self.team), request)
        assert rows is not None
        return [str(row.id) for row in rows]

    def _cursor(self, link: str) -> str:
        return parse_qs(urlparse(link).query)["cursor"][0]

    @parameterized.expand([("queryset",), ("facade",)])
    def test_pages_both_ways_through_rows_that_share_the_cursor_field(self, mode: str) -> None:
        # A NULL sorts first in descending order, so the walk crosses from NULL rows into a tie group.
        shared_marker = datetime(2024, 1, 1, tzinfo=UTC)
        for marker in [None, None, shared_marker, shared_marker, shared_marker]:
            UploadedMedia.objects.create(team=self.team, file_name="note", archived_at=marker)
        expected_ids = {str(id) for id in UploadedMedia.objects.filter(team=self.team).values_list("id", flat=True)}

        forward_pages: list[list[str]] = []
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
        shared_marker = UploadedMedia.objects.create(team=self.team, file_name="first").archived_at
        for file_name in ["second", "third"]:
            UploadedMedia.objects.create(team=self.team, file_name=file_name, archived_at=shared_marker)
        ids_newest_first = [
            str(id)
            for id in UploadedMedia.objects.filter(team=self.team)
            .order_by("-archived_at", "-id")
            .values_list("id", flat=True)
        ]

        # DRF wrote "skip two rows from the start" as `o=2`; clients store such links.
        page = self._page(mode, b64encode(b"o=2").decode("ascii"))

        assert [row["id"] for row in page["results"]] == ids_newest_first[2:]

    @parameterized.expand([("queryset",), ("facade",)])
    def test_drf_paginator_reads_every_cursor_to_the_same_rows(self, mode: str) -> None:
        newest = datetime(2024, 1, 3, tzinfo=UTC)
        shared = newest - timedelta(days=1)
        for marker in [newest, shared, shared, shared, shared, shared, shared - timedelta(days=1)]:
            UploadedMedia.objects.create(team=self.team, file_name="note", archived_at=marker)

        page = self._page(mode, None)
        cursors: list[str] = []
        while page["next"] is not None:
            cursors.append(self._cursor(page["next"]))
            page = self._page(mode, cursors[-1])
        while page["previous"] is not None:
            cursors.append(self._cursor(page["previous"]))
            page = self._page(mode, cursors[-1])

        assert len(cursors) == 6
        for cursor in cursors:
            assert self._drf_page_ids(cursor) == [row["id"] for row in self._page(mode, cursor)["results"]]

    @parameterized.expand(
        [
            ("negative_offset", b64encode(b"o=-1").decode("ascii")),
            ("deeply_nested_position", b64encode(urlencode({"v": "[" * 100_000}).encode("ascii")).decode("ascii")),
            (
                "value_the_field_cannot_hold",
                b64encode(urlencode({"v": '["not-a-date","1"]'}).encode("ascii")).decode("ascii"),
            ),
            (
                "id_the_field_cannot_hold",
                b64encode(urlencode({"v": '["2024-01-01 00:00:00+00:00","not-a-uuid"]'}).encode("ascii")).decode(
                    "ascii"
                ),
            ),
        ]
    )
    def test_rejects_a_malformed_cursor(self, _name: str, cursor: str) -> None:
        with self.assertRaises(NotFound):
            self._page("queryset", cursor)

    def test_ordering_keeps_one_term_per_field_and_caps_the_field_count(self) -> None:
        def ordering_for(param: str) -> tuple[str, ...]:
            request = Request(APIRequestFactory().get("/media/", {"ordering": param}))
            return _ByArchivedAtQueryset().get_ordering(request, UploadedMedia.objects.all(), _OrderableMediaView())

        assert ordering_for("archived_at,-archived_at,archived_at") == ("archived_at", "id")
        with self.assertRaises(ValidationError):
            ordering_for("archived_at,created_at,file_name,purpose,-id")
