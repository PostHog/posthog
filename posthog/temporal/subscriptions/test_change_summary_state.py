import gzip
import json

import pytest
from unittest.mock import AsyncMock

from parameterized import parameterized_class

from posthog.temporal.subscriptions.change_summary_state import (
    MAX_TTL_SECONDS,
    MIN_TTL_SECONDS,
    compute_ttl_seconds,
    generate_state_key,
    load_insight_state,
    store_insight_state,
)


class TestGenerateStateKey:
    def test_contains_subscription_and_insight_ids(self):
        key = generate_state_key(subscription_id=42, insight_id=99)
        assert "42" in key
        assert "99" in key
        assert key == "subscription:change_summary:42:99:state"


@parameterized_class(
    ("frequency", "interval", "expected_seconds"),
    [
        ("daily", 1, MIN_TTL_SECONDS),
        ("weekly", 1, 7 * 24 * 3600 * 3),
        ("weekly", 2, 7 * 24 * 3600 * 2 * 3),
        ("monthly", 1, 30 * 24 * 3600 * 3),
        ("daily", 100, MAX_TTL_SECONDS),
        ("yearly", 1, MAX_TTL_SECONDS),
        ("unknown_frequency", 1, MIN_TTL_SECONDS),
    ],
)
class TestComputeTtlSeconds:
    frequency: str
    interval: int
    expected_seconds: int

    def test_ttl_calculation(self):
        result = compute_ttl_seconds(self.frequency, self.interval)
        assert result == self.expected_seconds
        assert MIN_TTL_SECONDS <= result <= MAX_TTL_SECONDS


class TestStoreInsightState:
    @pytest.mark.asyncio
    async def test_store_returns_compressed_size(self):
        redis_client = AsyncMock()
        state = {"query_definition": {"kind": "TrendsQuery"}, "results_summary": "test data" * 100}

        compressed_size = await store_insight_state(redis_client, "test-key", state, ttl=300)

        redis_client.setex.assert_called_once()
        args = redis_client.setex.call_args
        assert args[0][0] == "test-key"
        assert args[0][1] == 300
        stored_bytes = args[0][2]
        decompressed = json.loads(gzip.decompress(stored_bytes).decode("utf-8"))
        assert decompressed == state
        assert compressed_size == len(stored_bytes)

    @pytest.mark.asyncio
    async def test_store_compresses_data(self):
        redis_client = AsyncMock()
        state = {"results_summary": "x" * 10000}

        compressed_size = await store_insight_state(redis_client, "test-key", state, ttl=300)

        raw_size = len(json.dumps(state).encode("utf-8"))
        assert compressed_size < raw_size


class TestLoadInsightState:
    @pytest.mark.asyncio
    async def test_load_decompresses(self):
        state = {"query_definition": {"kind": "TrendsQuery"}, "results_summary": "Pageviews: avg 1,234/day"}
        compressed = gzip.compress(json.dumps(state).encode("utf-8"))
        redis_client = AsyncMock()
        redis_client.get.return_value = compressed

        result = await load_insight_state(redis_client, "test-key")

        assert result == state
        redis_client.get.assert_called_once_with("test-key")

    @pytest.mark.asyncio
    async def test_load_missing_key_returns_none(self):
        redis_client = AsyncMock()
        redis_client.get.return_value = None

        result = await load_insight_state(redis_client, "nonexistent-key")

        assert result is None


class TestStoreAndLoadRoundtrip:
    @pytest.mark.asyncio
    async def test_roundtrip(self):
        state = {
            "query_definition": {"kind": "TrendsQuery", "series": [{"event": "$pageview"}]},
            "results_summary": "Pageviews: avg 1,234/day, trend up",
            "timestamp": "2025-04-15T10:00:00Z",
            "insight_name": "Weekly pageviews",
        }

        stored_data = None

        async def fake_setex(key, ttl, data):
            nonlocal stored_data
            stored_data = data

        async def fake_get(key):
            return stored_data

        redis_client = AsyncMock()
        redis_client.setex.side_effect = fake_setex
        redis_client.get.side_effect = fake_get

        await store_insight_state(redis_client, "roundtrip-key", state, ttl=300)
        loaded = await load_insight_state(redis_client, "roundtrip-key")

        assert loaded == state


class TestLoadCorruptedData:
    @pytest.mark.asyncio
    async def test_corrupted_gzip_returns_none(self):
        redis_client = AsyncMock()
        redis_client.get.return_value = b"not valid gzip data"

        result = await load_insight_state(redis_client, "corrupted-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_corrupted_json_returns_none(self):
        redis_client = AsyncMock()
        redis_client.get.return_value = gzip.compress(b"not valid json")

        result = await load_insight_state(redis_client, "corrupted-key")

        assert result is None
