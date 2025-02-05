from enum import Enum
from pydantic import BaseModel


class ResultEnum(str, Enum):
    QUESTION = "question"
    FILTER = "filter"


class FilterOperatorEnum(str, Enum):
    EXACT = "exact"
    IS_NOT = "is_not"
    ICONTAINS = "icontains"
    NOT_ICONTAINS = "not_icontains"
    REGEX = "regex"
    NOT_REGEX = "not_regex"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"
    IS_DATE_EXACT = "is_date_exact"
    IS_DATE_BEFORE = "is_date_before"
    IS_DATE_AFTER = "is_date_after"
    BETWEEN = "between"
    NOT_BETWEEN = "not_between"
    MIN = "min"
    MAX = "max"
    IN = "in"
    NOT_IN = "not_in"


class FilterTypeEnum(str, Enum):
    META = "meta"
    EVENT = "event"
    PERSON = "person"
    ELEMENT = "element"
    SESSION = "session"
    COHORT = "cohort"
    RECORDING = "recording"
    LOG_ENTRY = "log_entry"
    GROUP = "group"
    HOGQL = "hogql"
    DATA_WAREHOUSE = "data_warehouse"
    DATA_WAREHOUSE_PERSON_PROPERTY = "data_warehouse_person_property"


class LogicGroupTypeEnum(str, Enum):
    AND = "AND"
    OR = "OR"


class FilterValue(BaseModel):
    key: str
    type: FilterTypeEnum
    value: list[str]
    operator: FilterOperatorEnum

    class Config:
        extra = "forbid"


class FilterGroup(BaseModel):
    type: LogicGroupTypeEnum
    values: list[FilterValue]

    class Config:
        extra = "forbid"


class OuterFilterGroup(BaseModel):
    type: LogicGroupTypeEnum
    values: list[FilterGroup]

    class Config:
        extra = "forbid"


class FilterData(BaseModel):
    question: str
    date_from: str
    date_to: str
    filter_group: OuterFilterGroup

    class Config:
        extra = "forbid"


class AiFilterSchema(BaseModel):
    result: ResultEnum
    data: FilterData

    class Config:
        extra = "forbid"
