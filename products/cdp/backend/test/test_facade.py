from posthog.test.base import BaseTest

from posthog.models import Team

from products.cdp.backend.facade.api import (
    teams_with_enabled_transformation,
    warehouse_tables_with_enabled_hog_functions,
)
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


class TestTeamsWithEnabledTransformation(BaseTest):
    def test_returns_only_the_asked_teams_that_run_an_enabled_transformation_of_the_template(self) -> None:
        teams = [self.team, *(Team.objects.create(organization=self.organization) for _ in range(5))]
        enabled, disabled, deleted, other_template, destination, not_asked = teams
        for team, template_id, type, is_enabled, is_deleted in [
            (enabled, "template-geoip", "transformation", True, False),
            (disabled, "template-geoip", "transformation", False, False),
            (deleted, "template-geoip", "transformation", True, True),
            (other_template, "template-other", "transformation", True, False),
            (destination, "template-geoip", "destination", True, False),
            (not_asked, "template-geoip", "transformation", True, False),
        ]:
            HogFunction.objects.create(
                team=team, template_id=template_id, type=type, enabled=is_enabled, deleted=is_deleted
            )

        teams_with_geoip = teams_with_enabled_transformation(
            template_id="template-geoip", team_ids=[team.pk for team in teams if team is not not_asked]
        )

        assert teams_with_geoip == {enabled.pk}
