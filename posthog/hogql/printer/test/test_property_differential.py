"""Differential shadow-compare: the new lowering path must reproduce master's output (doc §13).

Each query is compiled BOTH ways — ``lower_property_access`` off (the old printer path) and on (logical lowering + the
ClickHouse physical passes) — and the two are compared. For the unmaterialized logical corpus the two paths are
**byte-identical** (the migration's central claim — property reads with no materialized column behind them lower to a
``JSONFieldAccess`` that prints exactly the old JSON-blob extract). Result-equivalence for the materialized cases (where
the SQL legitimately churns) is the execution net's job (``test_property_characterization.py``), not this file.

The second suite exercises the compile-boundary hook (``prepare_and_print_ast``) that powers the suite-wide sweep: with
``HOGQL_SHADOW_DIFFERENTIAL`` set it recompiles every query on the new path and accumulates the outcome in the
process-global registry; unset, it is a no-op.
"""

import os

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.printer.differential import SHADOW_ENV, get_registry, reset_registry
from posthog.hogql.printer.test.property_corpus import LOGICAL_CASES
from posthog.hogql.printer.test.property_harness import compile_case, normalize


class TestLogicalCorpusDifferential(BaseTest):
    """Every logical corpus case, every dialect: old path SQL must equal new path SQL, byte for byte."""

    maxDiff = None

    @parameterized.expand([(case.name, case) for case in LOGICAL_CASES])
    def test_paths_are_byte_identical(self, _name: str, case) -> None:
        mismatches: list[str] = []
        for dialect in case.dialects:
            old, _ = compile_case(case.sql, dialect, self.team, case.modifiers, lower_property_access=False)
            new, _ = compile_case(case.sql, dialect, self.team, case.modifiers, lower_property_access=True)
            if normalize(new, self.team) != normalize(old, self.team):
                mismatches.append(
                    f"[{dialect}] new path diverged from old:\n  old: {normalize(old, self.team)}\n  new: {normalize(new, self.team)}"
                )
        assert not mismatches, f"{case.name}: lowering path is not byte-identical to master\n" + "\n".join(mismatches)


class TestShadowBoundaryHook(BaseTest):
    """The compile-boundary hook records the new-vs-old outcome of every query the suite compiles (the sweep engine)."""

    def setUp(self) -> None:
        super().setUp()
        reset_registry()

    def _serve(self, sql: str, dialect: str = "clickhouse") -> None:
        # Compile on the served (old) path through the public boundary — this is what the hook wraps.
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        prepare_and_print_ast(parse_select(sql), context, dialect=dialect)

    def test_hook_is_noop_when_env_unset(self) -> None:
        # No env → the hook must not recompile anything (zero overhead on normal runs).
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(SHADOW_ENV, None)
            self._serve("SELECT properties.foo FROM events")
        assert get_registry().total == 0

    @patch.dict(os.environ, {SHADOW_ENV: "collect"})
    def test_hook_records_equivalent_for_unmaterialized_read(self) -> None:
        self._serve("SELECT properties.foo FROM events WHERE properties.bar = 'x'")
        registry = get_registry()
        assert registry.equivalent_count >= 1, registry
        assert registry.divergences == [], registry.divergences
        assert registry.errors == [], registry.errors

    @patch.dict(os.environ, {SHADOW_ENV: "collect"})
    def test_hook_skips_hogql_dialect(self) -> None:
        # hogql never lowers, so its two paths are trivially identical — the hook must not waste a recompile on it.
        self._serve("SELECT properties.foo FROM events", dialect="hogql")
        assert get_registry().total == 0
