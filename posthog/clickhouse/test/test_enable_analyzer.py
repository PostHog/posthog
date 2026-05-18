import xml.etree.ElementTree as ET
from pathlib import Path

from unittest.mock import MagicMock

from posthog.hogql.constants import HogQLGlobalSettings, get_default_hogql_global_settings

from posthog.clickhouse.client.execute import default_settings, sync_execute
from posthog.temporal.common.clickhouse import ClickHouseClient

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestSyncExecuteEnableAnalyzer:
    def test_default_settings_enable_analyzer(self):
        assert default_settings()["enable_analyzer"] == 1

    def test_sync_execute_always_enables_analyzer(self):
        mock_client = MagicMock()

        sync_execute("SELECT 1", settings={"enable_analyzer": 0}, flush=False, sync_client=mock_client)

        actual = mock_client.__enter__.return_value.execute.call_args[1]["settings"].get("enable_analyzer")
        assert actual == 1


class TestClickHouseProfileDefaults:
    def test_docker_profiles_enable_analyzer(self):
        for config_path in (
            REPO_ROOT / "docker/clickhouse/users.xml",
            REPO_ROOT / "docker/clickhouse/users-dev.xml",
        ):
            root = ET.parse(config_path).getroot()
            assert root.findtext("./profiles/default/enable_analyzer") == "1"


class TestGetDefaultHogQLGlobalSettings:
    def test_does_not_inject_query_level_analyzer_setting(self):
        settings = get_default_hogql_global_settings(team_id=None)
        assert settings.enable_analyzer is None

    def test_preserves_base_settings(self):
        base = HogQLGlobalSettings(max_execution_time=120)
        settings = get_default_hogql_global_settings(team_id=2, base=base)
        assert settings.max_execution_time == 120
        assert settings.enable_analyzer is None

    def test_preserves_explicit_query_level_analyzer_setting(self):
        base = HogQLGlobalSettings(enable_analyzer=True)
        settings = get_default_hogql_global_settings(team_id=2, base=base)
        assert settings.enable_analyzer is True


class TestTemporalClickHouseClientEnableAnalyzer:
    def test_client_always_enables_analyzer(self):
        client = ClickHouseClient(enable_analyzer=0)
        assert client.params["enable_analyzer"] == 1
