from typing import TypeVar, Type

from pydantic import BaseModel, ValidationError

from rest_framework.exceptions import ParseError
from sentry_sdk import capture_exception

T = TypeVar("T", bound=BaseModel)


class PydanticModelMixin:
    def get_model(self, data: dict, model: Type[T]) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            capture_exception(exc)
            raise ParseError("JSON parse error - %s" % str(exc))
