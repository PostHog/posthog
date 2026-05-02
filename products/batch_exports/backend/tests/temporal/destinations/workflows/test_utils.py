import asyncio

import pytest
from unittest.mock import MagicMock, patch

from aiohttp.client_proto import ResponseHandler

from products.batch_exports.backend.temporal.destinations.workflows_batch_export import (
    RecyclingTCPConnector,
    Tracking,
    TrackingAddSet,
)


def test_tracking_increase_increments_count():
    t = Tracking()

    assert t.count == 0
    t.increment()
    assert t.count == 1


def test_tracking_add_set_tracks_times_added():
    s = TrackingAddSet()

    class Element:
        pass

    element = Element()

    s.add(element)
    assert element.__tracking__.count == 1  # type: ignore

    s.remove(element)
    assert element.__tracking__.count == 1  # type: ignore

    s.add(element)
    assert element.__tracking__.count == 2  # type: ignore


@pytest.mark.parametrize(
    "count,recycle_requests,expect_force_close",
    [
        (2, 1, True),
        (1, 1, False),
        (1, 0, True),
    ],
)
@patch.object(RecyclingTCPConnector, "__init__", lambda self, *a, **kw: None)
def test_recycling_connector_force_closes_when_request_threshold_exceeded(count, recycle_requests, expect_force_close):
    connector = RecyclingTCPConnector.__new__(RecyclingTCPConnector)
    connector._recycle_requests = recycle_requests
    connector._recycle_timeout = None

    protocol = MagicMock()
    protocol.__tracking__ = Tracking()
    protocol.__tracking__.count = count

    with patch("aiohttp.TCPConnector._release"):
        connector._release(MagicMock(), protocol)

    assert protocol.force_close.called is expect_force_close


@pytest.mark.parametrize(
    "elapsed,recycle_timeout,expect_force_close",
    [
        (11, 10, True),
        (10, 10, False),
        (5, 10, False),
    ],
)
@patch.object(RecyclingTCPConnector, "__init__", lambda self, *a, **kw: None)
def test_recycling_connector_force_closes_when_timeout_exceeded(elapsed, recycle_timeout, expect_force_close):
    connector = RecyclingTCPConnector.__new__(RecyclingTCPConnector)
    connector._recycle_requests = None
    connector._recycle_timeout = recycle_timeout

    protocol = MagicMock()
    tracking = Tracking()
    tracking.first_added = 100.0
    protocol.__tracking__ = tracking

    with (
        patch(
            "products.batch_exports.backend.temporal.destinations.workflows_batch_export.time.monotonic",
            return_value=100.0 + elapsed,
        ),
        patch("aiohttp.TCPConnector._release"),
    ):
        connector._release(MagicMock(), protocol)

    assert protocol.force_close.called is expect_force_close


@patch.object(RecyclingTCPConnector, "__init__", lambda self, *a, **kw: None)
def test_recycling_connector_skips_protocol_without_tracking():
    connector = RecyclingTCPConnector.__new__(RecyclingTCPConnector)
    connector._recycle_requests = 1
    connector._recycle_timeout = None

    protocol = MagicMock(spec=[])  # no __tracking__ attribute

    with patch("aiohttp.TCPConnector._release") as super_release:
        connector._release(MagicMock(), protocol)

    super_release.assert_called_once()
    assert not hasattr(protocol, "force_close") or not protocol.force_close.called


async def test_response_handler_can_be_tracked():
    handler = ResponseHandler(asyncio.get_running_loop())
    assert hasattr(handler, "__dict__"), "no longer can be monkeypatched"
    assert not hasattr(handler, "__tracking__"), "must update tracking attribute"
