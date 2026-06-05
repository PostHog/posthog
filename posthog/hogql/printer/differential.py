"""Differential shadow-compare for the HogQL printer rearchitecture (``PRINTER_REARCHITECTURE.md`` §13).

The deletion gate for the printer's property-decision code is **equivalence, not reachability**: does the new
logical-lowering path produce master's output? We answer it by compiling each query **both ways** and comparing —

- **old path** = ``HogQLContext.lower_property_access`` **off** (today's default; the printer decides property → column).
- **new path** = ``lower_property_access`` **on** (logical lowering + ClickHouse physical passes decide; the printer
  renders ``JSONFieldAccess`` mechanically).

SQL-equal ⇒ equivalent (the common case — byte-identical for unmaterialized reads; cheap, no execution). SQL **differs**
⇒ the two paths are only *result*-equivalent (a materialized-column rewrite churns text but returns the same rows,
§8.7/§12.6), which is adjudicated by executing both — done by the caller that has data: the execution net in test, the
cost-guarded Celery worker in prod (§13.2). This module owns the **compile-both-ways + SQL compare** half and is shared
by both halves.

Two consumers:

1. **The compile-boundary hook** (``maybe_record_shadow_divergence``, wired into ``prepare_and_print_ast``): when the
   ``HOGQL_SHADOW_DIFFERENTIAL`` env is set in a test run, every query the suite compiles is recompiled on the new path
   and the SQL compared, accumulating divergences into a process-global :class:`ShadowRegistry` for a suite-wide sweep
   report (§8.3 — covers everything the suite touches, not a hand-picked corpus). Default (env unset) ⇒ a single cheap
   env check and return, zero overhead on normal runs.
2. **Direct callers** (the dedicated differential test, later the Celery worker) use :func:`compile_shadow_path` /
   :func:`compare_compiled` to drive the comparison themselves.

The new path must **fail loud** (§13.5): a property it cannot lower raises rather than silently falling back to the
printer. Here that surfaces as a recompile exception, captured as a :class:`ShadowError` — never swallowed into a
false "equivalent".
"""

from __future__ import annotations

import os
import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from posthog.hogql.constants import HogQLDialect, HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.visitor import clone_expr

if TYPE_CHECKING:
    from posthog.hogql.base import _T_AST


# ----------------------------------------------------------------------------------------------------------------------
# Comparison primitives
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledQuery:
    """One compile of a query: the printed SQL plus the parameter values the placeholders refer to.

    Equivalence is a property of the *pair* (sql, values) — two compiles match only if both the SQL template and the
    values it interpolates are identical. For unmaterialized reads the new path is byte-identical on both.
    """

    sql: str
    values: dict


@dataclass(frozen=True)
class ShadowComparison:
    dialect: HogQLDialect
    old: CompiledQuery
    new: CompiledQuery

    @property
    def equivalent(self) -> bool:
        # Sound by construction: identical SQL template + identical interpolated values ⇒ identical query. (Placeholder
        # renumbering would show here as a diff and escalate to result-comparison, which would confirm equivalence — so
        # strict equality never yields a false "equivalent", only an occasional conservative "differs".)
        return self.old.sql == self.new.sql and self.old.values == self.new.values


def compare_compiled(dialect: HogQLDialect, old: CompiledQuery, new: CompiledQuery) -> ShadowComparison:
    return ShadowComparison(dialect=dialect, old=old, new=new)


# ----------------------------------------------------------------------------------------------------------------------
# Shadow recompile (the new path) for an already-served old-path compile
# ----------------------------------------------------------------------------------------------------------------------


def build_shadow_context(served_context: HogQLContext) -> HogQLContext:
    """Derive a context for the new-path recompile from the already-served old-path context.

    Reuses the **deterministic / expensive** state the old compile resolved (``database``, ``restricted_properties``,
    resolved ``modifiers``, team/user, query flags, globals) so the shadow doesn't redo it, and **resets the per-compile
    mutable** state (``values``, ``timings``, observability, ``property_swapper``, ``workload``) so the recompile starts
    clean and placeholder numbering is apples-to-apples. Crucially it gives the shadow **fresh** warning/notice/error
    collectors so the recompile cannot pollute the user-facing context's diagnostics. The one switch that matters:
    ``lower_property_access=True``.

    NOTE: the shadow shares the served request's already-resolved ``Database``. That is the same team's schema and avoids
    an expensive rebuild; if shared post-resolution state ever produces a spurious diff, build a fresh database here.
    """
    return dataclasses.replace(
        served_context,
        lower_property_access=True,
        values={},
        timings=HogQLTimings(),
        type_observability=None,
        property_swapper=None,
        workload=None,
        warnings=[],
        notices=[],
        errors=[],
        data_warehouse_sync_warnings={},
    )


def compile_shadow_path(
    pristine_node: _T_AST,
    served_context: HogQLContext,
    dialect: HogQLDialect,
    stack: list | None = None,
    settings: HogQLGlobalSettings | None = None,
    pretty: bool = False,
) -> CompiledQuery:
    """Compile ``pristine_node`` on the **new** path and return its ``(sql, values)``.

    ``pristine_node`` must be a clone of the query taken **before** the old-path compile mutated it (the pipeline
    rewrites the node in place). ``settings`` likewise must be a copy untouched by the old path (the pipeline merges
    per-query settings into it). This calls the lower-level ``prepare_ast_for_printing`` / ``print_prepared_ast``
    directly rather than ``prepare_and_print_ast`` so the boundary hook is not re-entered; the recursion guard in
    :func:`maybe_record_shadow_divergence` is the backstop against any deeper re-entry.
    """
    # Lazy import breaks the utils ↔ differential cycle (utils imports the hook from here).
    from posthog.hogql.printer.utils import (  # noqa: PLC0415 — break circular import with printer.utils
        prepare_ast_for_printing,
        print_prepared_ast,
    )

    shadow_context = build_shadow_context(served_context)
    prepared = prepare_ast_for_printing(
        node=pristine_node, context=shadow_context, dialect=dialect, stack=stack, settings=settings
    )
    if prepared is None:
        return CompiledQuery(sql="", values=shadow_context.values)
    printed = print_prepared_ast(
        node=prepared, context=shadow_context, dialect=dialect, stack=stack, settings=settings, pretty=pretty
    )
    return CompiledQuery(sql=printed, values=shadow_context.values)


# ----------------------------------------------------------------------------------------------------------------------
# Process-global registry for the suite-wide sweep
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ShadowDivergence:
    """A query whose new-path SQL differed from its old-path SQL — to be adjudicated by result-comparison."""

    dialect: HogQLDialect
    old_sql: str
    new_sql: str


@dataclass(frozen=True)
class ShadowError:
    """The new path failed to compile a query the old path compiled fine — a fail-loud gap (§13.5)."""

    dialect: HogQLDialect
    old_sql: str
    error: str


@dataclass
class ShadowRegistry:
    """Accumulates the outcome of every shadow recompile during a sweep. Single-process by design (suite is serial)."""

    equivalent_count: int = 0
    divergences: list[ShadowDivergence] = field(default_factory=list)
    errors: list[ShadowError] = field(default_factory=list)

    def record_equivalent(self) -> None:
        self.equivalent_count += 1

    def record_divergence(self, divergence: ShadowDivergence) -> None:
        self.divergences.append(divergence)

    def record_error(self, error: ShadowError) -> None:
        self.errors.append(error)

    @property
    def total(self) -> int:
        return self.equivalent_count + len(self.divergences) + len(self.errors)


_registry: ShadowRegistry | None = None


def get_registry() -> ShadowRegistry:
    global _registry
    if _registry is None:
        _registry = ShadowRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = ShadowRegistry()


# ----------------------------------------------------------------------------------------------------------------------
# The compile-boundary hook
# ----------------------------------------------------------------------------------------------------------------------

SHADOW_ENV = "HOGQL_SHADOW_DIFFERENTIAL"

# Recursion guard: the shadow recompile must not itself trigger another shadow. A module-level flag is enough because
# the suite runs serially in one process; ``compile_shadow_path`` already side-steps the hook by calling the lower-level
# functions, so this only defends against an unexpected deeper re-entry into ``prepare_and_print_ast``.
_in_shadow = False

# Only these dialects have a meaningful old/new split. ``hogql`` never lowers (the printer renders properties directly),
# so its two paths are trivially identical — shadowing it is pure waste.
_SHADOW_DIALECTS: frozenset[HogQLDialect] = frozenset({"clickhouse", "postgres", "duckdb"})


def _shadow_mode() -> str | None:
    """``"strict"`` | ``"collect"`` | ``None`` (disabled). Confined to test runs even when the env is set."""
    raw = os.environ.get(SHADOW_ENV)
    if not raw:
        return None
    # Defense in depth: never double-compile outside tests, even if the env leaks into another environment.
    from django.conf import settings as django_settings  # noqa: PLC0415 — keep settings off the default import path

    if not getattr(django_settings, "TEST", False):
        return None
    return "strict" if raw.lower() == "strict" else "collect"


def should_shadow(context: HogQLContext, dialect: HogQLDialect) -> bool:
    """True when the boundary hook should recompile-and-compare for this query."""
    if _in_shadow:
        return False
    if dialect not in _SHADOW_DIALECTS:
        return False
    # The served compile must BE the old path for the comparison to mean anything. If the caller already turned lowering
    # on, the served output is the new path and there is nothing to shadow.
    if context.lower_property_access:
        return False
    return _shadow_mode() is not None


@dataclass(frozen=True)
class ShadowInput:
    """Pristine inputs snapshotted at the boundary *before* the old-path compile mutates the node and settings."""

    node: object
    settings: HogQLGlobalSettings | None


def snapshot_shadow_input(node: _T_AST, settings: HogQLGlobalSettings | None) -> ShadowInput:
    """Clone the node and copy the settings before the old path mutates either (call at the top of the boundary)."""
    return ShadowInput(
        node=clone_expr(node),
        settings=settings.model_copy(deep=True) if settings is not None else None,
    )


def maybe_record_shadow_divergence(
    shadow_input: ShadowInput,
    served_context: HogQLContext,
    dialect: HogQLDialect,
    old_sql: str,
    stack: list | None = None,
    pretty: bool = False,
) -> None:
    """Recompile the new path, compare to the served old-path SQL, and record the outcome in the registry.

    Called from ``prepare_and_print_ast`` after the old path has produced ``old_sql`` (so a shadow failure can never
    affect the served result). In ``collect`` mode every outcome is recorded and nothing is raised; in ``strict`` mode a
    divergence or a fail-loud recompile error is re-raised so a test fails. Recursion is fenced via ``_in_shadow``.
    """
    global _in_shadow
    mode = _shadow_mode()
    if mode is None:
        return

    registry = get_registry()
    _in_shadow = True
    try:
        new = compile_shadow_path(
            pristine_node=shadow_input.node,  # type: ignore[arg-type]
            served_context=served_context,
            dialect=dialect,
            stack=stack,
            settings=shadow_input.settings,
            pretty=pretty,
        )
    except Exception as exc:
        error = ShadowError(dialect=dialect, old_sql=old_sql, error=f"{type(exc).__name__}: {exc}")
        registry.record_error(error)
        if mode == "strict":
            raise
        return
    finally:
        _in_shadow = False

    comparison = compare_compiled(
        dialect=dialect,
        old=CompiledQuery(sql=old_sql, values=served_context.values),
        new=new,
    )
    if comparison.equivalent:
        registry.record_equivalent()
        return

    divergence = ShadowDivergence(dialect=dialect, old_sql=old_sql, new_sql=new.sql)
    registry.record_divergence(divergence)
    if mode == "strict":
        raise ShadowSQLDivergenceError(divergence)


class ShadowSQLDivergenceError(AssertionError):
    """Raised in ``strict`` mode when the new-path SQL diverges from the old path (result-equivalence not yet checked)."""

    def __init__(self, divergence: ShadowDivergence) -> None:
        self.divergence = divergence
        super().__init__(
            f"HogQL shadow differential: new path diverged from old for dialect {divergence.dialect!r}.\n"
            f"--- old (served) ---\n{divergence.old_sql}\n--- new (lowering) ---\n{divergence.new_sql}"
        )
