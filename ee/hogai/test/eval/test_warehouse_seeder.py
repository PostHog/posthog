"""DB-backed integration test for the warehouse seeder.

Runs the seeder against a real test team and asserts the synthetic catalog is
discoverable through ``system.information_schema`` — the contract the eval's
scorers depend on. The queryable needle requires object storage and degrades to
``queryable=False`` here; that path is covered too.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql.query import execute_hogql_query

from ee.hogai.eval.sandboxed.data_warehouse.seeder import seed_warehouse_schema

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from ee.hogai.eval.sandboxed.data_warehouse.synthesizer import (
    DESC_NEEDLE_PHRASE,
    DESC_NEEDLE_TABLE,
    REL_NEEDLE_SOURCE,
    REL_NEEDLE_TARGET,
    TYPE_NEEDLE_COLUMN,
    TYPE_NEEDLE_TABLE,
    VIEW_NEEDLE_NAME,
)


class TestWarehouseSeeder(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        # The seeder only reads team_id/user_id; a namespace stands in for the real
        # sandbox context here.
        context = cast("CustomPromptSandboxContext", SimpleNamespace(team_id=self.team.id, user_id=self.user.id))
        self.seed = seed_warehouse_schema(context)

    def _query(self, sql: str) -> list:
        return execute_hogql_query(sql, team=self.team).results or []

    def test_seed_payload_has_all_needles(self):
        assert self.seed["table_count"] >= 200
        assert self.seed["view_count"] >= 1
        assert self.seed["join_count"] >= 1
        assert set(self.seed) >= {
            "description_needle",
            "column_type_needle",
            "relationship_needle",
            "view_needle",
            "retrieval_needle",
        }

    def test_hundreds_of_tables_are_discoverable(self):
        rows = self._query("SELECT count() FROM system.information_schema.tables WHERE table_type = 'data_warehouse'")
        assert rows[0][0] >= 200

    def test_description_needle_surfaces_with_phrase(self):
        rows = self._query(
            f"SELECT description FROM system.information_schema.tables WHERE table_name = '{DESC_NEEDLE_TABLE}'"
        )
        assert rows and DESC_NEEDLE_PHRASE in (rows[0][0] or "")

    def test_description_search_finds_only_the_needle(self):
        rows = self._query(
            "SELECT table_name FROM system.information_schema.tables WHERE description ILIKE '%canonical MRR%'"
        )
        assert [r[0] for r in rows] == [DESC_NEEDLE_TABLE]

    def test_decimal_column_is_unique_among_warehouse_tables(self):
        # `information_schema.columns` spans every table, so the Decimal needle is
        # unique only within the warehouse schema — which is what the eval prompt
        # scopes to ("across all our warehouse tables").
        rows = self._query(
            "SELECT table_name, column_name FROM system.information_schema.columns "
            "WHERE data_type = 'Decimal' AND table_schema = 'warehouse'"
        )
        assert [tuple(r) for r in rows] == [(TYPE_NEEDLE_TABLE, TYPE_NEEDLE_COLUMN)]

    def test_relationship_needle_surfaces(self):
        rows = self._query(
            "SELECT source_table, target_table FROM system.information_schema.relationships "
            f"WHERE source_table = '{REL_NEEDLE_SOURCE}'"
        )
        assert [REL_NEEDLE_SOURCE, REL_NEEDLE_TARGET] in [[r[0], r[1]] for r in rows]

    def test_view_needle_is_classified_as_view(self):
        rows = self._query(
            f"SELECT table_type FROM system.information_schema.tables WHERE table_name = '{VIEW_NEEDLE_NAME}'"
        )
        assert rows and rows[0][0] == "view"
