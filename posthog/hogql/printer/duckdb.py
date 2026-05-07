from collections.abc import Callable
from typing import ClassVar

from posthog.hogql.ast import AST
from posthog.hogql.constants import HogQLDialect, HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
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

    def __init__(
        self,
        context: HogQLContext,
        stack: list[AST] | None = None,
        settings: HogQLGlobalSettings | None = None,
        pretty: bool = False,
    ):
        super().__init__(context=context, stack=stack, settings=settings, pretty=pretty)
        # Pre-compute the merged rename table and the PG-handler-minus-DuckDB-renames table
        # once so that ``visit_call`` doesn't rebuild them on every invocation.
        parent_renames = super()._get_function_renames()
        self._duckdb_function_renames: dict[str, str] = {**parent_renames, **DUCKDB_FUNCTION_RENAMES_LOWER}
        parent_handlers = super()._get_function_handlers()
        self._duckdb_function_handlers: dict[str, Callable[[list[str]], str]] = {
            # PG emulates these HogQL names via handler functions; DuckDB prefers the
            # native renames, so strip the parent handler entries whose names we remap.
            k: v
            for k, v in parent_handlers.items()
            if k not in DUCKDB_FUNCTION_RENAMES_LOWER
        }

    def _print_identifier(self, name: str) -> str:
        # DuckDB has no practical identifier length limit, so skip the Postgres
        # 63-character truncation (which introduces SHA-suffixed names that are
        # harder to read and compare).
        return escape_duckdb_identifier(name)

    def _get_function_renames(self) -> dict[str, str]:
        return self._duckdb_function_renames

    def _get_function_handlers(self) -> dict[str, Callable[[list[str]], str]]:
        return self._duckdb_function_handlers

    def _assert_with_ties_supported(self) -> None:
        # DuckDB supports the ``LIMIT N WITH TIES`` shape this printer emits via the
        # inherited limit-clause rendering. Override to allow what Postgres rejects.
        return
