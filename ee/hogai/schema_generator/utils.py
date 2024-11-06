from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=type[BaseModel])


class SchemaGeneratorOutput(BaseModel, Generic[T]):
    reasoning_steps: Optional[list[str]] = None
    answer: Optional[T] = None
