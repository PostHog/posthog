"""Tests for Redis intermediate storage helpers."""

import gzip

import pytest
from unittest.mock import AsyncMock

from posthog.temporal.llm_analytics.trace_summarization.state import (
    REDIS_KEY_PREFIX,
    REDIS_TTL_SECONDS,
    delete_text_repr,
    generate_redis_key,
    load_text_repr,
    store_text_repr,
)


class TestGenerateRedisKey:
    @pytest.mark.parametrize(
        "item_type,team_id,item_id,expected",
        [
            ("trace", 1, "abc-123", f"{REDIS_KEY_PREFIX}:trace:1:abc-123:text_repr"),
            ("generation", 42, "gen-456", f"{REDIS_KEY_PREFIX}:generation:42:gen-456:text_repr"),
        ],
    )
    def test_key_format(self, item_type, team_id, item_id, expected):
        assert generate_redis_key(item_type, team_id, item_id) == expected


class TestStoreAndLoadTextRepr:
    @pytest.mark.asyncio
    async def test_store_returns_compressed_size(self):
        redis_client = AsyncMock()
        text = "Hello, world!" * 100

        compressed_size = await store_text_repr(redis_client, "test-key", text)

        redis_client.setex.assert_called_once()
        args = redis_client.setex.call_args
        assert args[0][0] == "test-key"
        assert args[0][1] == REDIS_TTL_SECONDS
        stored_bytes = args[0][2]
        assert gzip.decompress(stored_bytes).decode("utf-8") == text
        assert compressed_size == len(stored_bytes)

    @pytest.mark.asyncio
    async def test_store_with_custom_ttl(self):
        redis_client = AsyncMock()

        await store_text_repr(redis_client, "test-key", "data", ttl=60)

        args = redis_client.setex.call_args
        assert args[0][1] == 60

    @pytest.mark.asyncio
    async def test_load_decompresses(self):
        text = "decompressed content"
        compressed = gzip.compress(text.encode("utf-8"))
        redis_client = AsyncMock()
        redis_client.get.return_value = compressed

        result = await load_text_repr(redis_client, "test-key")

        assert result == text
        redis_client.get.assert_called_once_with("test-key")

    @pytest.mark.asyncio
    async def test_load_returns_none_on_missing_key(self):
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        result = await load_text_repr(redis_client, "test-key")

        assert result is None


class TestDeleteTextRepr:
    @pytest.mark.asyncio
    async def test_delete_calls_redis(self):
        redis_client = AsyncMock()

        await delete_text_repr(redis_client, "test-key")

        redis_client.delete.assert_called_once_with("test-key")

    @pytest.mark.asyncio
    async def test_delete_swallows_errors(self):
        redis_client = AsyncMock()
        redis_client.delete.side_effect = Exception("connection error")

        await delete_text_repr(redis_client, "test-key")
