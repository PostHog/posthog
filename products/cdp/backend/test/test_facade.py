import json

from posthog.test.base import BaseTest
from unittest import mock

from parameterized import parameterized

from posthog.models import Organization, Team

from products.cdp.backend.facade.api import (
    disable_hog_function,
    disable_plugin_config,
    enabled_hog_function_ids_by_type,
    enabled_plugin_config_ids,
    warehouse_tables_with_enabled_hog_functions,
)
from products.cdp.backend.models.hog_functions import HogFunction
from products.cdp.backend.models.plugin import Plugin, PluginConfig

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


class RecordingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, object]] = []

    def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, json.loads(message) if message else message))


class TestStoppingCdpWork(BaseTest):
    def _stoppable(self, kind: str, team: Team) -> str:
        if kind == "hog_function":
            return str(HogFunction.objects.create(team=team, type="destination", enabled=True, hog="return event").id)
        plugin = Plugin.objects.create(organization=team.organization, name="Legacy plugin")
        return str(PluginConfig.objects.create(plugin=plugin, team=team, enabled=True, order=0).id)

    @parameterized.expand(
        [
            ("hog_function", disable_hog_function, lambda team_ids: enabled_hog_function_ids_by_type(team_ids)),
            ("plugin_config", disable_plugin_config, enabled_plugin_config_ids),
        ]
    )
    def test_disabling_tells_the_workers_and_leaves_other_teams_running(self, kind, disable, running) -> None:
        mine = self._stoppable(kind, self.team)
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other team")
        theirs = self._stoppable(kind, other_team)
        redis = RecordingRedis()

        with mock.patch("posthog.plugins.plugin_server_api.get_client", return_value=redis):
            assert disable(mine, team_id=self.team.pk) is True
            assert disable(mine, team_id=self.team.pk) is False
            assert disable(theirs, team_id=self.team.pk) is False

        assert not running([self.team.pk])
        assert running([other_team.pk])
        expected = (
            ("reload-hog-functions", {"teamId": self.team.pk, "hogFunctionIds": [mine]})
            if kind == "hog_function"
            else ("reload-plugins", "")
        )
        assert expected in redis.published
