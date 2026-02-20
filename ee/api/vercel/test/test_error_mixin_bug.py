from unittest.mock import patch

from django.test import RequestFactory

from parameterized import parameterized
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


class TestVercelErrorMixin(VercelTestBase):
    def _make_viewset(self) -> _TestViewSet:
        factory = RequestFactory()
        django_request = factory.put("/test/")
        viewset = _TestViewSet()
        viewset.action = "test_action"
        viewset.format_kwarg = None
        viewset.request = Request(django_request)
        return viewset

    def test_non_drf_exception_returns_vercel_error_format(self):
        viewset = self._make_viewset()
        exc = ValueError("Non-DRF exception")
        response = viewset.handle_exception(exc)

        self.assertIsNotNone(response)
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data["error"]["code"], "request_failed")
        self.assertNotIn("Non-DRF exception", response.data["error"]["message"])

    def test_non_drf_exception_calls_capture_exception(self):
        viewset = self._make_viewset()
        exc = ValueError("Non-DRF exception")
        with patch("posthog.exceptions.capture_exception") as mock_capture:
            viewset.handle_exception(exc)
            mock_capture.assert_called_once()

    def test_drf_validation_error_returns_vercel_error_format(self):
        viewset = self._make_viewset()
        exc = exceptions.ValidationError("DRF exception")
        response = viewset.handle_exception(exc)

        self.assertIsNotNone(response)
        self.assertIsInstance(response, Response)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["code"], "request_failed")
        self.assertIn("DRF exception", response.data["error"]["message"])

    def test_drf_validation_error_with_list_detail(self):
        viewset = self._make_viewset()
        exc = exceptions.ValidationError(["error one", "error two"])
        response = viewset.handle_exception(exc)

        self.assertEqual(response.status_code, 400)
        self.assertIn("error one", response.data["error"]["message"])
        self.assertIn("error two", response.data["error"]["message"])

    def test_drf_validation_error_with_dict_detail(self):
        viewset = self._make_viewset()
        exc = exceptions.ValidationError({"field": "is required"})
        response = viewset.handle_exception(exc)

        self.assertEqual(response.status_code, 400)
        self.assertIn("field", response.data["error"]["message"])

    def test_drf_validation_error_does_not_call_capture_exception(self):
        viewset = self._make_viewset()
        exc = exceptions.ValidationError("DRF exception")
        with patch("posthog.exceptions.capture_exception") as mock_capture:
            viewset.handle_exception(exc)
            mock_capture.assert_not_called()

    def test_drf_not_found_returns_vercel_error_format(self):
        viewset = self._make_viewset()
        exc = exceptions.NotFound("Not found")
        response = viewset.handle_exception(exc)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["error"]["code"], "request_failed")

    def test_dispatch_with_non_drf_exception(self):
        factory = RequestFactory()
        django_request = factory.put("/test/")
        viewset = _TestViewSet.as_view({"put": "test_action"})

        with patch.object(_TestViewSet, "test_action", side_effect=ValueError("Test error")):
            response = viewset(django_request)

            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 500)
            self.assertEqual(response.data["error"]["code"], "request_failed")
            self.assertNotIn("Test error", response.data["error"]["message"])


class TestVercelSSOEndpointMissingCredentials(VercelTestBase):
    """Integration test: hits the actual /login/vercel/ URL through Django's full request stack.

    The RuntimeError from _validate_client_credentials is caught by authenticate_sso's
    catch-all, which calls capture_exception and re-raises as AuthenticationFailed (401).
    The response is still formatted in Vercel's error schema by VercelErrorResponseMixin.
    """

    @parameterized.expand(
        [
            ("missing_secret", "test_id", None, "VERCEL_CLIENT_INTEGRATION_SECRET"),
            ("missing_id", None, None, "VERCEL_CLIENT_INTEGRATION_ID"),
        ]
    )
    @patch("ee.vercel.integration.capture_exception")
    def test_missing_credential_returns_vercel_error_and_captures(
        self, _name, client_id, client_secret, expected_setting_name, mock_capture
    ):
        with self.settings(VERCEL_CLIENT_INTEGRATION_ID=client_id, VERCEL_CLIENT_INTEGRATION_SECRET=client_secret):
            response = self.client.get("/login/vercel/", {"mode": "sso", "code": "fake", "state": "fake"})

        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data["error"]["code"], "request_failed")
        self.assertNotIn(expected_setting_name, data["error"]["message"])
        mock_capture.assert_called_once()
        captured_exc = mock_capture.call_args[0][0]
        self.assertIsInstance(captured_exc, RuntimeError)
        self.assertIn(expected_setting_name, str(captured_exc))
