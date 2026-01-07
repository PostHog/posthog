"""Test to reproduce the handle_exception returning None bug"""

from unittest.mock import patch

from django.test import RequestFactory

from rest_framework import exceptions, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from ee.api.vercel.test.base import VercelTestBase
from ee.api.vercel.vercel_error_mixin import VercelErrorResponseMixin


class _TestViewSet(VercelErrorResponseMixin, viewsets.GenericViewSet):
    authentication_classes = []
    permission_classes = []

    def test_action(self, request: Request) -> Response:
        raise ValueError("This is a non-DRF exception")


class TestVercelErrorMixinBug(VercelTestBase):
    def test_handle_exception_with_non_drf_exception_returns_response(self):
        factory = RequestFactory()
        django_request = factory.put("/test/")

        viewset = _TestViewSet()
        viewset.action = "test_action"
        viewset.format_kwarg = None
        viewset.request = Request(django_request)

        exc = ValueError("Non-DRF exception")
        response = viewset.handle_exception(exc)

        assert response is not None
        assert isinstance(response, Response)
        assert response.status_code == 500
        assert response.data["error"]["code"] == "internal_error"
        assert response.data["error"]["message"] == "An internal error occurred. Please try again."
        assert "Non-DRF exception" not in response.data["error"]["message"]

    def test_handle_exception_with_drf_exception_returns_response(self):
        factory = RequestFactory()
        django_request = factory.put("/test/")

        viewset = _TestViewSet()
        viewset.action = "test_action"
        viewset.format_kwarg = None
        viewset.request = Request(django_request)

        exc = exceptions.ValidationError("DRF exception")
        response = viewset.handle_exception(exc)

        assert response is not None
        assert isinstance(response, Response)
        assert response.status_code == 400

    def test_viewset_dispatch_with_non_drf_exception(self):
        factory = RequestFactory()
        django_request = factory.put("/test/")

        viewset = _TestViewSet.as_view({"put": "test_action"})

        with patch.object(_TestViewSet, "test_action", side_effect=ValueError("Test error")):
            response = viewset(django_request)

            assert response is not None
            assert response.status_code == 500
            assert response.data["error"]["code"] == "internal_error"
            assert response.data["error"]["message"] == "An internal error occurred. Please try again."
            assert "Test error" not in response.data["error"]["message"]
