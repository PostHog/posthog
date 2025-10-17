from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from drf_spectacular.utils import extend_schema
from pydantic import BaseModel, ValidationError
from rest_framework import (
    serializers,
    status as http_status,
)
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception

T = TypeVar("T", bound=BaseModel)


# Generic Pydantic model mixin for validating the response data
class PydanticModelMixin:
    def get_model(self, data: dict, model: type[T]) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            capture_exception(exc)
            raise ParseError("JSON parse error - {}".format(str(exc)))


def validated_request(request_serializer: type[serializers.Serializer], **extend_schema_kwargs) -> Callable:
    """
    Takes req/res serializers and validates against them.

    Usage:
        @validated_request(
            request_serializer=RequestSerializer,
            responses={
                200: OpenApiResponse(response=SuccessResponseSerializer, ...),
                400: OpenApiResponse(response=InvalidRequestResponseSerializer, ...),
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
        # Extract serializers from responses dict in extend_schema_kwargs
        response_serializers = {}
        responses_config = extend_schema_kwargs.get("responses", {})

        for status_code, response_config in responses_config.items():
            if hasattr(response_config, "response"):
                response_serializers[status_code] = response_config.response

        @extend_schema(request=request_serializer, **extend_schema_kwargs)
        @wraps(view_func)
        def wrapper(self, request: Request, *args, **kwargs) -> Response:
            serializer = request_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            request.validated_data = serializer.validated_data

            result = view_func(self, request, *args, **kwargs)

            if isinstance(result, Response):
                return result

            if not response_serializers:
                return result

            status_code = http_status.HTTP_200_OK
            data = result

            if isinstance(result, tuple) and len(result) == 2:
                data, status_code = result

            serializer_class = response_serializers.get(status_code)
            if not serializer_class:
                return Response(data, status=status_code)

            context = getattr(self, "get_serializer_context", lambda: {})()
            serialized = serializer_class(data, context=context)
            serialized.is_valid(raise_exception=True)
            return Response(serialized.data, status=status_code)

        return wrapper

    return decorator
