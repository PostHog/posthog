from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from django.conf import settings

import structlog
from drf_spectacular.utils import extend_schema
from pydantic import BaseModel, ValidationError
from rest_framework import serializers
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.file_system.file_system_logging import log_api_file_system_view
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


# Generic Pydantic model mixin for validating the response data
class PydanticModelMixin:
    def get_model(self, data: dict, model: type[T]) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            capture_exception(exc)
            raise ParseError("JSON parse error - {}".format(str(exc)))


def validated_request(
    request_serializer: type[serializers.Serializer],
    *,
    responses: dict[int, Response] | None = None,
    summary: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    deprecated: bool = False,
    **extend_schema_kwargs,
) -> Callable:
    """
    Takes req/res serializers and validates against them.

    Usage:
        @validated_request(
            request_serializer=RequestSerializer,
            responses={
                200: Response(response=SuccessResponseSerializer, ...),
                400: Response(response=InvalidRequestResponseSerializer, ...),
            },
            summary="Do something"
        )
        def my_action(self, request, **kwargs):
            request_data = request.validated_data.get("next_stage_id")

            if not request_data:
                return Response(
                    ErrorResponseSerializer({"error": "Invalid request"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(SuccessResponseSerializer(request_data, context=self.get_serializer_context()).data)
    """

    def decorator(view_func: Callable) -> Callable:
        # Extract serializers from responses dict
        response_serializers: dict[int, type[serializers.Serializer]] = {}
        if responses:
            for status_code, response_config in responses.items():
                if hasattr(response_config, "response") and response_config.response is not None:
                    response_serializers[status_code] = response_config.response

        @extend_schema(
            request=request_serializer,
            responses=responses,
            summary=summary,
            description=description,
            tags=tags,
            deprecated=deprecated,
            **extend_schema_kwargs,
        )
        @wraps(view_func)
        def wrapper(self, request: Request, *args, **kwargs) -> Response:
            serializer = request_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            request.validated_data = serializer.validated_data

            result = view_func(self, request, *args, **kwargs)

            if not response_serializers:
                return result

            # Step 1: Fetch HTTP status code (must be a Response object)
            if not isinstance(result, Response):
                # Warn during development if the view does not return a Response object
                if settings.DEBUG:
                    logger.warning(
                        "View must return a Response object when using @validated_request with response serializers",
                        view_func=view_func.__name__,
                        result_type=type(result).__name__,
                    )
                return result

            status_code = result.status_code
            data = result.data

            # Step 2: Check if status code is in defined response codes
            serializer_class = response_serializers.get(status_code)

            # Warn during development if the status code is not declared in the responses parameter
            if not serializer_class:
                if settings.DEBUG:
                    logger.warning(
                        "Response status code not declared in responses parameter of the @validated_request decorator",
                        view_func=view_func.__name__,
                        status_code=status_code,
                        declared_status_codes=sorted(response_serializers.keys()),
                    )
                return result

            # Step 3: Validate that response serializes properly
            context = getattr(self, "get_serializer_context", lambda: {})()
            serialized = serializer_class(data=data, context=context)

            # Warn during development if the response data does not match the declared serializer
            if not serialized.is_valid():
                if settings.DEBUG:
                    logger.warning(
                        "Response data does not match declared serializer for status code {status_code} declared in responses parameter of the @validated_request decorator",
                        view_func=view_func.__name__,
                        status_code=status_code,
                        serializer_class=serializer_class.__name__,
                        validation_errors=serialized.errors,
                    )
                return result

            # Step 4: Return the validated response
            return Response(serialized.data, status=status_code)

        return wrapper

    return decorator


class FileSystemViewSetMixin:
    """
    A mixin for tracking file system views. Each GET on the resource logs a new view.
    """

    _file_system_view_instance: Any | None = None

    def get_object(self) -> Any:
        parent = cast(Any, super())
        instance = parent.get_object()
        self._file_system_view_instance = instance
        return instance

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        parent = cast(Any, super())
        response = cast(Response, parent.retrieve(request, *args, **kwargs))
        instance = getattr(self, "_file_system_view_instance", None)
        if instance is not None:
            log_api_file_system_view(request, instance)
        return response
