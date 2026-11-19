from collections.abc import Callable
from typing import ClassVar

from posthog.hogql.database.models import DatabaseField, FunctionCallTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_hogql_identifier


class DirectSQLTable(FunctionCallTable):
    """Shared base for tables that print into an external SQL database queried directly
    (Postgres, MySQL, ...). Holds the members common to every engine; subclasses add the
    engine-specific schema/table fields and ``to_printed_<dialect>`` rendering."""

    requires_args: bool = False
    external_data_source_id: str
    connection_metadata: dict[str, object] | None = None
    # True for engines that resolve unquoted identifiers case-insensitively, so the resolver
    # accepts any spelling of a table qualifier while the printer keeps the discovered names.
    case_insensitive_identifiers: ClassVar[bool] = False
    # True only when these fields are the table's complete physical schema (no column-picker
    # restriction). Gates the direct `SELECT *` literal-star passthrough: when a restriction is in
    # effect the fields are a subset, so the star must expand from them rather than let the external
    # server expand against the unrestricted physical table (which would leak the hidden columns).
    has_complete_columns: bool = False
    # True when the column picker hides some of the table's columns, see `project_allowed_columns`.
    column_restricted: bool = False

    def project_allowed_columns(self, table_ref: str, quote: Callable[[str], str]) -> str:
        """Print a column-restricted table as a subquery of its allowed columns.

        The external server resolves names against whatever the FROM item exposes. A name HogQL can't
        resolve, a SELECT alias, a positional column-alias list or a whole-row reference would all reach
        hidden columns of the physical table, so the restriction has to hold in the printed SQL.
        """
        if not self.column_restricted:
            return table_ref
        columns = [field.name for field in self.fields.values() if isinstance(field, DatabaseField)]
        if not columns:
            raise QueryError(
                f"None of the selected columns of table {self.name} exist in the source anymore. "
                "Select its columns again."
            )
        return f"(SELECT {', '.join(quote(column) for column in columns)} FROM {table_ref})"

    def to_printed_hogql(self) -> str:
        return escape_hogql_identifier(self.name)
