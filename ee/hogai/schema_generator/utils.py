from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class SchemaGeneratorOutput(BaseModel, Generic[T]):
    query: Optional[T] = None
