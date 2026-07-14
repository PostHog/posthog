from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.pagination import MAX_PAGINATION_VALUE, BoundedLimitOffsetPagination

factory = APIRequestFactory()


class TestBoundedLimitOffsetPagination(SimpleTestCase):
    def _request(self, query: dict) -> Request:
        return Request(factory.get("/", query))

    @parameterized.expand(["limit", "offset"])
    def test_value_past_bigint_is_rejected(self, param: str):
        paginator = BoundedLimitOffsetPagination()
        getter = paginator.get_limit if param == "limit" else paginator.get_offset

        with self.assertRaises(ValidationError):
            getter(self._request({param: str(MAX_PAGINATION_VALUE + 1)}))

    def test_bigint_boundary_is_allowed(self):
        paginator = BoundedLimitOffsetPagination()
        request = self._request({"limit": str(MAX_PAGINATION_VALUE), "offset": str(MAX_PAGINATION_VALUE)})

        assert paginator.get_limit(request) == MAX_PAGINATION_VALUE
        assert paginator.get_offset(request) == MAX_PAGINATION_VALUE

    def test_non_integer_input_defers_to_drf_defaults(self):
        paginator = BoundedLimitOffsetPagination()
        request = self._request({"limit": "not-a-number", "offset": "not-a-number"})

        assert paginator.get_limit(request) == paginator.default_limit
        assert paginator.get_offset(request) == 0
