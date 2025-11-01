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
    request_serializer: type[serializers.Serializer] | None = None,
    *,
    responses: dict[int, Response] | None = None,
    summary: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    deprecated: bool = False,
    strict_request_validation: bool = True,
    strict_response_validation: bool = False,
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
            if request_serializer is not None:
                serializer = request_serializer(data=request.data)
                req_validation_result = serializer.is_valid(raise_exception=strict_request_validation)

                if not req_validation_result and settings.DEBUG:
                    logger.warning(
                        "Request data does not match declared serializer in @validated_request decorator. Please update the provided API schema to ensure API docs remain up to date",
                        view_func=view_func.__name__,
                        serializer_class=request_serializer.__name__,
                        validation_errors=serializer.errors,
                    )

                request.validated_data = serializer.validated_data

            result = view_func(self, request, *args, **kwargs)

            # Step 1: Check if responses are defined at all
            if not responses:
                if strict_response_validation:
                    raise serializers.ValidationError(
                        "Responses parameter is required when strict_response_validation is True"
                    )
                elif settings.DEBUG:
                    logger.warning(
                        "No responses parameter defined in @validated_request decorator. Please update the provided API schema to ensure API docs remain up to date",
                        view_func=view_func.__name__,
                    )
                return result

            # Step 2: Must be a Response object
            if not isinstance(result, Response):
                if strict_response_validation:
                    raise serializers.ValidationError(
                        f"View must return a Response object when using @validated_request with response serializers. Got {type(result).__name__}"
                    )
                elif settings.DEBUG:
                    logger.warning(
                        "View must return a Response object when using @validated_request with response serializers. Please update the provided API schema to ensure API docs remain up to date",
                        view_func=view_func.__name__,
                        result_type=type(result).__name__,
                    )
                return result

            status_code = result.status_code
            data = result.data

            # Step 3: Check if status code is in defined responses
            if status_code not in responses:
                if strict_response_validation:
                    raise serializers.ValidationError(
                        f"Response status code {status_code} not declared in responses parameter of the @validated_request decorator. "
                        f"Declared status codes: {sorted(responses.keys())}"
                    )
                elif settings.DEBUG:
                    logger.warning(
                        "Response status code not declared in responses parameter of the @validated_request decorator. Please update the provided API schema to ensure API docs remain up to date",
                        view_func=view_func.__name__,
                        status_code=status_code,
                        declared_status_codes=sorted(responses.keys()),
                    )
                return result

            # Step 4: Check if there's a serializer (or if it's declared as None)
            response_config = responses[status_code]
            is_none = response_config is None or (
                hasattr(response_config, "response") and response_config.response is None
            )

            if is_none:
                # Declared as None - validate no body
                if data not in (None, {}, []):
                    if strict_response_validation:
                        raise serializers.ValidationError(
                            f"Response status code {status_code} is declared with no body, but response contains data"
                        )
                    elif settings.DEBUG:
                        logger.warning(
                            f"Response status code {status_code} is declared with no body, but response contains data. Please update the provided API schema to ensure API docs remain up to date",
                            view_func=view_func.__name__,
                            status_code=status_code,
                        )
                return result

            # Step 5: Validate response matches serializer
            serializer_class = response_config.response
            context = getattr(self, "get_serializer_context", lambda: {})()
            serialized = serializer_class(data=data, context=context)

            if not serialized.is_valid(raise_exception=strict_response_validation):
                if settings.DEBUG:
                    logger.warning(
                        f"Response data does not match declared serializer for status code {status_code} declared in responses parameter of the @validated_request decorator. Please update the provided API schema to ensure API docs remain up to date",
                        view_func=view_func.__name__,
                        status_code=status_code,
                        serializer_class=serializer_class.__name__,
                        validation_errors=serialized.errors,
                    )
                return result

            return result

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
