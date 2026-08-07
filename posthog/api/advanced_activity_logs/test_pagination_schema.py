from django.test import SimpleTestCase

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.advanced_activity_logs.viewset import ActivityLogPagination


class TestActivityLogPaginationSchema(SimpleTestCase):
    def test_count_is_not_required_because_cursor_responses_omit_it(self):
        schema = ActivityLogPagination().get_paginated_response_schema({"type": "array"})

        assert "count" not in schema["required"]
        assert "results" in schema["required"]
        assert "count" in schema["properties"]

    def test_cursor_response_body_has_no_count(self):
        pagination = ActivityLogPagination()
        pagination.request = Request(APIRequestFactory().get("/"))
        pagination.cursor_pagination.page = []
        pagination.cursor_pagination.has_next = False
        pagination.cursor_pagination.has_previous = False

        assert "count" not in pagination.get_paginated_response([]).data
