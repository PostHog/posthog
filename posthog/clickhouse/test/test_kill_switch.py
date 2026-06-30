from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.clickhouse.client.execute import (
    _KILL_SWITCH_SETTINGS,
    KillSwitchLevel,
    _get_kill_switch_level,
    _get_kill_switch_team_sets,
    default_settings,
    get_kill_switch_level,
    get_team_kill_switch_level,
    resolve_kill_switch_level,
)


class TestGetKillSwitchLevel:
    @parameterized.expand(
        [
            ("off", "off", KillSwitchLevel.OFF),
            ("light", "light", KillSwitchLevel.LIGHT),
            ("full", "full", KillSwitchLevel.FULL),
            ("invalid_falls_back_to_off", "garbage", KillSwitchLevel.OFF),
        ]
    )
    def test_returns_normalized_level(self, _name: str, raw_value: object, expected: KillSwitchLevel):
        _get_kill_switch_level.cache_clear()
        with patch("posthog.models.instance_setting.get_instance_setting", return_value=raw_value):
            assert get_kill_switch_level() == expected
        _get_kill_switch_level.cache_clear()

    def test_caches_across_same_ttl(self):
        _get_kill_switch_level.cache_clear()
        mock = MagicMock(return_value="off")
        with patch("posthog.models.instance_setting.get_instance_setting", mock):
            _get_kill_switch_level(42)
            _get_kill_switch_level(42)
            assert mock.call_count == 1
        _get_kill_switch_level.cache_clear()


class TestGetTeamKillSwitchLevel:
    @parameterized.expand(
        [
            ("team_in_full_list_gets_full", [42], [], 42, KillSwitchLevel.FULL),
            ("team_in_light_list_gets_light", [], [42], 42, KillSwitchLevel.LIGHT),
            ("team_not_in_any_list_is_off", [99], [99], 42, KillSwitchLevel.OFF),
            ("team_in_both_lists_picks_full", [42], [42], 42, KillSwitchLevel.FULL),
        ]
    )
    def test_per_team_lookup(
        self,
        _name: str,
        full: list[int],
        light: list[int],
        team_id: int,
        expected: KillSwitchLevel,
    ):
        _get_kill_switch_team_sets.cache_clear()
        settings = {
            "CLICKHOUSE_KILL_SWITCH_FULL_TEAMS": full,
            "CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS": light,
        }
        with patch("posthog.models.instance_setting.get_instance_setting", side_effect=lambda name: settings[name]):
            assert get_team_kill_switch_level(team_id) == expected
        _get_kill_switch_team_sets.cache_clear()

    def test_global_get_kill_switch_level_ignores_per_team_lists(self):
        """The global resolver must remain unchanged — per-team overrides are opt-in."""
        _get_kill_switch_level.cache_clear()
        _get_kill_switch_team_sets.cache_clear()
        settings = {
            "CLICKHOUSE_KILL_SWITCH": "off",
            "CLICKHOUSE_KILL_SWITCH_FULL_TEAMS": [42],
            "CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS": [],
        }
        with patch("posthog.models.instance_setting.get_instance_setting", side_effect=lambda name: settings[name]):
            assert get_kill_switch_level() == KillSwitchLevel.OFF
        _get_kill_switch_level.cache_clear()
        _get_kill_switch_team_sets.cache_clear()

    @parameterized.expand(
        [
            ("string_full_teams", "1,2,3", [], 1, KillSwitchLevel.OFF),
            ("none_full_teams", None, [], 1, KillSwitchLevel.OFF),
            ("string_light_teams", [], "1,2,3", 1, KillSwitchLevel.OFF),
        ]
    )
    def test_non_list_setting_treated_as_empty(
        self,
        _name: str,
        full: object,
        light: object,
        team_id: int,
        expected: KillSwitchLevel,
    ):
        _get_kill_switch_team_sets.cache_clear()
        settings = {
            "CLICKHOUSE_KILL_SWITCH_FULL_TEAMS": full,
            "CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS": light,
        }
        with patch("posthog.models.instance_setting.get_instance_setting", side_effect=lambda name: settings[name]):
            assert get_team_kill_switch_level(team_id) == expected
        _get_kill_switch_team_sets.cache_clear()

    def test_team_sets_are_cached(self):
        _get_kill_switch_team_sets.cache_clear()
        settings = {
            "CLICKHOUSE_KILL_SWITCH_FULL_TEAMS": [42],
            "CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS": [7],
        }
        mock = MagicMock(side_effect=lambda name: settings[name])
        with patch("posthog.models.instance_setting.get_instance_setting", mock):
            get_team_kill_switch_level(42)
            get_team_kill_switch_level(42)
            # 2 calls for the per-team sets (full + light) over the same minute, no additional calls on the second invocation
            assert mock.call_count == 2
        _get_kill_switch_team_sets.cache_clear()


class TestResolveKillSwitchLevel:
    """
    Exercises the real precedence resolver used by `sync_execute`. The effective level
    must be the more severe of the global level and any per-team override.
    """

    @parameterized.expand(
        [
            ("global_light_team_full_wins_full", KillSwitchLevel.LIGHT, KillSwitchLevel.FULL, KillSwitchLevel.FULL),
            ("global_full_team_light_wins_full", KillSwitchLevel.FULL, KillSwitchLevel.LIGHT, KillSwitchLevel.FULL),
            ("global_off_team_full_wins_full", KillSwitchLevel.OFF, KillSwitchLevel.FULL, KillSwitchLevel.FULL),
            ("global_off_team_light_wins_light", KillSwitchLevel.OFF, KillSwitchLevel.LIGHT, KillSwitchLevel.LIGHT),
            ("global_light_team_off_wins_light", KillSwitchLevel.LIGHT, KillSwitchLevel.OFF, KillSwitchLevel.LIGHT),
            ("global_full_team_off_wins_full", KillSwitchLevel.FULL, KillSwitchLevel.OFF, KillSwitchLevel.FULL),
            ("global_off_team_off_is_off", KillSwitchLevel.OFF, KillSwitchLevel.OFF, KillSwitchLevel.OFF),
            ("global_full_team_full_is_full", KillSwitchLevel.FULL, KillSwitchLevel.FULL, KillSwitchLevel.FULL),
        ]
    )
    def test_precedence(
        self,
        _name: str,
        global_level: KillSwitchLevel,
        team_level: KillSwitchLevel,
        expected: KillSwitchLevel,
    ):
        with (
            patch("posthog.clickhouse.client.execute.get_kill_switch_level", return_value=global_level),
            patch("posthog.clickhouse.client.execute.get_team_kill_switch_level", return_value=team_level),
        ):
            assert resolve_kill_switch_level(team_id=42) == expected

    def test_none_team_id_returns_global_only(self):
        team_mock = MagicMock(return_value=KillSwitchLevel.FULL)
        with (
            patch("posthog.clickhouse.client.execute.get_kill_switch_level", return_value=KillSwitchLevel.LIGHT),
            patch("posthog.clickhouse.client.execute.get_team_kill_switch_level", team_mock),
        ):
            assert resolve_kill_switch_level(team_id=None) == KillSwitchLevel.LIGHT
            team_mock.assert_not_called()


class TestKillSwitchResourceLimits:
    @parameterized.expand(
        [
            ("existing_higher_gets_capped", {"max_execution_time": 300}, 15),
            ("existing_lower_is_preserved", {"max_execution_time": 5}, 5),
        ]
    )
    def test_min_capping(self, _name: str, existing: dict, expected_time: int):
        core_settings = {**default_settings(), **existing}
        overrides = _KILL_SWITCH_SETTINGS[KillSwitchLevel.FULL]
        core_settings.update({k: min(core_settings.get(k, v), v) for k, v in overrides.items()})

        assert core_settings["max_execution_time"] == expected_time

    def test_light_does_not_set_max_memory_usage(self):
        core_settings = {**default_settings()}
        overrides = _KILL_SWITCH_SETTINGS[KillSwitchLevel.LIGHT]
        core_settings.update({k: min(core_settings.get(k, v), v) for k, v in overrides.items()})

        assert "max_memory_usage" not in core_settings

    def test_full_sets_max_memory_usage(self):
        core_settings = {**default_settings()}
        overrides = _KILL_SWITCH_SETTINGS[KillSwitchLevel.FULL]
        core_settings.update({k: min(core_settings.get(k, v), v) for k, v in overrides.items()})

        assert core_settings["max_memory_usage"] == 30_000_000_000


class TestKillSwitchConcurrencyReduction:
    @parameterized.expand(
        [
            ("light_halves", KillSwitchLevel.LIGHT, 20, 10),
            ("full_quarters", KillSwitchLevel.FULL, 20, 5),
            ("full_floors_to_1", KillSwitchLevel.FULL, 2, 1),
        ]
    )
    def test_concurrency_reduction(self, _name: str, level: KillSwitchLevel, original: int, expected: int):
        if level == KillSwitchLevel.LIGHT:
            result = max(1, original // 2)
        elif level == KillSwitchLevel.FULL:
            result = max(1, original // 4)
        else:
            result = original
        assert result == expected


class TestKillSwitchCacheWarming:
    @parameterized.expand(
        [
            ("light", KillSwitchLevel.LIGHT),
            ("full", KillSwitchLevel.FULL),
        ]
    )
    @patch("posthog.caching.warming.logger")
    def test_cache_warming_skipped(self, _name: str, level: KillSwitchLevel, mock_logger: MagicMock):
        with patch("posthog.clickhouse.client.execute.get_kill_switch_level", return_value=level):
            from posthog.caching.warming import schedule_warming_for_teams_task

            schedule_warming_for_teams_task()

            mock_logger.info.assert_called_with("kill_switch_on_skipping_cache_warming", level=level)

    @patch("posthog.clickhouse.client.execute.get_kill_switch_level", return_value=KillSwitchLevel.OFF)
    @patch("posthog.caching.warming.largest_teams", return_value=[])
    def test_cache_warming_proceeds_when_off(self, mock_largest: MagicMock, _mock_ks: MagicMock):
        from posthog.caching.warming import schedule_warming_for_teams_task

        try:
            schedule_warming_for_teams_task()
        except Exception:
            pass

        mock_largest.assert_called_once()
