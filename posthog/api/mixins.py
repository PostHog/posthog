from typing import TypeVar

from posthog.exceptions_capture import capture_exception
from pydantic import BaseModel, ValidationError
from rest_framework.exceptions import ParseError

T = TypeVar("T", bound=BaseModel)


class PydanticModelMixin:
    def get_model(self, data: dict, model: type[T]) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            capture_exception(exc)
            raise ParseError("JSON parse error - {}".format(str(exc)))
