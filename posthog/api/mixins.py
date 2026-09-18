import copy
from collections.abc import Callable
from functools import wraps
from typing import Any, Generic, TypeVar, cast

from django.conf import settings

import structlog
from drf_spectacular.utils import OpenApiResponse, PolymorphicProxySerializer, extend_schema
from pydantic import BaseModel, ValidationError
from rest_framework import serializers
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.file_system.file_system_logging import log_api_file_system_view
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_SCHEMA_HINT = "Please update the provided API schema to ensure API docs remain up to date"


class ValidatedRequest(Request):
    """
    Request with validated_data and validated_query_data attributes.
    These are set by the @validated_request decorator when serializers are provided.
    """

    validated_data: dict[str, Any]
    validated_query_data: dict[str, Any]


_VT = TypeVar("_VT")


class TypedRequest(ValidatedRequest, Generic[_VT]):
    """ValidatedRequest with a typed validated_data field.

    DataclassSerializer.validated_data returns a dataclass instance, but
    ValidatedRequest annotates it as dict[str, Any].  This subclass lets
    view methods declare the actual type so the type checker can follow along.

    Usage::

        def create(self, request: TypedRequest[CreateRepoInput], **kwargs) -> Response:
            data = request.validated_data  # type checker knows this is CreateRepoInput
    """

    validated_data: _VT  # type: ignore[assignment]


# Generic Pydantic model mixin for validating the response data
class PydanticModelMixin:
    def get_model(self, data: dict, model: type[T]) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            capture_exception(exc)
            raise ParseError("JSON parse error - {}".format(str(exc)))


@frozen
class _RequestValidator:
    """Validates the query params and the body of a request against the declared serializers."""

    view_name: str
    request_serializer: type[serializers.Serializer] | None
    query_serializer: type[serializers.Serializer] | None
    strict: bool
    include_serializer_context: bool

    def attach_validated_data(self, view: Any, request: Request) -> None:
        validated = cast(ValidatedRequest, request)
        validated.validated_query_data = {}
        if self.query_serializer is None and self.request_serializer is None:
            # Building the context reads `view.team`, which can hit the database, and no serializer wants it.
            return

        context = (
            {"request": request, "view": view, "team": getattr(view, "team", None)}
            if self.include_serializer_context
            else {}
        )

        if self.query_serializer is not None:
            query = self.query_serializer(data=request.query_params, context=context)
            query.is_valid(raise_exception=True)
            validated.validated_query_data = query.validated_data

        if self.request_serializer is not None:
            body = self.request_serializer(data=request.data, context=context)
            if not body.is_valid(raise_exception=self.strict) and settings.DEBUG:
                logger.warning(
                    f"Request body does not match declared serializer in @validated_request decorator. {_SCHEMA_HINT}",
                    view_func=self.view_name,
                    serializer_class=self.request_serializer.__name__,
                    validation_errors=body.errors,
                )
            validated.validated_data = body.validated_data


@frozen
class _ResponseValidator:
    """Checks what a view returned against the responses the decorator declares."""

    view_name: str
    responses: dict[int, OpenApiResponse | None] | None
    strict: bool

    def check(self, view: Any, result: Any) -> None:
        # Every check below either raises under strict mode or logs under DEBUG. Outside both it does nothing.
        if not (self.strict or settings.DEBUG):
            return

        if not self.responses:
            self._report(
                "Responses parameter is required when strict_response_validation is True",
                f"No responses parameter defined in @validated_request decorator. {_SCHEMA_HINT}",
            )
            return

        if not isinstance(result, Response):
            self._report(
                f"View must return a Response object when using @validated_request with response serializers. Got {type(result).__name__}",
                f"View must return a Response object when using @validated_request with response serializers. {_SCHEMA_HINT}",
                result_type=type(result).__name__,
            )
            return

        status_code = result.status_code
        if status_code not in self.responses:
            self._report(
                f"Response status code {status_code} not declared in responses parameter of the @validated_request decorator. "
                f"Declared status codes: {sorted(self.responses.keys())}",
                f"Response status code not declared in responses parameter of the @validated_request decorator. {_SCHEMA_HINT}",
                status_code=status_code,
                declared_status_codes=sorted(self.responses.keys()),
            )
            return

        response_config = self.responses[status_code]
        response_serializer = response_config.response if response_config else None
        if response_serializer is None:
            self._check_declared_empty(status_code, result.data)
        else:
            self._check_body(view, status_code, result.data, response_serializer)

    def _report(self, error: str, warning: str, **log_context: Any) -> None:
        if self.strict:
            raise serializers.ValidationError(error)
        logger.warning(warning, view_func=self.view_name, **log_context)

    def _check_declared_empty(self, status_code: int, data: Any) -> None:
        if data in (None, {}, []):
            return
        self._report(
            f"Response status code {status_code} is declared with no body, but response contains data",
            f"Response status code {status_code} is declared with no body, but response contains data. {_SCHEMA_HINT}",
            status_code=status_code,
        )

    def _check_body(self, view: Any, status_code: int, data: Any, response_serializer: Any) -> None:
        # A PolymorphicProxySerializer only describes the schema; it cannot validate data.
        # `many=True` wraps one in a plain ListSerializer, so the child needs the same check.
        if isinstance(response_serializer, PolymorphicProxySerializer) or isinstance(
            getattr(response_serializer, "child", None), PolymorphicProxySerializer
        ):
            return

        context: dict[str, Any] = getattr(view, "get_serializer_context", lambda: {})()
        serialized = self._instantiate(response_serializer, data, context)

        try:
            body_matches_serializer = serialized.is_valid(raise_exception=self.strict)
        except Exception as exc:
            # `is_valid` only handles DRF's ValidationError. A DataclassSerializer can raise other
            # errors for a valid response, and this check is advisory under DEBUG, so warn instead.
            if self.strict:
                raise
            logger.warning(
                "Response serializer could not parse the response it declared for status code "
                f"{status_code} in the responses parameter of the @validated_request decorator. "
                "The response was returned unchanged; check the declared serializer.",
                view_func=self.view_name,
                status_code=status_code,
                serializer_class=type(serialized).__name__,
                error=str(exc),
            )
            return

        if not body_matches_serializer:
            logger.warning(
                f"Response data does not match declared serializer for status code {status_code} declared in responses parameter of the @validated_request decorator. {_SCHEMA_HINT}",
                view_func=self.view_name,
                status_code=status_code,
                serializer_class=type(serialized).__name__,
                validation_errors=serialized.errors,
            )

    @staticmethod
    def _instantiate(response_serializer: Any, data: Any, context: dict[str, Any]) -> serializers.BaseSerializer[Any]:
        # drf-spectacular accepts a serializer class or an instance, so handle both.
        if not isinstance(response_serializer, serializers.BaseSerializer):
            return response_serializer(data=data, context=context)

        # A declared instance can carry constructor arguments that rebuilding from its class drops,
        # such as `allow_empty` on a `many=True` list or a keyword the serializer requires. DRF's
        # deepcopy replays the original constructor call, including for the child of a
        # ListSerializer, so copy the declared instance and bind only the response data to the copy.
        serialized = copy.deepcopy(response_serializer)
        serialized.initial_data = data
        serialized._context = context
        return serialized


def validated_request(
    request_serializer: type[serializers.Serializer] | None = None,
    *,
    query_serializer: type[serializers.Serializer] | None = None,
    responses: dict[int, OpenApiResponse | None] | None = None,
    summary: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    deprecated: bool = False,
    strict_request_validation: bool = True,
    strict_response_validation: bool = False,
    include_serializer_context: bool = False,
    **extend_schema_kwargs,
) -> Callable:
    """
    Takes req/res serializers and validates against them.

    Usage:
        @validated_request(
            request_serializer=RequestBodySerializer,
            query_serializer=QuerySerializer,
            responses={
                200: Response(response=SuccessResponseSerializer, ...),
            },
            summary="Do something"
        )
        def my_action(self, request: ValidatedRequest, **kwargs):
            # request.validated_data contains validated body data (if request_serializer provided)
            # request.validated_query_data contains validated query params (if query_serializer provided)
            body_field = request.validated_data["field"]
            query_param = request.validated_query_data["param"]

    By default the request/query serializers are constructed with no context, unlike DRF's
    own `get_serializer()` (which always includes `request`/`view`/`format`). Pass
    `include_serializer_context=True` to opt a view into the standard context — needed when a
    serializer's `validate()` reads `self.context["request"]` or `self.context["team"]` (e.g. to
    attribute a rejected request to the calling user/team).
    """

    def decorator(view_func: Callable) -> Callable:
        parameters: list = list(extend_schema_kwargs.pop("parameters", None) or [])
        if query_serializer is not None:
            parameters.append(query_serializer)

        request_validator = _RequestValidator(
            view_name=view_func.__name__,
            request_serializer=request_serializer,
            query_serializer=query_serializer,
            strict=strict_request_validation,
            include_serializer_context=include_serializer_context,
        )
        response_validator = _ResponseValidator(
            view_name=view_func.__name__, responses=responses, strict=strict_response_validation
        )

        @extend_schema(
            request=request_serializer,
            parameters=parameters if parameters else None,
            responses=responses,
            summary=summary,
            description=description,
            tags=tags,
            deprecated=deprecated,
            **extend_schema_kwargs,
        )
        @wraps(view_func)
        def wrapper(self, request: Request, *args, **kwargs) -> Response:
            request_validator.attach_validated_data(self, request)
            result = view_func(self, request, *args, **kwargs)
            response_validator.check(self, result)
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
