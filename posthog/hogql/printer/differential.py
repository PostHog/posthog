"""Differential verification for the HogQL printer rearchitecture (``PRINTER_REARCHITECTURE.md`` §13).

**In test mode, every compiled HogQL query is also rendered on the new lowering path and compared** — so the existing
suite verifies both paths on every run (the production Celery shadow's logic, synchronous, in CI). Always on
(``settings.TEST``), not an opt-in.

The new path and the old path **share everything up to the gate**: parse, resolve, the property swappers. They differ
only in the final steps — for the new path the logical-lowering pass + the ClickHouse physical passes rewrite the
property reads, and the printer renders the resulting ``JSONFieldAccess`` mechanically. So the differential takes the
**served prepared tree** (the resolved, swapped AST the old-path compile already produced) and applies *only* those
new-path steps to a clone of it. It never re-resolves — which matters: resolution is path-independent, expensive, and
re-running it a second time would fight one-shot test fixtures (mocked group-type / materialized-column lookups).

- **Compare:** render the new path and compare SQL. **SQL-equal ⇒ same results** (the unmaterialized common case;
  free, no execution). **SQL-differs ⇒ execute both and compare result rows** — a materialized rewrite is
  result-equivalent (passes); a real divergence **fails the test**. If either side cannot be executed (a mock that
  patches the registry but never creates the column, a compile-only context with no live ClickHouse), the check
  **skips** — it never false-fails on what it cannot adjudicate.

Hooked at both real boundaries so the whole suite is covered (§13.9): ``HogQLQueryExecutor.execute`` (the served result
is in hand) and ``prepare_and_print_ast`` (compile-only callers — the served SQL is executed too on a diff). The
production half is the Celery shadow + the ``propertyLowering`` org feature flag that controls which path *serves*.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from posthog.hogql.constants import HogQLDialect, HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.transforms.clickhouse_physical_passes import clickhouse_physical_passes
from posthog.hogql.transforms.logical_property_lowering import lower_property_access
from posthog.hogql.visitor import clone_expr

if TYPE_CHECKING:
    from posthog.hogql.base import _T_AST


# Only ClickHouse can be executed-and-compared here (``sync_execute``). For the warehouse dialects the check is
# SQL-equality only: equal ⇒ pass, differs ⇒ skip (can't adjudicate without their execution path). The corpus golden
# pins their byte-identity, and a materialized rewrite — the only source of a SQL diff — is ClickHouse-only.
_EXECUTE_DIALECTS: frozenset[HogQLDialect] = frozenset({"clickhouse"})
_COMPARE_DIALECTS: frozenset[HogQLDialect] = frozenset({"clickhouse", "postgres", "duckdb"})

# Recursion guard: rendering/executing the new path must not re-enter the check. A single flag suffices — the suite
# runs serially in one process. Also consulted by test query-capture to exclude the differential's own queries.
_in_differential = False


def _is_test_mode() -> bool:
    from django.conf import settings  # noqa: PLC0415 — keep django settings off the default import path

    return bool(getattr(settings, "TEST", False))


def is_in_differential() -> bool:
    """Whether a differential check is currently rendering/executing the new path. Test query-capture (and any other
    observer of executed queries) consults this to **exclude the differential's verification queries** — they are not
    part of the query behavior the test is asserting on."""
    return _in_differential


def should_check(context: HogQLContext, dialect: HogQLDialect) -> bool:
    """True when the boundary should run the differential for this query (cheap pre-filter)."""
    if _in_differential or not _is_test_mode() or dialect not in _COMPARE_DIALECTS:
        return False
    # The served compile must BE the old path. If lowering is already on (an org switched over, or a test forced it),
    # the served output is the new path and there is nothing to compare.
    return not context.lower_property_access


# ----------------------------------------------------------------------------------------------------------------------
# Render the new path from the served (already resolved + swapped) prepared tree
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    values: dict


def build_new_path_context(served_context: HogQLContext) -> HogQLContext:
    """A context for rendering the new path from the served prepared tree. Keeps the resolved state the lowering +
    physical passes read (``database``, ``property_swapper``, ``modifiers``, ``restricted_properties``); flips lowering
    on; and gives a **fresh** ``values`` dict so the new render's placeholders don't collide with the served render's."""
    return dataclasses.replace(
        served_context,
        lower_property_access=True,
        values={},
        timings=HogQLTimings(),
        type_observability=None,
        warnings=[],
        notices=[],
        errors=[],
        data_warehouse_sync_warnings={},
    )


def render_new_path(
    served_prepared: _T_AST,
    served_context: HogQLContext,
    dialect: HogQLDialect,
    stack: list | None = None,
    settings: HogQLGlobalSettings | None = None,
    pretty: bool = False,
) -> CompiledQuery:
    """Apply the new-path steps (logical lowering + ClickHouse physical passes) to a clone of the served prepared tree
    and print it. Shares resolution + the swappers with the served compile — it does NOT re-resolve."""
    from posthog.hogql.printer.utils import print_prepared_ast  # noqa: PLC0415 — break circular import with utils

    context = build_new_path_context(served_context)
    node = clone_expr(served_prepared)
    node = lower_property_access(node, context)
    if dialect == "clickhouse":
        node = clickhouse_physical_passes(node, context)
    printed = print_prepared_ast(
        node=node, context=context, dialect=dialect, stack=stack, settings=settings, pretty=pretty
    )
    return CompiledQuery(sql=printed, values=context.values)


# ----------------------------------------------------------------------------------------------------------------------
# Execute-and-compare
# ----------------------------------------------------------------------------------------------------------------------


class _Unexecutable:
    """Sentinel: the SQL could not be executed, so the difference cannot be adjudicated (skip, never fail)."""


_UNEXECUTABLE = _Unexecutable()


class DifferentialResultMismatch(AssertionError):
    """The new lowering path returned different rows than the old path for the same query — a real regression."""

    def __init__(self, dialect: HogQLDialect, old_sql: str, new_sql: str) -> None:
        super().__init__(
            f"HogQL differential: the new lowering path returned different results for dialect {dialect!r}.\n"
            f"--- old (served) ---\n{old_sql}\n--- new (lowering) ---\n{new_sql}"
        )


def _safe_execute(sql: str, values: dict, context: HogQLContext) -> list | _Unexecutable:
    """Run a read-only SELECT and return its rows, or ``_UNEXECUTABLE`` if it cannot run (no live CH, a mocked-but-
    absent materialized column, an environmental error). Never raises — an unrunnable query is "can't adjudicate"."""
    from posthog.clickhouse.client.execute import sync_execute  # noqa: PLC0415 — keep the CH client off the import path

    try:
        return list(sync_execute(sql, values, team_id=context.team_id, readonly=True))
    except Exception:
        return _UNEXECUTABLE


def _rows_equal(old: list, new: list) -> bool:
    # Order-insensitive multiset comparison (a query without ORDER BY has undefined row order). ``repr`` keys make
    # rows hashable even when they contain arrays / maps / tuples.
    return Counter(map(repr, old)) == Counter(map(repr, new))


def check_query(
    served_prepared: _T_AST | None,
    served_context: HogQLContext,
    served_sql: str,
    dialect: HogQLDialect,
    *,
    served_results: list | None = None,
    stack: list | None = None,
    settings: HogQLGlobalSettings | None = None,
    pretty: bool = False,
) -> None:
    """Render the new path from the served prepared tree and compare to the served compile; raise
    :class:`DifferentialResultMismatch` on a real result divergence. SQL-equal ⇒ return (same results). SQL-differs ⇒
    execute both and compare rows; skip if either side is unexecutable. A no-op outside test mode or inside a nested
    check, or when there is no prepared tree to render (an empty/short-circuited compile)."""
    global _in_differential
    if served_prepared is None or not should_check(served_context, dialect):
        return

    _in_differential = True
    try:
        # Render the new path from the served prepared tree. Shares resolution + swappers, so a failure here is in the
        # lowering / physical passes / printer — a real fail-loud gap (§13.5) — and propagates.
        new = render_new_path(served_prepared, served_context, dialect, stack=stack, settings=settings, pretty=pretty)

        if new.sql == served_sql and new.values == served_context.values:
            return  # SQL identical ⇒ results identical, no execution needed

        if dialect not in _EXECUTE_DIALECTS:
            return  # warehouse dialects: SQL-equality only; a diff can't be adjudicated here

        old_rows = (
            served_results
            if served_results is not None
            else _safe_execute(served_sql, served_context.values, served_context)
        )
        if old_rows is _UNEXECUTABLE:
            return
        new_rows = _safe_execute(new.sql, new.values, served_context)
        if new_rows is _UNEXECUTABLE:
            return

        if not _rows_equal(old_rows, new_rows):
            raise DifferentialResultMismatch(dialect, served_sql, new.sql)
    finally:
        _in_differential = False
