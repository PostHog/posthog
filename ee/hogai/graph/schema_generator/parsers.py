import json
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError


class PydanticOutputParserException(ValueError):
    llm_output: str
    """Serialized LLM output."""
    validation_message: str
    """Pydantic validation error message."""

    def __init__(self, llm_output: str, validation_message: str):
        super().__init__(f"{validation_message} at `{llm_output}`")
        self.llm_output = llm_output
        self.validation_message = validation_message


T = TypeVar("T", bound=BaseModel)


def parse_pydantic_structured_output(model: type[T]) -> Callable[[dict], T]:
    def parser(output: dict) -> T:
        try:
            return model.model_validate(output)
        except ValidationError as e:
            raise PydanticOutputParserException(
                llm_output=json.dumps(output), validation_message=e.json(include_url=False)
            )

    return parser
