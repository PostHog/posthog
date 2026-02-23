from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.client.execute import (
    _KILL_SWITCH_EXEMPT_USERS,
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
            ("invalid_string", "garbage", KillSwitchLevel.OFF),
            ("empty_string", "", KillSwitchLevel.OFF),
            ("bool_false", False, KillSwitchLevel.OFF),
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


class TestKillSwitchExemptUsers:
    @parameterized.expand(
        [
            ("batch_export", ClickHouseUser.BATCH_EXPORT),
            ("migrations", ClickHouseUser.MIGRATIONS),
            ("ops", ClickHouseUser.OPS),
        ]
    )
    def test_exempt_users(self, _name: str, user: ClickHouseUser):
        assert user in _KILL_SWITCH_EXEMPT_USERS

    @parameterized.expand(
        [
            ("app", ClickHouseUser.APP),
            ("api", ClickHouseUser.API),
            ("default", ClickHouseUser.DEFAULT),
            ("cache_warmup", ClickHouseUser.CACHE_WARMUP),
            ("max_ai", ClickHouseUser.MAX_AI),
            ("endpoints", ClickHouseUser.ENDPOINTS),
        ]
    )
    def test_non_exempt_users(self, _name: str, user: ClickHouseUser):
        assert user not in _KILL_SWITCH_EXEMPT_USERS


class TestKillSwitchResourceLimits:
    @parameterized.expand(
        [
            ("light_caps_execution_time", KillSwitchLevel.LIGHT, {"max_execution_time": 300}, 30),
            ("light_keeps_lower_execution_time", KillSwitchLevel.LIGHT, {"max_execution_time": 10}, 10),
            ("full_caps_execution_time", KillSwitchLevel.FULL, {"max_execution_time": 300}, 15),
            ("full_keeps_lower_execution_time", KillSwitchLevel.FULL, {"max_execution_time": 5}, 5),
        ]
    )
    def test_min_capping_preserves_lower_existing_value(
        self, _name: str, level: KillSwitchLevel, existing: dict, expected_time: int
    ):
        core_settings = {**default_settings(), **existing}
        overrides = _KILL_SWITCH_SETTINGS[level]
        core_settings.update({k: min(core_settings.get(k, v), v) for k, v in overrides.items()})

        assert core_settings["max_execution_time"] == expected_time

    @parameterized.expand(
        [
            ("light_applies", KillSwitchLevel.LIGHT, ClickHouseUser.APP, True),
            ("full_applies", KillSwitchLevel.FULL, ClickHouseUser.API, True),
            ("off_no_change", KillSwitchLevel.OFF, ClickHouseUser.APP, False),
            ("batch_export_exempt", KillSwitchLevel.FULL, ClickHouseUser.BATCH_EXPORT, False),
            ("migrations_exempt", KillSwitchLevel.FULL, ClickHouseUser.MIGRATIONS, False),
            ("ops_exempt", KillSwitchLevel.LIGHT, ClickHouseUser.OPS, False),
        ]
    )
    def test_limits_applied_based_on_level_and_user(
        self, _name: str, level: KillSwitchLevel, ch_user: ClickHouseUser, should_apply: bool
    ):
        core_settings = {**default_settings()}

        if level != KillSwitchLevel.OFF and ch_user not in _KILL_SWITCH_EXEMPT_USERS:
            overrides = _KILL_SWITCH_SETTINGS[level]
            core_settings.update({k: min(core_settings.get(k, v), v) for k, v in overrides.items()})

        if should_apply:
            overrides = _KILL_SWITCH_SETTINGS[level]
            for key, value in overrides.items():
                assert core_settings[key] == value
        else:
            assert "max_result_rows" not in core_settings

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


class TestKillSwitchHedgedRequests:
    @parameterized.expand(
        [
            ("off_enabled", KillSwitchLevel.OFF, "1"),
            ("light_disabled", KillSwitchLevel.LIGHT, "0"),
            ("full_disabled", KillSwitchLevel.FULL, "0"),
        ]
    )
    def test_hedged_requests_for_online_app(self, _name: str, level: KillSwitchLevel, expected: str):
        settings: dict = {}
        workload = Workload.ONLINE
        ch_user = ClickHouseUser.APP

        if workload == Workload.OFFLINE:
            settings["use_hedged_requests"] = "0"
        elif workload == Workload.ONLINE and ch_user == ClickHouseUser.APP:
            if level != KillSwitchLevel.OFF:
                settings["use_hedged_requests"] = "0"
            else:
                settings["use_hedged_requests"] = "1"

        assert settings["use_hedged_requests"] == expected


class TestKillSwitchConcurrencyReduction:
    @parameterized.expand(
        [
            ("light_20_to_10", KillSwitchLevel.LIGHT, 20, 10),
            ("light_6_to_3", KillSwitchLevel.LIGHT, 6, 3),
            ("light_3_to_1", KillSwitchLevel.LIGHT, 3, 1),
            ("light_2_to_1", KillSwitchLevel.LIGHT, 2, 1),
            ("light_1_to_1", KillSwitchLevel.LIGHT, 1, 1),
            ("full_20_to_5", KillSwitchLevel.FULL, 20, 5),
            ("full_6_to_1", KillSwitchLevel.FULL, 6, 1),
            ("full_3_to_1", KillSwitchLevel.FULL, 3, 1),
            ("full_2_to_1", KillSwitchLevel.FULL, 2, 1),
            ("full_1_to_1", KillSwitchLevel.FULL, 1, 1),
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
