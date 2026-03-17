from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql.constants import HogQLGlobalSettings, get_default_hogql_global_settings

from posthog.clickhouse.client.execute import default_settings
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

    def test_injects_setting_for_listed_team(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            core_settings: dict = {
                **default_settings(),
            }
            if is_enable_analyzer_team(2):
                core_settings.setdefault("allow_experimental_analyzer", 1)

            assert core_settings["allow_experimental_analyzer"] == 1

    def test_does_not_inject_for_unlisted_team(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            core_settings: dict = {
                **default_settings(),
            }
            if is_enable_analyzer_team(99):
                core_settings.setdefault("allow_experimental_analyzer", 1)

            assert "allow_experimental_analyzer" not in core_settings

    def test_does_not_override_explicit_zero(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            core_settings: dict = {
                **default_settings(),
                "allow_experimental_analyzer": 0,
            }
            if is_enable_analyzer_team(2):
                core_settings.setdefault("allow_experimental_analyzer", 1)

            assert core_settings["allow_experimental_analyzer"] == 0


class TestGetDefaultHogQLGlobalSettings:
    def setup_method(self):
        _get_enable_analyzer_teams.cache_clear()

    def teardown_method(self):
        _get_enable_analyzer_teams.cache_clear()

    def test_sets_enable_analyzer_for_listed_team(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            settings = get_default_hogql_global_settings(team_id=2)
            assert settings.allow_experimental_analyzer is True

    def test_no_override_for_unlisted_team(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            settings = get_default_hogql_global_settings(team_id=99)
            assert settings.allow_experimental_analyzer is None

    def test_does_not_override_explicit_false(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            base = HogQLGlobalSettings(allow_experimental_analyzer=False)
            settings = get_default_hogql_global_settings(team_id=2, base=base)
            assert settings.allow_experimental_analyzer is False

    def test_preserves_base_settings(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            base = HogQLGlobalSettings(max_execution_time=120)
            settings = get_default_hogql_global_settings(team_id=2, base=base)
            assert settings.max_execution_time == 120
            assert settings.allow_experimental_analyzer is True

    def test_none_team_id(self):
        with patch(INSTANCE_SETTING_PATH, return_value=[2]):
            settings = get_default_hogql_global_settings(team_id=None)
            assert settings.allow_experimental_analyzer is None
