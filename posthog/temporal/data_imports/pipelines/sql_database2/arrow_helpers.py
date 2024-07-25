from typing import Any, Optional
from collections.abc import Sequence
import uuid

from dlt.common.schema.typing import TTableSchemaColumns
from dlt.common import logger
from dlt.common.configuration import with_config
from dlt.common.destination import DestinationCapabilitiesContext
from dlt.common.json import custom_encode, map_nested_in_place

from .schema_types import RowAny


@with_config
def columns_to_arrow(
    columns_schema: TTableSchemaColumns,
    caps: DestinationCapabilitiesContext = None,
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
    from dlt.common.libs.pyarrow import pyarrow as pa
    import numpy as np

    try:
        from pandas._libs import lib

        pivoted_rows = lib.to_object_array_tuples(rows).T  # type: ignore[attr-defined]
    except ImportError:
        logger.info("Pandas not installed, reverting to numpy.asarray to create a table which is slower")
        pivoted_rows = np.asarray(rows, dtype="object", order="k").T  # type: ignore[call-overload]

    columnar = {col: dat.ravel() for col, dat in zip(columns, np.vsplit(pivoted_rows, len(columns)))}

    get_type = np.vectorize(type)
    apply_str = np.vectorize(lambda x: str(x) if x is not None else None)
    for col, dat in zip(columns, np.vsplit(pivoted_rows, len(columns))):
        typed_arr = get_type(dat.ravel())
        minus_uuid = typed_arr == uuid.UUID
        any_left = minus_uuid.any()
        if any_left:
            columnar[col] = apply_str(dat.ravel())
        else:
            columnar[col] = dat.ravel()

    columnar_known_types = {
        col["name"]: columnar[col["name"]] for col in columns.values() if col.get("data_type") is not None
    }
    columnar_unknown_types = {
        col["name"]: columnar[col["name"]] for col in columns.values() if col.get("data_type") is None
    }

    arrow_schema = columns_to_arrow(columns, tz=tz)

    for idx in range(0, len(arrow_schema.names)):
        field = arrow_schema.field(idx)
        py_type = type(rows[0][idx])
        # cast double / float ndarrays to decimals if type mismatch, looks like decimals and floats are often mixed up in dialects
        if pa.types.is_decimal(field.type) and issubclass(py_type, str | float):
            logger.warning(
                f"Field {field.name} was reflected as decimal type, but rows contains {py_type.__name__}. Additional cast is required which may slow down arrow table generation."
            )
            float_array = pa.array(columnar_known_types[field.name], type=pa.float64())
            columnar_known_types[field.name] = float_array.cast(field.type, safe=False)

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
