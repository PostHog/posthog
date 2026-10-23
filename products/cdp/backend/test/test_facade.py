from posthog.test.base import BaseTest

from products.cdp.backend.facade.api import warehouse_tables_with_enabled_hog_functions
from products.cdp.backend.models.hog_functions import HogFunction

VIEW_SOURCE = "data-warehouse-view"


class TestWarehouseTablesWithEnabledHogFunctions(BaseTest):
    def _function(self, source: str, table_names: list[str], *, enabled: bool = True, deleted: bool = False) -> None:
        HogFunction.objects.create(
            team=self.team,
            enabled=enabled,
            deleted=deleted,
            filters={"source": source, "data_warehouse": [{"table_name": name} for name in table_names]},
        )

    def test_returns_only_the_asked_names_an_enabled_function_of_that_source_triggers_on(self) -> None:
        self._function(VIEW_SOURCE, ["orders", "refunds", "not_asked"])
        self._function(VIEW_SOURCE, ["invoices"])
        self._function(VIEW_SOURCE, ["disabled_view"], enabled=False)
        self._function(VIEW_SOURCE, ["deleted_view"], deleted=True)
        self._function("data-warehouse-table", ["table_source"])

        triggered = warehouse_tables_with_enabled_hog_functions(
            team_id=self.team.pk,
            trigger_source=VIEW_SOURCE,
            table_names=["orders", "refunds", "invoices", "disabled_view", "deleted_view", "table_source", "unused"],
        )

        assert triggered == {"orders", "refunds", "invoices"}
