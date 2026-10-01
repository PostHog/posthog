from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import patch

from posthog.clickhouse.query_router import config
from posthog.clickhouse.query_router.config import CLASS_POLICIES, Pool, PoolBounds, QueryClass, RouterMode

DEFAULT_SETTINGS: dict[str, Any] = {
    "QUERY_ROUTER_MODE": "enforce",
    "QUERY_ROUTER_ENFORCE": "offline:4",
    "QUERY_ROUTER_OFFLINE_FLOOR": 10,
    "QUERY_ROUTER_OFFLINE_CEILING": 20,
    "QUERY_ROUTER_ONLINE_FLOOR": 30,
    "QUERY_ROUTER_ONLINE_CEILING": 40,
}


@pytest.fixture(autouse=True)
def fresh_settings() -> Iterator[None]:
    config._load_settings.cache_clear()
    with patch.object(config, "TEST", False):
        yield
    config._load_settings.cache_clear()


def test_share_never_rises_with_the_class_number() -> None:
    shares = [CLASS_POLICIES[query_class].share for query_class in sorted(QueryClass)]
    assert shares == sorted(shares, reverse=True)


def test_enforce_applies_only_to_the_listed_pool_and_class() -> None:
    with patch("posthog.models.instance_setting.get_instance_settings", return_value=DEFAULT_SETTINGS):
        assert config.get_mode(Pool.OFFLINE, QueryClass.BACKGROUND) == RouterMode.ENFORCE
        assert config.get_mode(Pool.OFFLINE, QueryClass.API) == RouterMode.OBSERVE
        assert config.get_mode(Pool.ONLINE, QueryClass.BACKGROUND) == RouterMode.OBSERVE
        assert config.get_pool_bounds(Pool.ONLINE) == PoolBounds(floor=30, ceiling=40)


@pytest.mark.parametrize(
    "read",
    [
        pytest.param({"side_effect": RuntimeError("database is down")}, id="settings unreadable"),
        pytest.param({"return_value": {**DEFAULT_SETTINGS, "QUERY_ROUTER_MODE": "enforced"}}, id="mistyped mode"),
        pytest.param({"return_value": {**DEFAULT_SETTINGS, "QUERY_ROUTER_ENFORCE": "offline:9"}}, id="unknown class"),
    ],
)
def test_bad_settings_turn_the_router_off_and_are_read_once_a_minute(read: dict[str, Any]) -> None:
    with patch("posthog.models.instance_setting.get_instance_settings", **read) as get_instance_settings:
        modes = [config.get_mode(Pool.OFFLINE, QueryClass.BACKGROUND) for _ in range(3)]

    assert modes == [RouterMode.OFF] * 3
    assert get_instance_settings.call_count == 1
