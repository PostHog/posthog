import decimal
import json
import math
import orjson
import pyarrow as pa
import pyarrow.compute as pc
import numpy as np
from typing import Any, Optional
from dateutil import parser
from collections.abc import Sequence

from dlt.common.schema.typing import TTableSchemaColumns
from dlt.common import logger
from dlt.common.configuration import with_config
from dlt.common.destination import DestinationCapabilitiesContext
from dlt.common.json import custom_encode, map_nested_in_place

from .schema_types import RowAny


def safe_parse_datetime(date_str):
    try:
        return parser.parse(date_str)
    except (ValueError, OverflowError):
        return None


@with_config
def columns_to_arrow(
    columns_schema: TTableSchemaColumns,
    caps: Optional[DestinationCapabilitiesContext] = None,
    tz: str = "UTC",
) -> Any:
    """Converts `column_schema` to arrow schema using `caps` and `tz`. `caps` are injected from the container - which
    is always the case if run within the pipeline. This will generate arrow schema compatible with the destination.
    Otherwise generic capabilities are used
    """
    from dlt.common.libs.pyarrow import pyarrow as pa, get_py_arrow_datatype
    from dlt.common.destination.capabilities import DestinationCapabilitiesContext

    return pa.schema(
        [
            pa.field(
                name,
                get_py_arrow_datatype(
                    schema_item,
                    caps or DestinationCapabilitiesContext.generic_capabilities(),
                    tz,
                ),
                nullable=schema_item.get("nullable", True),
            )
            for name, schema_item in columns_schema.items()
            if schema_item.get("data_type") is not None
        ]
    )


def row_tuples_to_arrow(rows: Sequence[RowAny], columns: TTableSchemaColumns, tz: str) -> Any:
    """Converts the rows to an arrow table using the columns schema.
    Columns missing `data_type` will be inferred from the row data.
    Columns with object types not supported by arrow are excluded from the resulting table.
    """

    caps = DestinationCapabilitiesContext.generic_capabilities()
    caps.decimal_precision = (76, 32)

    try:
        from pandas._libs import lib

        pivoted_rows = lib.to_object_array_tuples(rows).T
    except ImportError:
        logger.info("Pandas not installed, reverting to numpy.asarray to create a table which is slower")
        pivoted_rows = np.asarray(rows, dtype="object", order="k").T  # type: ignore[call-overload]

    columnar = {col: dat.ravel() for col, dat in zip(columns, np.vsplit(pivoted_rows, len(columns)))}
    columnar_known_types = {
        col["name"]: columnar[col["name"]] for col in columns.values() if col.get("data_type") is not None
    }
    columnar_unknown_types = {
        col["name"]: columnar[col["name"]] for col in columns.values() if col.get("data_type") is None
    }

    arrow_schema = columns_to_arrow(columns, caps=caps, tz=tz)
    column_names = list(columns.keys())

    for idx in range(0, len(arrow_schema.names)):
        field = arrow_schema.field(idx)
        py_type: type = type(None)
        col_index = column_names.index(field.name)
        for row in rows:
            val = row[col_index]
            if val is not None:
                py_type = type(val)
                break

        # cast double / float ndarrays to decimals if type mismatch, looks like decimals and floats are often mixed up in dialects
        if pa.types.is_decimal(field.type) and issubclass(py_type, str | float):
            logger.warning(
                f"Field {field.name} was reflected as decimal type, but rows contains {py_type.__name__}. Additional cast is required which may slow down arrow table generation."
            )
            float_array = pa.array(columnar_known_types[field.name], type=pa.float64())
            columnar_known_types[field.name] = float_array.cast(field.type, safe=False)
        # cast string timestamps to datetime objects
        if pa.types.is_timestamp(field.type) and issubclass(py_type, str):
            timestamp_array = pa.array(
                [safe_parse_datetime(s) for s in columnar_known_types[field.name]], type=field.type
            )
            columnar_known_types[field.name] = timestamp_array
            has_nulls = pc.any(pc.is_null(timestamp_array)).as_py()

            adjusted_field = arrow_schema.field(idx).with_nullable(has_nulls)
            arrow_schema = arrow_schema.set(idx, adjusted_field)
        if issubclass(py_type, dict | list):
            logger.warning(
                f"Field {field.name} was reflected as JSON type and needs to be serialized back to string to be placed in arrow table. This will slow data extraction down. You should cast JSON field to STRING in your database system ie. by creating and extracting an SQL VIEW that selects with cast."
            )
            json_str_array = pa.array([None if s is None else json_dumps(s) for s in columnar_known_types[field.name]])
            columnar_known_types[field.name] = json_str_array
        if issubclass(py_type, decimal.Decimal):
            # Remove any NaN or infinite values from decimal columns
            columnar_known_types[field.name] = np.array(
                [
                    None
                    if x is not None and (math.isnan(x) or (isinstance(x, decimal.Decimal) and x.is_infinite()))
                    else x
                    for x in columnar_known_types[field.name]
                ]
            )

        if issubclass(py_type, bytes) or issubclass(py_type, str):
            # For bytes/str columns, ensure any dict values are serialized to JSON strings
            # Convert to numpy array after processing
            processed_values = [
                None if x is None else json_dumps(x) if isinstance(x, dict | list) else x
                for x in columnar_known_types[field.name]
            ]
            columnar_known_types[field.name] = np.array(processed_values, dtype=object)

    # If there are unknown type columns, first create a table to infer their types
    if columnar_unknown_types:
        new_schema_fields = []
        for key in list(columnar_unknown_types):
            arrow_col: Optional[pa.Array] = None
            try:
                arrow_col = pa.array(columnar_unknown_types[key])
                if pa.types.is_null(arrow_col.type):
                    logger.warning(
                        f"Column {key} contains only NULL values and data type could not be inferred. This column is removed from a arrow table"
                    )
                    continue

            except pa.ArrowInvalid as e:
                # Try coercing types not supported by arrow to a json friendly format
                # E.g. dataclasses -> dict, UUID -> str
                try:
                    arrow_col = pa.array(map_nested_in_place(custom_encode, list(columnar_unknown_types[key])))
                    logger.warning(
                        f"Column {key} contains a data type which is not supported by pyarrow and got converted into {arrow_col.type}. This slows down arrow table generation."
                    )
                except (pa.ArrowInvalid, TypeError):
                    logger.warning(
                        f"Column {key} contains a data type which is not supported by pyarrow. This column will be ignored. Error: {e}"
                    )
            if arrow_col is not None:
                columnar_known_types[key] = arrow_col
                new_schema_fields.append(
                    pa.field(
                        key,
                        arrow_col.type,
                        nullable=columns[key]["nullable"],
                    )
                )

        # New schema
        column_order = {name: idx for idx, name in enumerate(columns)}
        arrow_schema = pa.schema(
            sorted(
                list(arrow_schema) + new_schema_fields,
                key=lambda x: column_order[x.name],
            )
        )

    return pa.Table.from_pydict(columnar_known_types, schema=arrow_schema)


def json_dumps(obj: Any) -> str:
    try:
        return orjson.dumps(obj).decode()
    except TypeError as e:
        if str(e) == "Integer exceeds 64-bit range":
            return json.dumps(obj)
        raise TypeError(e)
