from datetime import date, datetime
from typing import Optional, Literal, TypeAlias
from uuid import UUID
from pydantic import BaseModel, Extra

ConstantDataType: TypeAlias = Literal[
    "int", "float", "str", "bool", "array", "tuple", "date", "datetime", "uuid", "unknown"
]
ConstantSupportedPrimitive: TypeAlias = int | float | str | bool | date | datetime | UUID | None
ConstantSupportedData: TypeAlias = (
    ConstantSupportedPrimitive | list[ConstantSupportedPrimitive] | tuple[ConstantSupportedPrimitive, ...]
)

# Keywords passed to ClickHouse without transformation
KEYWORDS = ["true", "false", "null"]

# Keywords you can't alias to
RESERVED_KEYWORDS = KEYWORDS + ["team_id"]

# Limit applied to SELECT statements without LIMIT clause when queried via the API
DEFAULT_RETURNED_ROWS = 100
# Max limit for all SELECT queries, and the default for CSV exports.
MAX_SELECT_RETURNED_ROWS = 10000

# Settings applied on top of all HogQL queries.
class HogQLSettings(BaseModel):
    class Config:
        extra = Extra.forbid

    readonly: Optional[int] = 2
    max_execution_time: Optional[int] = 60
    allow_experimental_object_type: Optional[bool] = True
