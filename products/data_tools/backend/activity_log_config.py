FIELD_EXCLUSIONS = {
    "DataWarehouseExpression": ["deleted_at"],
    "DataWarehouseJoin": ["deleted_at"],
}


FIELD_WITH_MASKED_CONTENTS = {
    # Any activity-log reader sees these rows, including readers denied the tables they name.
    "DataWarehouseJoin": [
        "source_table_name",
        "source_table_key",
        "joining_table_name",
        "joining_table_key",
        "field_name",
        "configuration",
    ],
}
