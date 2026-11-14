from posthog.test.base import BaseTest

from posthog.models import Team

from products.cdp.backend.facade.api import enabled_transformations, warehouse_tables_with_enabled_hog_functions
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


# Saving compiles both: the empty filters to a program that returns true, the event filter to a real check.
NO_FILTERS: dict = {"events": [], "actions": []}
EVENT_FILTER = {"events": [{"id": "$pageview", "type": "events"}]}


class TestEnabledTransformations(BaseTest):
    def test_returns_the_enabled_transformations_of_the_asked_teams_in_ingestion_order(self) -> None:
        other_team, not_asked = (Team.objects.create(organization=self.organization) for _ in range(2))
        for team, template_id, type, execution_order, filters, enabled, deleted in [
            (self.team, "unordered", "transformation", None, None, True, False),
            (self.team, "second", "transformation", 2, NO_FILTERS, True, False),
            (self.team, "first", "transformation", 1, {}, True, False),
            (self.team, "second-created-later", "transformation", 2, EVENT_FILTER, True, False),
            (self.team, "disabled", "transformation", 1, None, False, False),
            (self.team, "deleted", "transformation", 1, None, True, True),
            (self.team, "destination", "destination", 1, None, True, False),
            (other_team, "filtered", "transformation", 1, EVENT_FILTER, True, False),
            (not_asked, "not-asked", "transformation", 1, None, True, False),
        ]:
            HogFunction.objects.create(
                team=team,
                template_id=template_id,
                type=type,
                execution_order=execution_order,
                filters=filters,
                enabled=enabled,
                deleted=deleted,
                hog=f"// {template_id}",
            )

        transformations = enabled_transformations(team_ids=[self.team.pk, other_team.pk])

        assert sorted(
            [(t.team_id, t.template_id, t.hog, t.has_filters) for t in transformations],
            key=lambda row: row[0],
        ) == [
            (self.team.pk, "first", "// first", False),
            (self.team.pk, "second", "// second", False),
            (self.team.pk, "second-created-later", "// second-created-later", True),
            (self.team.pk, "unordered", "// unordered", False),
            (other_team.pk, "filtered", "// filtered", True),
        ]
