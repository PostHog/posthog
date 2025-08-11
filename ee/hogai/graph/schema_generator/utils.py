from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class SchemaGeneratorOutput(BaseModel, Generic[T]):
    query: Optional[T] = Field(description="The final SQL query to be executed.", default=None)
