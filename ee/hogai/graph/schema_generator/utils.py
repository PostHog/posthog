from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

TOutput = TypeVar("TOutput")


class SchemaGeneratorOutput(BaseModel, Generic[TOutput]):
    query: Optional[TOutput] = None
