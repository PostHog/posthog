from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.constants import HogQLGlobalSettings, get_default_hogql_global_settings

from posthog.clickhouse.client.execute import sync_execute
from posthog.settings.data_stores import _get_enable_analyzer_teams, is_enable_analyzer_team

INSTANCE_SETTING_PATH = "posthog.models.instance_setting.get_instance_setting"


class TestIsEnableAnalyzerTeam:
    def setup_method(self):
        _get_enable_analyzer_teams.cache_clear()

    def teardown_method(self):
        _get_enable_analyzer_teams.cache_clear()

    @parameterized.expand(
        [
            ("listed_team", [2, 5, 10], 2, True),
            ("unlisted_team", [2, 5, 10], 3, False),
            ("none_team", [2, 5, 10], None, False),
            ("empty_setting", [], 2, False),
            ("single_team", [7], 7, True),
        ]
    )
    def test_returns_expected(self, _name: str, setting_value: list[int], team_id: int | None, expected: bool):
        with patch(INSTANCE_SETTING_PATH, return_value=setting_value):
            assert is_enable_analyzer_team(team_id) == expected


class TestSyncExecuteEnableAnalyzer:
    def setup_method(self):
        _get_enable_analyzer_teams.cache_clear()

    def teardown_method(self):
        _get_enable_analyzer_teams.cache_clear()

    @parameterized.expand(
        [
            ("injects_for_listed_team", [2], 2, None, 1),
            ("skips_for_unlisted_team", [2], 99, None, None),
            ("does_not_override_explicit_zero", [2], 2, 0, 0),
        ]
    )
    def test_analyzer_setting(self, _name, allowed_teams, team_id, explicit_value, expected):
        mock_client = MagicMock()
        caller_settings = {"enable_analyzer": explicit_value} if explicit_value is not None else None

        with patch(INSTANCE_SETTING_PATH, return_value=allowed_teams):
            sync_execute("SELECT 1", settings=caller_settings, team_id=team_id, flush=False, sync_client=mock_client)

        actual = mock_client.__enter__.return_value.execute.call_args[1]["settings"].get("enable_analyzer")
        assert actual == expected


class TestGetDefaultHogQLGlobalSettings:
    def setup_method(self):
        _get_enable_analyzer_teams.cache_clear()

    def teardown_method(self):
        _get_enable_analyzer_teams.cache_clear()

    def test_sets_enable_analyzer_for_listed_team(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            settings = get_default_hogql_global_settings(team_id=2)
            assert settings.enable_analyzer is True

    def test_no_override_for_unlisted_team(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            settings = get_default_hogql_global_settings(team_id=99)
            assert settings.enable_analyzer is None

    def test_does_not_override_explicit_false(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            base = HogQLGlobalSettings(enable_analyzer=False)
            settings = get_default_hogql_global_settings(team_id=2, base=base)
            assert settings.enable_analyzer is False

    def test_preserves_base_settings(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            base = HogQLGlobalSettings(max_execution_time=120)
            settings = get_default_hogql_global_settings(team_id=2, base=base)
            assert settings.max_execution_time == 120
            assert settings.enable_analyzer is True

    def test_none_team_id(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            settings = get_default_hogql_global_settings(team_id=None)
            assert settings.enable_analyzer is None
