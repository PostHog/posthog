from typing import TypeVar, Type

from pydantic import BaseModel, ValidationError

from rest_framework.exceptions import ParseError

T = TypeVar("T", bound=BaseModel)


class PydanticModelMixin:
    def get_model(self, data: dict, model: Type[T]) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise ParseError("JSON parse error - %s" % str(exc))
