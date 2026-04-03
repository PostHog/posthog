import json

import pytest
from unittest.mock import AsyncMock, patch

from ee.billing.salesforce_enrichment.redis_cache import (
    _compress_redis_data,
    get_cached_org_mappings_count,
    get_org_mappings_from_redis,
    get_org_mappings_page_from_redis,
    store_org_mappings_in_redis,
)


class TestCompressionHelpers:
    def test_compression_produces_bytes(self):
        original_data = '{"test": "data"}'

        compressed = _compress_redis_data(original_data)

        assert isinstance(compressed, bytes)

    def test_compression_round_trip(self):
        import gzip

        original_data = '{"key": "value", "list": [1, 2, 3]}'

        compressed = _compress_redis_data(original_data)
        decompressed = gzip.decompress(compressed).decode("utf-8")

        assert decompressed == original_data


class TestStoreOrgMappingsInRedis:
    @pytest.mark.asyncio
    async def test_store_org_mappings_success(self):
        mappings = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"},
        ]

        mock_pipe = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.pipeline.return_value = mock_pipe

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            await store_org_mappings_in_redis(mappings)

            mock_pipe.delete.assert_called_once_with("salesforce-enrichment:global:org_mappings")
            mock_pipe.rpush.assert_called_once()
            mock_pipe.expire.assert_called_once_with("salesforce-enrichment:global:org_mappings", 12 * 60 * 60)
            mock_pipe.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_org_mappings_custom_ttl(self):
        mappings = [{"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"}]
        custom_ttl = 3600

        mock_pipe = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.pipeline.return_value = mock_pipe

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            await store_org_mappings_in_redis(mappings, ttl=custom_ttl)

            mock_pipe.expire.assert_called_once_with("salesforce-enrichment:global:org_mappings", custom_ttl)

    @pytest.mark.asyncio
    async def test_store_org_mappings_empty_list(self):
        mock_pipe = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.pipeline.return_value = mock_pipe

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            await store_org_mappings_in_redis([])

            mock_pipe.delete.assert_called_once()
            mock_pipe.rpush.assert_not_called()
            mock_pipe.execute.assert_called_once()


class TestGetOrgMappingsPageFromRedis:
    @pytest.mark.asyncio
    async def test_get_page_success(self):
        raw_items = [
            json.dumps({"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"}).encode(),
            json.dumps({"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"}).encode(),
        ]
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = raw_items

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_org_mappings_page_from_redis(0, 10000)

            assert result == [
                {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
                {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"},
            ]

    @pytest.mark.asyncio
    async def test_get_page_cache_miss(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_org_mappings_page_from_redis(0, 10000)

            assert result is None

    @pytest.mark.asyncio
    async def test_get_page_redis_error(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.side_effect = Exception("Redis connection error")

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            with patch("ee.billing.salesforce_enrichment.redis_cache.capture_exception") as mock_capture:
                result = await get_org_mappings_page_from_redis(0, 10000)

                assert result is None
                mock_capture.assert_called_once()


class TestGetOrgMappingsFromRedis:
    @pytest.mark.asyncio
    async def test_get_all_mappings(self):
        raw_items = [
            json.dumps({"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"}).encode(),
        ]
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = raw_items

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_org_mappings_from_redis()

            assert result == [{"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"}]

    @pytest.mark.asyncio
    async def test_get_all_cache_miss(self):
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_org_mappings_from_redis()

            assert result is None


class TestGetCachedOrgMappingsCount:
    @pytest.mark.asyncio
    async def test_count_success(self):
        mock_redis = AsyncMock()
        mock_redis.llen.return_value = 280009

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_cached_org_mappings_count()

            assert result == 280009
            mock_redis.llen.assert_called_once_with("salesforce-enrichment:global:org_mappings")

    @pytest.mark.asyncio
    async def test_count_empty_returns_none(self):
        mock_redis = AsyncMock()
        mock_redis.llen.return_value = 0

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_cached_org_mappings_count()

            assert result is None

    @pytest.mark.asyncio
    async def test_count_redis_error(self):
        mock_redis = AsyncMock()
        mock_redis.llen.side_effect = Exception("Redis error")

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            with patch("ee.billing.salesforce_enrichment.redis_cache.capture_exception") as mock_capture:
                result = await get_cached_org_mappings_count()

                assert result is None
                mock_capture.assert_called_once()


class TestStoreAndRetrieveRoundTrip:
    @pytest.mark.asyncio
    async def test_store_and_retrieve_org_mappings_round_trip(self):
        original_mappings = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"},
        ]

        stored_list: list[str] = []

        store_pipe = AsyncMock()

        def mock_rpush(key, *values):
            stored_list.extend(values)

        store_pipe.rpush = mock_rpush

        mock_redis = AsyncMock()
        mock_redis.pipeline.return_value = store_pipe
        # lrange returns whatever was stored via rpush
        mock_redis.lrange = AsyncMock(side_effect=lambda key, start, end: stored_list)

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            await store_org_mappings_in_redis(original_mappings)
            retrieved_mappings = await get_org_mappings_from_redis()

            assert retrieved_mappings == original_mappings

    @pytest.mark.asyncio
    async def test_store_and_count_org_mappings_round_trip(self):
        original_mappings = [
            {"salesforce_account_id": f"001{i:03d}", "posthog_org_id": f"uuid-{i}"} for i in range(100)
        ]

        stored_list: list[str] = []

        store_pipe = AsyncMock()

        def mock_rpush(key, *values):
            stored_list.extend(values)

        store_pipe.rpush = mock_rpush

        mock_redis = AsyncMock()
        mock_redis.pipeline.return_value = store_pipe
        mock_redis.llen.return_value = 100

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            await store_org_mappings_in_redis(original_mappings)

            assert len(stored_list) == 100

            count = await get_cached_org_mappings_count()
            assert count == 100
