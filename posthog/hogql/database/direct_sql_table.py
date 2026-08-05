from posthog.hogql.database.models import FunctionCallTable
from posthog.hogql.escape_sql import escape_hogql_identifier


class DirectSQLTable(FunctionCallTable):
    """Shared base for tables that print into an external SQL database queried directly
    (Postgres, MySQL, ...). Holds the members common to every engine; subclasses add the
    engine-specific schema/table fields and ``to_printed_<dialect>`` rendering."""

    requires_args: bool = False
    external_data_source_id: str
    connection_metadata: dict[str, object] | None = None
    # True only when these fields are the table's complete physical schema (no column-picker
    # restriction). Gates the direct `SELECT *` literal-star passthrough: when a restriction is in
    # effect the fields are a subset, so the star must expand from them rather than let the external
    # server expand against the unrestricted physical table (which would leak the hidden columns).
    has_complete_columns: bool = False

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name)
