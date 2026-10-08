import asyncio
from typing import Any, NamedTuple

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from products.data_warehouse.backend import s3 as s3_module

_S3 = "products.data_warehouse.backend.s3"


class _ClientPair(NamedTuple):
    first: Any
    second: Any


def _filesystem_factory() -> MagicMock:
    def build(**kwargs):
        fs = MagicMock()
        fs.set_session = AsyncMock()
        fs.storage_options = kwargs
        return fs

    return MagicMock(side_effect=build)


class TestSharedAsyncClientPerLoop:
    # An asynchronous S3FileSystem is bound to the loop that opened its session. Handing one loop's
    # client to another raises "Event loop is closed" from deep inside aiobotocore; handing every
    # call a new client rebuilds the session and resolves credentials each time.

    @pytest.fixture(autouse=True)
    def _cloud_setup_with_empty_registry(self):
        s3_module._LOOP_S3_CLIENTS.clear()
        with override_settings(USE_LOCAL_SETUP=False):
            yield
        s3_module._LOOP_S3_CLIENTS.clear()

    @patch(f"{_S3}.boto_proxy_config_kwargs", return_value={})
    def test_calls_on_one_loop_share_a_client_and_calls_on_another_loop_do_not(self, _proxy: MagicMock) -> None:
        async def two_uses() -> _ClientPair:
            async with s3_module.aget_s3_client() as first, s3_module.aget_s3_client() as second:
                return _ClientPair(first, second)

        with patch(f"{_S3}.s3fs.S3FileSystem", _filesystem_factory()) as filesystem:
            first_loop = asyncio.run(two_uses())
            second_loop = asyncio.run(two_uses())

        assert first_loop[0] is first_loop[1]
        assert second_loop[0] is second_loop[1]
        assert first_loop[0] is not second_loop[0]
        assert filesystem.call_count == 2
        assert all(
            call.kwargs["asynchronous"] and call.kwargs["skip_instance_cache"] for call in filesystem.call_args_list
        )

    @patch(f"{_S3}.boto_proxy_config_kwargs", return_value={})
    def test_each_endpoint_gets_its_own_shared_client(self, _proxy: MagicMock) -> None:
        # The proxy bypass keys on the endpoint, so a client for one must never serve another.
        async def two_endpoints() -> _ClientPair:
            async with (
                s3_module.aget_s3_client() as default,
                s3_module.aget_s3_client(endpoint_url="https://other.example.com") as other,
            ):
                return _ClientPair(default, other)

        with patch(f"{_S3}.s3fs.S3FileSystem", _filesystem_factory()):
            default, other = asyncio.run(two_endpoints())

        assert default is not other
        assert other.storage_options["endpoint_url"] == "https://other.example.com"
        assert "endpoint_url" not in default.storage_options

    @patch(f"{_S3}.boto_proxy_config_kwargs", return_value={})
    def test_a_fresh_instance_is_never_shared_and_is_closed(self, _proxy: MagicMock) -> None:
        async def use_fresh() -> Any:
            async with s3_module.aget_s3_client(fresh_instance=True) as fs:
                return fs

        with patch(f"{_S3}.s3fs.S3FileSystem", _filesystem_factory()):
            fresh = asyncio.run(use_fresh())

        assert len(s3_module._LOOP_S3_CLIENTS) == 0
        fresh._s3creator.__aexit__.assert_awaited_once()
