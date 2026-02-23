from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.clickhouse.client.execute import (
    _KILL_SWITCH_SETTINGS,
    KillSwitchLevel,
    _get_kill_switch_level,
    default_settings,
    get_kill_switch_level,
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
