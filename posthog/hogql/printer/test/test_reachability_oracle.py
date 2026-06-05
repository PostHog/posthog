"""Tests for the reachability oracle instrumentation (PR0b).

These pin the oracle's contract on the **master baseline**: with the printer's property-decision entry points
instrumented, property reads that still reach the printer ARE recorded, the oracle records nothing when inactive, and
the wrapped methods are restored on exit. On master the printer still decides everything for the SQL dialects, so the
reached-set is broadly non-empty — that is the expected, correct starting point the migration shrinks to empty.

One characterized subtlety (not a bug): the ``hogql`` dialect prints ``properties.foo`` natively via ``visit_field``
and never enters the property-decision entry points, so it records **nothing**. The oracle reports that faithfully —
for ``hogql`` the printer's property machinery is already unreachable.
"""

from __future__ import annotations

from posthog.test.base import BaseTest

from posthog.hogql.printer.base import BasePrinter
from posthog.hogql.printer.clickhouse import ClickHousePrinter
from posthog.hogql.printer.postgres import PostgresPrinter
from posthog.hogql.printer.test.property_harness import compile_case
from posthog.hogql.printer.test.reachability_oracle import (
    ENTRY_MATERIALIZED_SOURCE,
    ENTRY_VISIT_PROPERTY_TYPE,
    ReachCollector,
    printer_reachability_oracle,
    reached_set_for_corpus,
)

# A simple case that reads one property in SELECT and compares another in WHERE — both must be observed.
SAMPLE_SQL = "SELECT properties.foo FROM events WHERE properties.bar = 'x'"

# Dialects that route property reads through the printer's property-decision code on master. hogql prints natively and
# is handled separately (it reaches nothing).
DIALECTS_THAT_REACH = ("clickhouse", "postgres", "duckdb")


class TestReachabilityOracle(BaseTest):
    def test_clickhouse_reaches_are_recorded(self) -> None:
        with printer_reachability_oracle() as collector:
            compile_case(SAMPLE_SQL, "clickhouse", self.team)

        props = collector.property_names_for_dialect("clickhouse")
        assert props, "master baseline: properties must reach the ClickHouse printer"
        assert "foo" in props
        assert "bar" in props
        # The value-read chokepoint and the visit fallback both fire for an unmaterialized read.
        entries = {record.entry_point for record in collector.records_for_dialect("clickhouse")}
        assert ENTRY_MATERIALIZED_SOURCE in entries
        assert ENTRY_VISIT_PROPERTY_TYPE in entries
        # Nothing leaks into other dialects from a clickhouse-only compile.
        assert collector.property_names_for_dialect("postgres") == set()

    def test_postgres_reaches_are_recorded(self) -> None:
        with printer_reachability_oracle() as collector:
            compile_case(SAMPLE_SQL, "postgres", self.team)

        props = collector.property_names_for_dialect("postgres")
        assert props, "master baseline: properties must reach the Postgres printer"
        assert "foo" in props
        assert "bar" in props
        assert collector.property_names_for_dialect("clickhouse") == set()

    def test_hogql_reaches_nothing_because_it_prints_natively(self) -> None:
        # hogql re-prints `properties.foo` as a field chain (visit_field) and never enters the property-decision
        # entry points. The oracle correctly records nothing — the printer's property code is already dead for hogql.
        with printer_reachability_oracle() as collector:
            printed, _ = compile_case(SAMPLE_SQL, "hogql", self.team)

        assert "properties.foo" in printed  # native chain rendering, no JSON extract
        assert len(collector) == 0
        assert collector.property_names_for_dialect("hogql") == set()

    def test_records_nothing_when_oracle_inactive(self) -> None:
        # Compile outside the context manager: the wrappers are not installed, so nothing is observed.
        collector = ReachCollector()
        compile_case(SAMPLE_SQL, "clickhouse", self.team)
        assert len(collector) == 0

    def test_context_manager_restores_original_methods(self) -> None:
        original_materialized = BasePrinter._get_materialized_property_source_for_property_type
        original_property_group = ClickHousePrinter._get_property_group_source_for_field
        original_base_visit = BasePrinter.visit_property_type
        original_clickhouse_visit = ClickHousePrinter.visit_property_type
        original_postgres_visit = PostgresPrinter.visit_property_type

        with printer_reachability_oracle():
            # Inside the block the methods are wrapped (different identities).
            assert BasePrinter._get_materialized_property_source_for_property_type is not original_materialized
            assert BasePrinter.visit_property_type is not original_base_visit

        # On exit every entry point is restored to its original.
        assert BasePrinter._get_materialized_property_source_for_property_type is original_materialized
        assert ClickHousePrinter._get_property_group_source_for_field is original_property_group
        assert BasePrinter.visit_property_type is original_base_visit
        assert ClickHousePrinter.visit_property_type is original_clickhouse_visit
        assert PostgresPrinter.visit_property_type is original_postgres_visit

    def test_context_manager_restores_methods_after_exception(self) -> None:
        original_base_visit = BasePrinter.visit_property_type
        original_property_group = ClickHousePrinter._get_property_group_source_for_field

        with self.assertRaises(RuntimeError):
            with printer_reachability_oracle():
                raise RuntimeError("boom")

        assert BasePrinter.visit_property_type is original_base_visit
        assert ClickHousePrinter._get_property_group_source_for_field is original_property_group

    def test_corpus_reached_set_is_non_empty_per_reaching_dialect(self) -> None:
        # Documents the master baseline at corpus level: every SQL dialect that routes through the printer reaches it
        # for multiple properties; hogql prints natively and reaches nothing.
        collector = reached_set_for_corpus(self.team)

        for dialect in DIALECTS_THAT_REACH:
            records = collector.records_for_dialect(dialect)
            assert records, f"corpus reached-set must be non-empty for {dialect} on master"
            # The corpus reads many distinct property keys (foo, bar, a, arr, obj, ...).
            assert len(collector.property_names_for_dialect(dialect)) > 1

        assert collector.records_for_dialect("hogql") == set()
