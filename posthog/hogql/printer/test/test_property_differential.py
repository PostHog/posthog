"""Differential verification: the new lowering path must reproduce master's output (doc §13).

In test mode the differential is **always on** — every compiled HogQL query has the new path rendered from the same
resolved+swapped tree and compared, and a real result divergence fails the test (``check_query``, hooked at
``prepare_and_print_ast`` and the executor). This file pins the mechanism directly: byte-identity over the logical
corpus, and the pass / fail / skip behavior of ``check_query``. The suite at large is the real coverage.
"""

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.printer.differential import CompiledQuery, DifferentialResultMismatch, check_query
from posthog.hogql.printer.test.property_corpus import LOGICAL_CASES
from posthog.hogql.printer.test.property_harness import compile_case, normalize

_RENDER = "posthog.hogql.printer.differential.render_new_path"


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


class TestDifferentialCheck(ClickhouseTestMixin, BaseTest):
    """The always-on (in TEST) check: byte-identical passes; a real result divergence fails; unexecutable skips."""

    def _context(self) -> HogQLContext:
        return HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def test_byte_identical_query_passes(self) -> None:
        # Compiling an unmaterialized read runs the always-on check; the new path is byte-identical, so it must not
        # raise (and never executes — SQL-equal is the cheap path).
        prepare_and_print_ast(
            parse_select("SELECT properties.foo FROM events WHERE properties.bar = 'x'"),
            self._context(),
            dialect="clickhouse",
        )

    @patch(_RENDER)
    def test_real_result_divergence_fails(self, mock_render) -> None:
        # Force the new path to a SQL that executes to different rows than the served result → the check must fail.
        mock_render.return_value = CompiledQuery(sql="SELECT 2", values={})
        with self.assertRaises(DifferentialResultMismatch):
            check_query(parse_select("SELECT 1"), self._context(), "SELECT 1", "clickhouse", served_results=[(1,)])

    @patch(_RENDER)
    def test_unexecutable_new_path_skips(self, mock_render) -> None:
        # A new SQL that cannot run (missing table) is "can't adjudicate" → skip, never fail.
        mock_render.return_value = CompiledQuery(sql="SELECT 1 FROM table_that_does_not_exist_xyzzy", values={})
        check_query(parse_select("SELECT 1"), self._context(), "SELECT 1", "clickhouse", served_results=[(1,)])

    @patch(_RENDER)
    def test_result_equivalent_diff_passes(self, mock_render) -> None:
        # SQL differs but executes to the same rows (e.g. a materialized rewrite) → passes.
        mock_render.return_value = CompiledQuery(sql="SELECT 1 + 0", values={})
        check_query(parse_select("SELECT 1"), self._context(), "SELECT 1", "clickhouse", served_results=[(1,)])
