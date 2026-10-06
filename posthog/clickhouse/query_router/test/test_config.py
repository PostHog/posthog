from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from prometheus_client import REGISTRY

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_router import config
from posthog.clickhouse.query_router.config import Pool, QueryClass, RouterMode
from posthog.clickhouse.query_tagging import tags_context
from posthog.clickhouse.workload import Workload

DEFAULT_SETTINGS: dict[str, Any] = {
    "QUERY_ROUTER_MODE": "enforce",
    "QUERY_ROUTER_ENFORCE": "offline:4",
    "QUERY_ROUTER_OFFLINE_LIMIT": 20,
    "QUERY_ROUTER_ONLINE_LIMIT": 40,
}


@pytest.fixture(autouse=True)
def fresh_settings() -> Iterator[None]:
    config._load_settings.cache_clear()
    with patch.object(config, "TEST", False):
        yield
    config._load_settings.cache_clear()


def test_enforce_applies_only_to_the_listed_pool_and_class() -> None:
    with patch("posthog.models.instance_setting.get_instance_settings", return_value=DEFAULT_SETTINGS):
        settings = config.get_settings()

    assert settings.mode_for(Pool.OFFLINE, QueryClass.BACKGROUND) == RouterMode.ENFORCE
    assert settings.mode_for(Pool.OFFLINE, QueryClass.API) == RouterMode.OBSERVE
    assert settings.mode_for(Pool.ONLINE, QueryClass.BACKGROUND) == RouterMode.OBSERVE
    assert settings.limits[Pool.ONLINE] == 40


@pytest.mark.parametrize(
    "read, expected_mode",
    [
        pytest.param({"side_effect": RuntimeError("database is down")}, RouterMode.ERROR, id="settings unreadable"),
        pytest.param(
            {"return_value": {**DEFAULT_SETTINGS, "QUERY_ROUTER_MODE": "enforced"}},
            RouterMode.ERROR,
            id="mistyped mode",
        ),
        pytest.param(
            {"return_value": {**DEFAULT_SETTINGS, "QUERY_ROUTER_OFFLINE_LIMIT": 0}}, RouterMode.ERROR, id="zero limit"
        ),
        pytest.param(
            {"return_value": {**DEFAULT_SETTINGS, "QUERY_ROUTER_ENFORCE": "offline"}},
            RouterMode.ERROR,
            id="enforce item without a class",
        ),
        pytest.param(
            {"return_value": {**DEFAULT_SETTINGS, "QUERY_ROUTER_ENFORCE": "offline:9"}},
            RouterMode.ERROR,
            id="enforce item with an unknown class",
        ),
        pytest.param(
            {"return_value": {**DEFAULT_SETTINGS, "QUERY_ROUTER_MODE": "off", "QUERY_ROUTER_OFFLINE_LIMIT": 0}},
            RouterMode.OFF,
            id="intentional off ignores unused limits",
        ),
    ],
)
def test_bad_settings_fail_open_visibly_and_are_read_once_a_minute(
    read: dict[str, Any], expected_mode: RouterMode
) -> None:
    labels = {"pool": "offline", "query_class": "background", "outcome": "error"}
    before = REGISTRY.get_sample_value("posthog_query_router_admissions_total", labels) or 0
    client = MagicMock()
    client.execute.return_value = [(1,)]
    with (
        patch("posthog.models.instance_setting.get_instance_settings", **read) as get_instance_settings,
        patch("posthog.clickhouse.client.execute.get_client_from_pool", return_value=client),
        tags_context(kind="celery", id="posthog.tasks.example"),
    ):
        client.__enter__.return_value = client
        for _ in range(3):
            assert config.get_settings().mode_for(Pool.OFFLINE, QueryClass.BACKGROUND) == expected_mode
            assert sync_execute("SELECT 1", flush=False, workload=Workload.OFFLINE) == [(1,)]

    assert get_instance_settings.call_count == 1
    after = REGISTRY.get_sample_value("posthog_query_router_admissions_total", labels) or 0
    assert after - before == (0 if expected_mode == RouterMode.OFF else 3)
