import xml.etree.ElementTree as ET
from pathlib import Path

from posthog.hogql.constants import HogQLGlobalSettings, get_default_hogql_global_settings

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestClickHouseProfileDefaults:
    def test_docker_profiles_do_not_explicitly_override_analyzer(self):
        for config_path in (
            REPO_ROOT / "docker/clickhouse/users.xml",
            REPO_ROOT / "docker/clickhouse/users-dev.xml",
        ):
            root = ET.parse(config_path).getroot()
            # ClickHouse 26.3 enables the analyzer by default, but explicitly setting it in the
            # profile is propagated to remote sessions and breaks distributed system.clusters reads.
            assert root.findtext("./profiles/default/enable_analyzer") is None
            assert root.findtext("./profiles/default/allow_experimental_analyzer") is None


class TestGetDefaultHogQLGlobalSettings:
    def test_does_not_inject_query_level_analyzer_setting(self):
        settings = get_default_hogql_global_settings(team_id=None)
        assert settings.enable_analyzer is None

    def test_preserves_base_settings(self):
        base = HogQLGlobalSettings(max_execution_time=120)
        settings = get_default_hogql_global_settings(team_id=2, base=base)
        assert settings.max_execution_time == 120
        assert settings.enable_analyzer is None
