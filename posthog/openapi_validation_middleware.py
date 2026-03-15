from __future__ import annotations

from collections.abc import Callable
from functools import cached_property
from typing import Any

import structlog
from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpRequest, HttpResponse

logger = structlog.get_logger(__name__)


class OpenAPISchemaValidationMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        if not settings.OPENAPI_E2E_VALIDATION_ENABLED:
            raise MiddlewareNotUsed()
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not self._should_validate(request):
            return self.get_response(request)

        request_errors = self._collect_request_errors(request)
        response = self.get_response(request)
        response_errors = self._collect_response_errors(request, response)

        total_errors = len(request_errors) + len(response_errors)
        response["X-PostHog-OpenAPI-Validation-Errors"] = str(total_errors)
        return response

    def _should_validate(self, request: HttpRequest) -> bool:
        if not request.path.startswith("/api/"):
            return False

        header_name = settings.OPENAPI_E2E_VALIDATION_HEADER
        header_value = settings.OPENAPI_E2E_VALIDATION_HEADER_VALUE
        if not header_name:
            return True

        return request.headers.get(header_name, "") == header_value

    @cached_property
    def _openapi(self) -> Any | None:
        try:
            from drf_spectacular.generators import SchemaGenerator
            from openapi_core import OpenAPI
        except Exception as exc:
            logger.warning("openapi_validation_unavailable", error=str(exc))
            return None

        schema = SchemaGenerator().get_schema(request=None, public=True)
        if schema is None:
            logger.warning("openapi_validation_schema_generation_failed")
            return None

        return OpenAPI.from_dict(schema)

    def _collect_request_errors(self, request: HttpRequest) -> list[str]:
        if self._openapi is None:
            return []

        try:
            from openapi_core.contrib.django.requests import DjangoOpenAPIRequest

            self._openapi.validate_request(DjangoOpenAPIRequest(request))
            return []
        except Exception as exc:
            self._log_validation_error(request=request, phase="request", error=str(exc))
            return [str(exc)]

    def _collect_response_errors(self, request: HttpRequest, response: HttpResponse) -> list[str]:
        if self._openapi is None:
            return []

        try:
            from openapi_core.contrib.django.requests import DjangoOpenAPIRequest
            from openapi_core.contrib.django.responses import DjangoOpenAPIResponse

            self._openapi.validate_response(DjangoOpenAPIRequest(request), DjangoOpenAPIResponse(response))
            return []
        except Exception as exc:
            self._log_validation_error(
                request=request,
                phase="response",
                error=str(exc),
                status_code=response.status_code,
            )
            return [str(exc)]

    def _log_validation_error(
        self,
        *,
        request: HttpRequest,
        phase: str,
        error: str,
        status_code: int | None = None,
    ) -> None:
        logger.warning(
            "openapi_validation_error",
            phase=phase,
            method=request.method,
            path=request.path,
            status_code=status_code,
            error=error,
        )

