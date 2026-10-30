from django.test import SimpleTestCase

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.advanced_activity_logs.viewset import ActivityLogPagination
from posthog.models.activity_logging.activity_log import ActivityLog


class TestActivityLogPaginationSchema(SimpleTestCase):
    def test_count_is_required_because_both_modes_return_it(self):
        schema = ActivityLogPagination().get_paginated_response_schema({"type": "array"})

        assert "count" in schema["required"]
        assert "results" in schema["required"]

    def test_cursor_response_body_has_count(self):
        pagination = ActivityLogPagination()
        pagination.request = Request(APIRequestFactory().get("/"))
        pagination.counted_rows = ActivityLog.objects.none()
        pagination.page = []
        pagination.has_next = False
        pagination.has_previous = False

        assert pagination.get_paginated_response([]).data["count"] == 0
