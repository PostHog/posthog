import pytest
from unittest import mock

from posthog.temporal.common import client as client_module
from posthog.temporal.common.client import _resolve_temporal_port, async_connect, connect


@pytest.mark.parametrize(
    "port,expected",
    [
        (7233, 7233),
        ("7233", 7233),
        ("  7233  ", 7233),
        (1, 1),
        (65535, 65535),
    ],
)
def test_resolve_temporal_port_accepts_valid_values(port, expected):
    assert _resolve_temporal_port(port) == expected


@pytest.mark.parametrize(
    "port",
    ["", "  ", "not-a-port", "7233a", "0", "-1", "65536", "70000"],
)
def test_resolve_temporal_port_rejects_invalid_values(port):
    with pytest.raises(ValueError, match="Invalid Temporal port"):
        _resolve_temporal_port(port)


async def test_connect_rejects_bad_port_before_reaching_bridge():
    # The worker path (create_worker -> connect) must fail with a named error, not the bridge's opaque one.
    with mock.patch.object(client_module.Client, "connect", new=mock.AsyncMock()) as bridge_connect:
        with pytest.raises(ValueError, match="Invalid Temporal port 'not-a-port'"):
            await connect("temporal", "not-a-port", "default", settings=None)

    bridge_connect.assert_not_called()


async def test_connect_builds_target_from_valid_port():
    with mock.patch.object(client_module.Client, "connect", new=mock.AsyncMock()) as bridge_connect:
        await connect("temporal", "7233", "default", settings=None)

    assert bridge_connect.call_args.args[0] == "temporal:7233"


async def test_async_connect_surfaces_bad_port(settings):
    # The schedule-registration path (init_schedules -> async_connect) fails with a named error.
    settings.TEMPORAL_PORT = "not-a-port"
    with mock.patch.object(client_module.Client, "connect", new=mock.AsyncMock()):
        with pytest.raises(ValueError, match="Invalid Temporal port"):
            await async_connect()
