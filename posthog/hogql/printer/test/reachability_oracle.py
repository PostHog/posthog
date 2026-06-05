"""Reachability oracle for the HogQL printer rearchitecture (see ``posthog/hogql/PRINTER_REARCHITECTURE.md`` §9.3,
§12.5, §8.3).

The oracle is the *deletion gate* for the printer's property-decision code. We are moving the "what physical SQL does
``properties.X`` become" decision out of the printer and into early AST→AST passes. The printer's property machinery may
only be deleted once it is *provably* unreachable — and "provably" means: with the oracle active across the entire test
suite, no ``PropertyType`` reaches any of the three property-decision entry points for that dialect.

On master (today) EVERYTHING reaches the printer, so the oracle fires broadly — that is expected and correct. As the
migration lands logical lowering, the reached-set shrinks; when it is empty for a dialect, that dialect's printer
property code is dead and can be removed.

This module is **additive test tooling**. It instruments the entry points by wrapping the class methods (call through
to the original, never alter behavior) and restores them on exit. It changes no production behavior and is active only
inside ``printer_reachability_oracle()``.

The three entry points (doc §12.5):

1. ``BasePrinter._get_materialized_property_source_for_property_type`` — the chokepoint for value reads AND all 8
   comparison optimizers (which route here via ``ClickHousePrinter._get_materialized_string_property_source``). The
   ClickHouse override calls ``super()``, so patching the **base** method alone covers every dialect at a single site
   without double-counting. (When the ClickHouse override returns ``None`` early for a restricted property it does not
   call ``super()`` and this point does not fire — entry point 3 catches that case.)
2. ``ClickHousePrinter._get_property_group_source_for_field`` — the ``JSONHas`` / key-existence property-group path.
3. ``visit_property_type`` (base + the ``ClickHousePrinter`` and ``PostgresPrinter`` overrides) — recorded only when
   ``type.joined_subquery is None``, because a joined-subquery passthrough is a plain aliased-column read, not a
   property (doc §8.11). This catches the JSON-blob fallback and the restricted reads that return ``None`` from entry
   point 1 but still reach the printer as a property.

Subclass ``visit_property_type`` overrides call ``super()``, so a single node fires multiple wrappers on one instance.
That is fine and intended: reaches are recorded into a *set* keyed by ``(dialect, property_name, entry_point)`` so the
duplicates collapse to one record.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.printer.base import BasePrinter
from posthog.hogql.printer.clickhouse import ClickHousePrinter
from posthog.hogql.printer.duckdb import DuckDBPrinter
from posthog.hogql.printer.hogql import HogQLPrinter
from posthog.hogql.printer.postgres import PostgresPrinter

if TYPE_CHECKING:
    from posthog.hogql.printer.types import PrintableMaterializedColumn, PrintableMaterializedPropertyGroupItem

    from posthog.models import Team


# Entry-point identifiers recorded with each reach. Stable strings so reports/golden are deterministic.
ENTRY_MATERIALIZED_SOURCE = "_get_materialized_property_source_for_property_type"
ENTRY_PROPERTY_GROUP_SOURCE = "_get_property_group_source_for_field"
ENTRY_VISIT_PROPERTY_TYPE = "visit_property_type"

# Most-specific-first because ``DuckDBPrinter`` subclasses ``PostgresPrinter``: an ``isinstance`` check would
# misclassify a DuckDB printer as postgres. We match on the *exact* runtime class instead.
_DIALECT_BY_CLASS: tuple[tuple[type[BasePrinter], HogQLDialect], ...] = (
    (ClickHousePrinter, "clickhouse"),
    (DuckDBPrinter, "duckdb"),
    (PostgresPrinter, "postgres"),
    (HogQLPrinter, "hogql"),
)


def _dialect_for_printer(printer: BasePrinter) -> HogQLDialect | None:
    """Map a printer instance to its dialect by exact runtime class. Returns ``None`` for an unknown subclass."""
    printer_class = type(printer)
    for klass, dialect in _DIALECT_BY_CLASS:
        if printer_class is klass:
            return dialect
    return None


@dataclass(frozen=True)
class ReachRecord:
    """One distinct property-decision reach: a ``(dialect, property_name, entry_point)`` the printer was asked about.

    Frozen + hashable so records dedup in a ``set`` — the same node firing multiple ``visit_property_type`` wrappers
    (base + override) collapses to a single record.
    """

    dialect: HogQLDialect
    property_name: str
    entry_point: str


class ReachCollector:
    """Accumulates :class:`ReachRecord` s. Thread-unsafe by design (the test suite is single-process)."""

    def __init__(self) -> None:
        self._records: set[ReachRecord] = set()

    def record(self, dialect: HogQLDialect, property_name: str, entry_point: str) -> None:
        self._records.add(ReachRecord(dialect=dialect, property_name=property_name, entry_point=entry_point))

    @property
    def records(self) -> set[ReachRecord]:
        return self._records

    def dialects(self) -> set[HogQLDialect]:
        return {record.dialect for record in self._records}

    def records_for_dialect(self, dialect: HogQLDialect) -> set[ReachRecord]:
        return {record for record in self._records if record.dialect == dialect}

    def property_names_for_dialect(self, dialect: HogQLDialect) -> set[str]:
        return {record.property_name for record in self._records if record.dialect == dialect}

    def merge(self, other: ReachCollector) -> None:
        self._records |= other._records

    def clear(self) -> None:
        self._records.clear()

    def __len__(self) -> int:
        return len(self._records)

    def __bool__(self) -> bool:
        return bool(self._records)


def _property_name_from_type(type: ast.PropertyType) -> str | None:
    """First chain element is the top-level property key — the unit the oracle tracks (entry points 1 & 3)."""
    if not type.chain:
        return None
    return str(type.chain[0])


@contextlib.contextmanager
def printer_reachability_oracle() -> Iterator[ReachCollector]:
    """Instrument the three property-decision entry points; yield a live collector; restore originals on exit.

    Wrapping calls through to the original implementation and returns its value unchanged — the oracle never alters
    printer behavior, it only observes. Restoration is guaranteed via ``finally`` even if a wrapped call raises.
    """
    collector = ReachCollector()

    # Save originals (unbound functions on the class) so we can restore them exactly.
    original_materialized_source = BasePrinter._get_materialized_property_source_for_property_type
    original_property_group_source = ClickHousePrinter._get_property_group_source_for_field
    original_base_visit = BasePrinter.visit_property_type
    original_clickhouse_visit = ClickHousePrinter.visit_property_type
    original_postgres_visit = PostgresPrinter.visit_property_type

    def wrapped_materialized_source(
        self: BasePrinter, type: ast.PropertyType
    ) -> PrintableMaterializedColumn | PrintableMaterializedPropertyGroupItem | None:
        dialect = _dialect_for_printer(self)
        property_name = _property_name_from_type(type)
        if dialect is not None and property_name is not None:
            collector.record(dialect, property_name, ENTRY_MATERIALIZED_SOURCE)
        return original_materialized_source(self, type)

    def wrapped_property_group_source(
        self: ClickHousePrinter, field_type: ast.FieldType, property_name: str
    ) -> PrintableMaterializedPropertyGroupItem | None:
        dialect = _dialect_for_printer(self)
        if dialect is not None:
            collector.record(dialect, property_name, ENTRY_PROPERTY_GROUP_SOURCE)
        return original_property_group_source(self, field_type, property_name)

    def _record_visit(self: BasePrinter, type: ast.PropertyType) -> None:
        # A joined_subquery passthrough prints as ``alias.field`` — a plain column read, not a property (§8.11).
        if type.joined_subquery is not None and type.joined_subquery_field_name is not None:
            return
        dialect = _dialect_for_printer(self)
        property_name = _property_name_from_type(type)
        if dialect is not None and property_name is not None:
            collector.record(dialect, property_name, ENTRY_VISIT_PROPERTY_TYPE)

    def wrapped_base_visit(self: BasePrinter, type: ast.PropertyType) -> str:
        _record_visit(self, type)
        return original_base_visit(self, type)

    def wrapped_clickhouse_visit(self: ClickHousePrinter, type: ast.PropertyType) -> str:
        _record_visit(self, type)
        return original_clickhouse_visit(self, type)

    def wrapped_postgres_visit(self: PostgresPrinter, type: ast.PropertyType) -> str:
        _record_visit(self, type)
        return original_postgres_visit(self, type)

    BasePrinter._get_materialized_property_source_for_property_type = wrapped_materialized_source  # type: ignore[method-assign]
    ClickHousePrinter._get_property_group_source_for_field = wrapped_property_group_source  # type: ignore[method-assign]
    BasePrinter.visit_property_type = wrapped_base_visit  # type: ignore[method-assign]
    ClickHousePrinter.visit_property_type = wrapped_clickhouse_visit  # type: ignore[method-assign]
    PostgresPrinter.visit_property_type = wrapped_postgres_visit  # type: ignore[method-assign]

    try:
        yield collector
    finally:
        BasePrinter._get_materialized_property_source_for_property_type = original_materialized_source  # type: ignore[method-assign]
        ClickHousePrinter._get_property_group_source_for_field = original_property_group_source  # type: ignore[method-assign]
        BasePrinter.visit_property_type = original_base_visit  # type: ignore[method-assign]
        ClickHousePrinter.visit_property_type = original_clickhouse_visit  # type: ignore[method-assign]
        PostgresPrinter.visit_property_type = original_postgres_visit  # type: ignore[method-assign]


def reached_set_for_corpus(team: Team) -> ReachCollector:
    """Run every ``LOGICAL_CASES`` case through each of its dialects with the oracle active; return the reached-set.

    Compiles via the shared ``compile_case`` so the oracle sees exactly what the golden harness does. A case that fails
    to compile for a dialect is skipped (the oracle is not a correctness gate — the golden + execution nets are); we
    still record whatever reached the printer before the failure.
    """
    # Imported here, not at module top: the corpus/harness are sibling test modules and importing them at module load
    # would couple this tooling import to Django test setup. They are only needed when this helper actually runs.
    from posthog.hogql.printer.test.property_corpus import LOGICAL_CASES  # noqa: PLC0415
    from posthog.hogql.printer.test.property_harness import compile_case  # noqa: PLC0415

    with printer_reachability_oracle() as collector:
        for case in LOGICAL_CASES:
            for dialect in case.dialects:
                try:
                    compile_case(case.sql, dialect, team, case.modifiers)
                except Exception:
                    # Compilation failure is not the oracle's concern; keep whatever reaches we already recorded.
                    continue
    return collector


def format_report(collector: ReachCollector, ordered_dialects: tuple[HogQLDialect, ...]) -> str:
    """Render a sorted, human-readable reached-set report grouped by dialect.

    Deterministic ordering (fixed dialect order, then sorted property name, then sorted entry point) so the report is a
    stable artifact that can be diffed across runs to prove the set shrank.
    """
    lines: list[str] = []
    total = len(collector)
    lines.append("# HogQL printer reachability oracle — reached-set report")
    lines.append(
        "# Each line is a (property, entry_point) that reached the printer's property-decision code for that dialect."
    )
    lines.append("# On master this fires broadly (the printer still decides everything). The migration shrinks it to")
    lines.append("# empty per dialect; an empty dialect section means that dialect's printer property code is dead.")
    lines.append(f"# total distinct (dialect, property, entry_point) reaches: {total}")
    lines.append("")

    seen_dialects = collector.dialects()
    # Show every dialect we know about (even if empty) plus any unexpected extras, deterministically.
    extra_dialects = sorted(d for d in seen_dialects if d not in ordered_dialects)
    for dialect in (*ordered_dialects, *extra_dialects):
        records = sorted(
            collector.records_for_dialect(dialect),
            key=lambda record: (record.property_name, record.entry_point),
        )
        property_count = len({record.property_name for record in records})
        lines.append(f"## {dialect}  —  {len(records)} reaches across {property_count} distinct properties")
        if not records:
            lines.append("  (none — printer property code is unreachable for this dialect)")
        for record in records:
            lines.append(f"  {record.property_name}\t{record.entry_point}")
        lines.append("")

    return "\n".join(lines) + "\n"


def summarize(collector: ReachCollector, ordered_dialects: tuple[HogQLDialect, ...]) -> str:
    """One-line-per-dialect stdout summary (counts only)."""
    parts: list[str] = [f"reachability oracle: {len(collector)} total distinct reaches"]
    for dialect in ordered_dialects:
        records = collector.records_for_dialect(dialect)
        property_count = len({record.property_name for record in records})
        parts.append(f"  {dialect}: {len(records)} reaches / {property_count} properties")
    return "\n".join(parts)
