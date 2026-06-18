from typing import ClassVar

from posthog.hogql.printer.base import HogQLDialect
from posthog.hogql.printer.postgres import PostgresPrinter


class SnowflakePrinter(PostgresPrinter):
    """Prints a HogQL AST as Snowflake SQL."""

    DIALECT_NAME: ClassVar[HogQLDialect] = "snowflake"
