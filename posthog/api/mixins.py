from typing import Any, TypeVar, cast

from pydantic import BaseModel, ValidationError
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.file_system.file_system_logging import log_api_file_system_view
from posthog.exceptions_capture import capture_exception

T = TypeVar("T", bound=BaseModel)


class PydanticModelMixin:
    def get_model(self, data: dict, model: type[T]) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            capture_exception(exc)
            raise ParseError("JSON parse error - {}".format(str(exc)))


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
