from datetime import date, datetime
from enum import Enum
from typing import Optional, Literal, TypeAlias
from uuid import UUID
from pydantic import ConfigDict, BaseModel

ConstantDataType: TypeAlias = Literal[
    "int",
    "float",
    "str",
    "bool",
    "array",
    "tuple",
    "date",
    "datetime",
    "uuid",
    "unknown",
]
ConstantSupportedPrimitive: TypeAlias = int | float | str | bool | date | datetime | UUID | None
ConstantSupportedData: TypeAlias = (
    ConstantSupportedPrimitive | list[ConstantSupportedPrimitive] | tuple[ConstantSupportedPrimitive, ...]
)

# Keywords passed to ClickHouse without transformation
KEYWORDS = ["true", "false", "null"]

# Keywords you can't alias to
RESERVED_KEYWORDS = [*KEYWORDS, "team_id"]

# Limit applied to SELECT statements without LIMIT clause when queried via the API
DEFAULT_RETURNED_ROWS = 100
# Max limit for all SELECT queries, and the default for CSV exports.
MAX_SELECT_RETURNED_ROWS = 10000  # sync with CSV_EXPORT_LIMIT
# Max limit for heatmaps which don't really need 1 billion so have their own max
MAX_SELECT_HEATMAPS_LIMIT = 1000000  # 1m datapoints
# Max limit for all cohort calculations
MAX_SELECT_COHORT_CALCULATION_LIMIT = 1000000000  # 1b persons

CSV_EXPORT_LIMIT = 10000
CSV_EXPORT_BREAKDOWN_LIMIT_INITIAL = 512
CSV_EXPORT_BREAKDOWN_LIMIT_LOW = 64  # The lowest limit we want to go to

BREAKDOWN_VALUES_LIMIT = 25
BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES = 300


class LimitContext(str, Enum):
    QUERY = "query"
    QUERY_ASYNC = "query_async"
    EXPORT = "export"
    COHORT_CALCULATION = "cohort_calculation"
    HEATMAPS = "heatmaps"


def get_max_limit_for_context(limit_context: LimitContext) -> int:
    if limit_context == LimitContext.EXPORT:
        return MAX_SELECT_RETURNED_ROWS  # 10k
    elif limit_context in (LimitContext.QUERY, LimitContext.QUERY_ASYNC):
        return MAX_SELECT_RETURNED_ROWS  # 10k
    elif limit_context == LimitContext.HEATMAPS:
        return MAX_SELECT_HEATMAPS_LIMIT  # 1M
    elif limit_context == LimitContext.COHORT_CALCULATION:
        return MAX_SELECT_COHORT_CALCULATION_LIMIT  # 1b
    else:
        raise ValueError(f"Unexpected LimitContext value: {limit_context}")


def get_default_limit_for_context(limit_context: LimitContext) -> int:
    """Limit used if no limit is provided"""
    if limit_context == LimitContext.EXPORT:
        return MAX_SELECT_RETURNED_ROWS  # 10k
    elif limit_context in (LimitContext.QUERY, LimitContext.QUERY_ASYNC):
        return DEFAULT_RETURNED_ROWS  # 100
    elif limit_context == LimitContext.HEATMAPS:
        return MAX_SELECT_HEATMAPS_LIMIT  # 1M
    elif limit_context == LimitContext.COHORT_CALCULATION:
        return MAX_SELECT_COHORT_CALCULATION_LIMIT  # 1b
    else:
        raise ValueError(f"Unexpected LimitContext value: {limit_context}")


def get_breakdown_limit_for_context(limit_context: LimitContext) -> int:
    """Limit used for breakdowns"""
    if limit_context == LimitContext.EXPORT:
        return CSV_EXPORT_BREAKDOWN_LIMIT_INITIAL

    return BREAKDOWN_VALUES_LIMIT


# Settings applied at the SELECT level
class HogQLQuerySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    optimize_aggregation_in_order: Optional[bool] = None


# Settings applied on top of all HogQL queries.
class HogQLGlobalSettings(HogQLQuerySettings):
    model_config = ConfigDict(extra="forbid")
    readonly: Optional[int] = 2
    max_execution_time: Optional[int] = 60
    allow_experimental_object_type: Optional[bool] = True
    format_csv_allow_double_quotes: Optional[bool] = False
    max_ast_elements: Optional[int] = 50000 * 20  # default value 50000
    max_expanded_ast_elements: Optional[int] = 1000000
    max_query_size: Optional[int] = 262144 * 2  # default value 262144 (= 256 KiB)
