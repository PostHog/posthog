# Attribution fields addition for migration 0126
ADD_ATTRIBUTION_FIELDS_SQL = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS
has_gclid Bool,
ADD COLUMN IF NOT EXISTS
has_gad_source_paid_search Bool,
ADD COLUMN IF NOT EXISTS
has_fbclid Bool
AFTER region_name
"""


def add_attribution_fields_to_table(table_name: str) -> str:
    return ADD_ATTRIBUTION_FIELDS_SQL.format(table_name=table_name)


ADD_MAT_METADATA_FIELDS_SQL = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS
mat_metadata_loggedIn Nullable(Bool),
ADD COLUMN IF NOT EXISTS
mat_metadata_backend Nullable(String)
AFTER has_fbclid
"""


def add_mat_metadata_fields_to_table(table_name: str) -> str:
    return ADD_MAT_METADATA_FIELDS_SQL.format(table_name=table_name)


# Keep backward compatibility
def add_mat_metadata_loggedIn_to_table(table_name: str) -> str:
    return add_mat_metadata_fields_to_table(table_name)
