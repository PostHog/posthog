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
    DIALECT_LABEL: ClassVar[str] = "DuckDB"

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
        self._jsonpath_placeholders: dict[str, str] = {}

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

    def _json_property_args(self, chain) -> list[str]:
        # DuckDB reads a JSON key beginning with `$` as a JSONPath root marker, so PostHog's
        # `$`-prefixed property keys break the inherited Postgres `->>` arrow form. Bind the whole
        # chain as one quoted JSONPath member expression (`$."k1"."k2"`) instead, forcing plain-key
        # semantics for every key. The path is a bound value (not inlined), so this is not an
        # injection vector; the escaping only keeps the JSONPath itself well-formed.
        def member(key) -> str:
            escaped = str(key).replace("\\", "\\\\").replace('"', '\\"')
            return f'."{escaped}"'

        path = "$" + "".join(member(k) for k in chain)
        # DuckDB rejects `GROUP BY <expr>` when the SELECT and GROUP BY bind the same path to
        # different placeholders, so reuse one placeholder per distinct path within a query.
        placeholder = self._jsonpath_placeholders.get(path)
        if placeholder is None:
            placeholder = self.context.add_value(path)
            self._jsonpath_placeholders[path] = placeholder
        return [placeholder]

    def _unsafe_json_extract_trim_quotes(self, unsafe_field, unsafe_args):
        if not unsafe_args:
            return unsafe_field
        return f"({unsafe_field}) ->> {unsafe_args[0]}"
