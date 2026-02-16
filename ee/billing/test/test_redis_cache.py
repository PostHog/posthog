import pytest
from unittest.mock import AsyncMock, patch

from ee.billing.salesforce_enrichment.redis_cache import (
    _compress_redis_data,
    _decompress_redis_data,
    get_cached_org_mappings_count,
    get_org_mappings_from_redis,
    store_org_mappings_in_redis,
)


class TestCompressionHelpers:
    def test_compression_decompression_round_trip(self):
        original_data = '{"key": "value", "list": [1, 2, 3]}'

        compressed = _compress_redis_data(original_data)
        decompressed = _decompress_redis_data(compressed)

        assert decompressed == original_data

    def test_compression_decompression_unicode(self):
        original_data = '{"name": "Test Café ñ 日本語"}'

        compressed = _compress_redis_data(original_data)
        decompressed = _decompress_redis_data(compressed)

        assert decompressed == original_data

    def test_compression_produces_bytes(self):
        original_data = '{"test": "data"}'

        compressed = _compress_redis_data(original_data)

        assert isinstance(compressed, bytes)


class TestStoreOrgMappingsInRedis:
    @pytest.mark.asyncio
    async def test_store_org_mappings_success(self):
        mappings = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"},
        ]

        mock_redis = AsyncMock()

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            await store_org_mappings_in_redis(mappings)

            mock_redis.setex.assert_called_once()
            call_args = mock_redis.setex.call_args
            # First arg is key, second is TTL, third is compressed data
            assert call_args[0][0] == "salesforce-enrichment:global:org_mappings"
            assert call_args[0][1] == 12 * 60 * 60  # Default TTL
            assert isinstance(call_args[0][2], bytes)  # Compressed data

    @pytest.mark.asyncio
    async def test_store_org_mappings_custom_ttl(self):
        mappings = [{"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"}]
        custom_ttl = 3600

        mock_redis = AsyncMock()

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            await store_org_mappings_in_redis(mappings, ttl=custom_ttl)

            call_args = mock_redis.setex.call_args
            assert call_args[0][1] == custom_ttl

    @pytest.mark.asyncio
    async def test_store_org_mappings_empty_list(self):
        mock_redis = AsyncMock()

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            await store_org_mappings_in_redis([])

            mock_redis.setex.assert_called_once()


class TestGetOrgMappingsFromRedis:
    @pytest.mark.asyncio
    async def test_get_org_mappings_success(self):
        original_data = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"},
        ]
        compressed_data = _compress_redis_data(
            '[{"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"}, {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"}]'
        )

        mock_redis = AsyncMock()
        mock_redis.get.return_value = compressed_data

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_org_mappings_from_redis()

            assert result == original_data
            mock_redis.get.assert_called_once_with("salesforce-enrichment:global:org_mappings")

    @pytest.mark.asyncio
    async def test_get_org_mappings_cache_miss(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_org_mappings_from_redis()

            assert result is None

    @pytest.mark.asyncio
    async def test_get_org_mappings_redis_error(self):
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = Exception("Redis connection error")

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            with patch("ee.billing.salesforce_enrichment.redis_cache.capture_exception") as mock_capture:
                result = await get_org_mappings_from_redis()

                assert result is None
                mock_capture.assert_called_once()


class TestGetCachedOrgMappingsCount:
    @pytest.mark.asyncio
    async def test_get_cached_org_mappings_count_success(self):
        original_data = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"},
            {"salesforce_account_id": "001GHI", "posthog_org_id": "uuid-3"},
        ]
        import json

        compressed_data = _compress_redis_data(json.dumps(original_data))

        mock_redis = AsyncMock()
        mock_redis.get.return_value = compressed_data

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_cached_org_mappings_count()

            assert result == 3

    @pytest.mark.asyncio
    async def test_get_cached_org_mappings_count_cache_miss(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_cached_org_mappings_count()

            assert result is None

    @pytest.mark.asyncio
    async def test_get_cached_org_mappings_count_empty_list(self):
        compressed_data = _compress_redis_data("[]")

        mock_redis = AsyncMock()
        mock_redis.get.return_value = compressed_data

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            result = await get_cached_org_mappings_count()

            assert result == 0


class TestStoreAndRetrieveRoundTrip:
    @pytest.mark.asyncio
    async def test_store_and_retrieve_org_mappings_round_trip(self):
        original_mappings = [
            {"salesforce_account_id": "001ABC", "posthog_org_id": "uuid-1"},
            {"salesforce_account_id": "001DEF", "posthog_org_id": "uuid-2"},
        ]

        stored_data = None

        async def mock_setex(key, ttl, data):
            nonlocal stored_data
            stored_data = data

        async def mock_get(key):
            return stored_data

        mock_redis = AsyncMock()
        mock_redis.setex = mock_setex
        mock_redis.get = mock_get

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

        stored_data = None

        async def mock_setex(key, ttl, data):
            nonlocal stored_data
            stored_data = data

        async def mock_get(key):
            return stored_data

        mock_redis = AsyncMock()
        mock_redis.setex = mock_setex
        mock_redis.get = mock_get

        with patch(
            "ee.billing.salesforce_enrichment.redis_cache.get_async_client",
            return_value=mock_redis,
        ):
            await store_org_mappings_in_redis(original_mappings)
            count = await get_cached_org_mappings_count()

            assert count == 100
