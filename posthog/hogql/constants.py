import sys
from datetime import date, datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

type ConstantDataType = Literal["int", "float", "str", "bool", "array", "tuple", "date", "datetime", "uuid", "unknown"]
type ConstantSupportedPrimitive = int | float | str | bool | date | datetime | UUID | None
type ConstantSupportedData = (
    ConstantSupportedPrimitive | list[ConstantSupportedPrimitive] | tuple[ConstantSupportedPrimitive, ...]
)

# Keywords passed to ClickHouse without transformation
KEYWORDS = ["true", "false", "null"]

# Keywords you can't alias to
RESERVED_KEYWORDS = [*KEYWORDS, "team_id"]

# Limit applied to SELECT statements without LIMIT clause when queried via the API
DEFAULT_RETURNED_ROWS = 100
# Max limit for all SELECT queries, and the default for CSV exports
# Sync with frontend/src/queries/nodes/DataTable/DataTableExport.tsx
MAX_SELECT_RETURNED_ROWS = 50000
# Max limit for retention queries.
MAX_SELECT_RETENTION_LIMIT = 100000  # 100k
# Max limit for heatmaps which don't really need 1 billion so have their own max
MAX_SELECT_HEATMAPS_LIMIT = 1000000  # 1m datapoints
# Max limit for all cohort calculations
MAX_SELECT_COHORT_CALCULATION_LIMIT = 1000000000  # 1b persons
# Max amount of memory usage when doing group by before swapping to disk. Only used in certain queries
MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY = 22 * 1024 * 1024 * 1024

CSV_EXPORT_LIMIT = 300000
CSV_EXPORT_BREAKDOWN_LIMIT_INITIAL = 512
CSV_EXPORT_BREAKDOWN_LIMIT_LOW = 64  # The lowest limit we want to go to

BREAKDOWN_VALUES_LIMIT = 25
BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES = 300


class LimitContext(StrEnum):
    QUERY = "query"
    QUERY_ASYNC = "query_async"
    EXPORT = "export"
    COHORT_CALCULATION = "cohort_calculation"
    HEATMAPS = "heatmaps"
    SAVED_QUERY = "saved_query"
    RETENTION = "retention"


def get_max_limit_for_context(limit_context: LimitContext) -> int:
    if limit_context in (
        LimitContext.QUERY,
        LimitContext.QUERY_ASYNC,
    ):
        return MAX_SELECT_RETURNED_ROWS  # 50k
    elif limit_context == LimitContext.EXPORT:
        return CSV_EXPORT_LIMIT
    elif limit_context == LimitContext.HEATMAPS:
        return MAX_SELECT_HEATMAPS_LIMIT  # 1M
    elif limit_context == LimitContext.COHORT_CALCULATION:
        return MAX_SELECT_COHORT_CALCULATION_LIMIT  # 1b
    elif limit_context == LimitContext.RETENTION:
        return MAX_SELECT_RETENTION_LIMIT  # 100k
    elif limit_context == LimitContext.SAVED_QUERY:
        return sys.maxsize  # Max python int
    else:
        raise ValueError(f"Unexpected LimitContext value: {limit_context}")


def get_default_limit_for_context(limit_context: LimitContext) -> int:
    """Limit used if no limit is provided"""
    if limit_context == LimitContext.EXPORT:
        return CSV_EXPORT_LIMIT
    elif limit_context in (LimitContext.QUERY, LimitContext.QUERY_ASYNC):
        return DEFAULT_RETURNED_ROWS  # 100
    elif limit_context == LimitContext.HEATMAPS:
        return MAX_SELECT_HEATMAPS_LIMIT  # 1M
    elif limit_context == LimitContext.COHORT_CALCULATION:
        return MAX_SELECT_COHORT_CALCULATION_LIMIT  # 1b
    elif limit_context == LimitContext.SAVED_QUERY:
        return sys.maxsize  # Max python int
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
    optimize_aggregation_in_order: bool | None = None
    date_time_output_format: str | None = None
    date_time_input_format: str | None = None
    join_algorithm: str | None = None


# Settings applied on top of all HogQL queries.
class HogQLGlobalSettings(HogQLQuerySettings):
    model_config = ConfigDict(extra="forbid")
    readonly: int | None = 2
    max_execution_time: int | None = 60
    max_memory_usage: int | None = None  # default value coming from cloud config
    max_threads: int | None = None
    allow_experimental_object_type: bool | None = True
    format_csv_allow_double_quotes: bool | None = False
    max_ast_elements: int | None = 4_000_000  # default value 50000
    max_expanded_ast_elements: int | None = 4_000_000
    max_bytes_before_external_group_by: int | None = 0  # default value means we don't swap ordering by to disk
    allow_experimental_analyzer: bool | None = None
    transform_null_in: bool | None = True
    # A bugfix workaround that stops clauses that look like
    # `or(event = '1', event = '2', event = '3')` from being optimized into `event IN ('1', '2', '3')`
    # which can cause an error like `Not found column if(in(__table1.event, __set_String_14734461331367945596_10185115430245904968), 1_UInt8, 0_UInt8) in block.
    # There are only columns: if(nullIn(__table1.event, __set_String_14734461331367945596_10185115430245904968), 1_UInt8, 0_UInt8)
    # https://github.com/ClickHouse/ClickHouse/issues/64487
    optimize_min_equality_disjunction_chain_length: int | None = 4294967295
    # experimental support for nonequal joins
    allow_experimental_join_condition: bool | None = True
    preferred_block_size_bytes: int | None = None
