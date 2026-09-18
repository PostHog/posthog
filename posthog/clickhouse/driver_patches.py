"""Corrections applied to the pinned clickhouse-driver.

Every patch here is a defect in clickhouse-driver 0.2.10 that we cannot wait for a release to
fix. Drop a patch once the pinned version carries the fix.
"""

import struct
from collections.abc import Callable
from typing import Any

from clickhouse_driver import errors as driver_errors
from clickhouse_driver.columns import (
    mapcolumn,
    service as column_service,
)
from clickhouse_driver.columns.base import Column
from clickhouse_driver.columns.util import get_inner_columns, get_inner_spec
from clickhouse_driver.streams import native as native_stream


class ClickHouseColumnDecodeError(Exception):
    """The driver could not turn a result column into Python values.

    Raised in place of the driver's own error so the column type reaches the caller, which
    otherwise sees a bare `ValueError` from somewhere inside the decoder.
    """

    def __init__(self, column_type: str, cause: Exception) -> None:
        self.column_type = column_type
        super().__init__(f"Cannot decode ClickHouse column of type {column_type}: {cause}")


# A decode failure is a parsing or unpacking fault. A network or socket error passes through the
# same call and must stay untouched, because a retry can still succeed for it.
_DECODE_ERROR_TYPES = (
    driver_errors.UnknownTypeError,
    driver_errors.LogicalError,
    struct.error,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
)


def _create_map_column(
    spec: str, column_by_spec_getter: Callable[[str], Column], column_options: dict[str, Any]
) -> mapcolumn.MapColumn:
    """Replacement for `mapcolumn.create_map_column`.

    The original splits the inner spec on a regex that only skips a comma followed by a bare type
    name, so any value type nesting a comma before a parenthesis (`Map(String, Map(String,
    Array(UInt64)))`) yields three parts and fails to unpack. Split on paren depth instead, with
    the helper the driver already uses for Tuple.
    """
    inner_columns = get_inner_columns(get_inner_spec("Map", spec))
    if len(inner_columns) != 2:
        raise driver_errors.UnknownTypeError(f"Unknown type {spec}")

    key, value = inner_columns
    return mapcolumn.MapColumn(
        column_by_spec_getter(key.strip()),
        column_by_spec_getter(value.strip()),
        **column_options,
    )


def _naming_read_column(original: Callable[..., Any]) -> Callable[..., Any]:
    def read_column(context: Any, column_spec: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return original(context, column_spec, *args, **kwargs)
        except _DECODE_ERROR_TYPES as err:
            raise ClickHouseColumnDecodeError(column_spec, err) from err

    return read_column


_installed = False


def install_clickhouse_driver_patches() -> None:
    global _installed
    if _installed:
        return
    _installed = True

    mapcolumn.create_map_column = _create_map_column
    column_service.create_map_column = _create_map_column
    native_stream.read_column = _naming_read_column(native_stream.read_column)
