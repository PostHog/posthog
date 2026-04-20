from collections.abc import Callable
from typing import ClassVar

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.escape_sql import escape_duckdb_identifier
from posthog.hogql.printer.duckdb_functions import DUCKDB_FUNCTION_RENAMES_LOWER
from posthog.hogql.printer.postgres import PostgresPrinter


class DuckDBPrinter(PostgresPrinter):
    """Prints a HogQL AST as DuckDB SQL.

    DuckDB is Postgres-wire compatible, so this subclass inherits the vast
    majority of its behavior from ``PostgresPrinter``. Overrides are limited to
    places where DuckDB ships a native function or syntax that produces cleaner
    or faster SQL than the Postgres-compatible shim.
    """

    DIALECT_NAME: ClassVar[HogQLDialect] = "duckdb"

    def _print_identifier(self, name: str) -> str:
        # DuckDB has no practical identifier length limit, so skip the Postgres
        # 63-character truncation (which introduces SHA-suffixed names that are
        # harder to read and compare).
        return escape_duckdb_identifier(name)

    def _get_function_renames(self) -> dict[str, str]:
        # Layer DuckDB-specific renames on top of the inherited Postgres map.
        return {**super()._get_function_renames(), **DUCKDB_FUNCTION_RENAMES_LOWER}

    def _get_function_handlers(self) -> dict[str, Callable[[list[str]], str]]:
        # Drop any PG handler whose HogQL name DuckDB wants to rename natively —
        # the rename lookup runs after the handler lookup, so leaving the handler
        # in place would shadow our rename.
        parent_handlers = super()._get_function_handlers()
        return {k: v for k, v in parent_handlers.items() if k not in DUCKDB_FUNCTION_RENAMES_LOWER}
