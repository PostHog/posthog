from typing import ClassVar

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.database.direct_snowflake_table import DirectSnowflakeTable
from posthog.hogql.printer.postgres import PostgresPrinter


class SnowflakePrinter(PostgresPrinter):
    """Prints a HogQL AST as Snowflake SQL."""

    DIALECT_NAME: ClassVar[HogQLDialect] = "snowflake"
    DIALECT_LABEL: ClassVar[str] = "Snowflake"

    def _print_table_sql(self, table) -> str:
        if isinstance(table, DirectSnowflakeTable):
            return table.to_printed_snowflake(self.context)
        if hasattr(table, "to_printed_snowflake"):
            return table.to_printed_snowflake(self.context)
        return super()._print_table_sql(table)

    def _print_table(self, table) -> str:
        if isinstance(table, DirectSnowflakeTable):
            return table.to_printed_snowflake(self.context)
        if hasattr(table, "to_printed_snowflake"):
            return table.to_printed_snowflake(self.context)
        return super()._print_table(table)
