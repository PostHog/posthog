from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from posthog.openapi_validation_middleware import OpenAPISchemaValidationMiddleware


class TestOpenAPISchemaValidationMiddleware(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(OPENAPI_E2E_VALIDATION_ENABLED=False)
    def test_middleware_disabled_when_flag_is_off(self):
        with self.assertRaises(MiddlewareNotUsed):
            OpenAPISchemaValidationMiddleware(lambda _: HttpResponse("ok"))

    @override_settings(
        OPENAPI_E2E_VALIDATION_ENABLED=True,
        OPENAPI_E2E_VALIDATION_HEADER="X-PostHog-OpenAPI-Validate",
        OPENAPI_E2E_VALIDATION_HEADER_VALUE="1",
    )
    def test_skips_validation_without_header(self):
        middleware = OpenAPISchemaValidationMiddleware(lambda _: HttpResponse("ok"))

        request = self.factory.get("/api/projects/")
        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse("X-PostHog-OpenAPI-Validation-Errors" in response)

    @override_settings(
        OPENAPI_E2E_VALIDATION_ENABLED=True,
        OPENAPI_E2E_VALIDATION_HEADER="X-PostHog-OpenAPI-Validate",
        OPENAPI_E2E_VALIDATION_HEADER_VALUE="1",
    )
    def test_reports_request_and_response_errors_without_blocking(self):
        middleware = OpenAPISchemaValidationMiddleware(lambda _: HttpResponse("ok"))
        middleware._collect_request_errors = lambda _: ["request error"]  # type: ignore[method-assign]
        middleware._collect_response_errors = lambda _request, _response: ["response error"]  # type: ignore[method-assign]

        request = self.factory.get("/api/projects/", HTTP_X_POSTHOG_OPENAPI_VALIDATE="1")
        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-PostHog-OpenAPI-Validation-Errors"], "2")
