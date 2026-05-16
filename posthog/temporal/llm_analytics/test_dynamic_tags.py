import gzip
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from posthog.temporal.llm_analytics.dynamic_tags import (
    DynamicTagResult,
    _ExtractedTags,
    cache_key,
    fingerprint,
    invalidate_cached_tags,
    resolve_dynamic_tags,
)

from products.llm_analytics.backend.models.taggers import TagDefinition


def test_cache_key_is_stable():
    assert cache_key("abc") == "llma:tagger:abc:dynamic_tags"


def test_fingerprint_changes_when_url_or_prompt_change():
    fp1 = fingerprint("https://a.example", "prompt-a")
    fp2 = fingerprint("https://a.example", "prompt-b")
    fp3 = fingerprint("https://b.example", "prompt-a")
    assert fp1 != fp2
    assert fp1 != fp3
    assert fp2 != fp3
    # Same inputs → same fingerprint
    assert fingerprint("https://a.example", "prompt-a") == fp1


@pytest.mark.asyncio
async def test_resolve_returns_cached_tags_on_hit():
    cached_tags = [{"name": "alice", "description": "billing"}, {"name": "bob", "description": "analytics"}]
    fp = fingerprint("https://x.example", "find owners")
    payload = gzip.compress(json.dumps({"fingerprint": fp, "tags": cached_tags}).encode("utf-8"))

    redis_mock = AsyncMock()
    redis_mock.get.return_value = payload

    with patch("posthog.temporal.llm_analytics.dynamic_tags.get_async_client", AsyncMock(return_value=redis_mock)):
        result = await resolve_dynamic_tags(
            tagger_id="tagger-1",
            tag_source_url="https://x.example",
            tag_source_prompt="find owners",
            provider="openai",
            model="gpt-5-mini",
            provider_key=None,
            eval_config=None,
        )

    assert result.tags == cached_tags
    assert result.extraction_llm_used is False
    assert result.skip_reason is None
    # No extraction call happened — no token counts
    assert result.extraction_input_tokens == 0
    assert result.extraction_output_tokens == 0


@pytest.mark.asyncio
async def test_resolve_ignores_cache_when_fingerprint_mismatches():
    """A stale cache entry (different URL/prompt) must be skipped, not served."""
    stale_payload = gzip.compress(json.dumps({"fingerprint": "deadbeef", "tags": [{"name": "old"}]}).encode("utf-8"))

    redis_mock = AsyncMock()
    redis_mock.get.return_value = stale_payload

    extracted = _ExtractedTags(tags=[TagDefinition(name="new", description="fresh")])
    llm_response = MagicMock()
    llm_response.parsed = extracted
    llm_response.usage = MagicMock(input_tokens=50, output_tokens=10)

    llm_client = MagicMock()
    llm_client.complete.return_value = llm_response

    with (
        patch("posthog.temporal.llm_analytics.dynamic_tags.get_async_client", AsyncMock(return_value=redis_mock)),
        patch("posthog.temporal.llm_analytics.dynamic_tags.Client", return_value=llm_client),
        patch(
            "posthog.temporal.llm_analytics.dynamic_tags._fetch_url_as_markdown",
            AsyncMock(return_value="# Owners\n\n- new"),
        ),
    ):
        result = await resolve_dynamic_tags(
            tagger_id="tagger-1",
            tag_source_url="https://x.example",
            tag_source_prompt="find owners",
            provider="openai",
            model="gpt-5-mini",
            provider_key=None,
            eval_config=None,
        )

    assert result.tags == [{"name": "new", "description": "fresh"}]
    assert result.extraction_llm_used is True
    assert result.extraction_input_tokens == 50
    assert result.extraction_output_tokens == 10


@pytest.mark.asyncio
async def test_resolve_returns_skip_when_url_fetch_fails():
    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    with (
        patch("posthog.temporal.llm_analytics.dynamic_tags.get_async_client", AsyncMock(return_value=redis_mock)),
        patch("httpx.AsyncClient") as mock_async_client_cls,
    ):
        mock_client_ctx = AsyncMock()
        mock_client_ctx.get.side_effect = httpx.ConnectError("network down")
        mock_async_client_cls.return_value.__aenter__.return_value = mock_client_ctx

        result = await resolve_dynamic_tags(
            tagger_id="t",
            tag_source_url="https://broken.example",
            tag_source_prompt="extract",
            provider="openai",
            model="gpt-5-mini",
            provider_key=None,
            eval_config=None,
        )

    assert result.skip_reason == "tag_source_fetch_failed"
    assert result.tags is None


@pytest.mark.asyncio
async def test_resolve_returns_skip_when_url_returns_4xx():
    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    response = MagicMock()
    response.status_code = 404
    response.content = b""
    response.encoding = "utf-8"

    with (
        patch("posthog.temporal.llm_analytics.dynamic_tags.get_async_client", AsyncMock(return_value=redis_mock)),
        patch("httpx.AsyncClient") as mock_async_client_cls,
    ):
        mock_client_ctx = AsyncMock()
        mock_client_ctx.get.return_value = response
        mock_async_client_cls.return_value.__aenter__.return_value = mock_client_ctx

        result = await resolve_dynamic_tags(
            tagger_id="t",
            tag_source_url="https://example.com/missing",
            tag_source_prompt="extract",
            provider="openai",
            model="gpt-5-mini",
            provider_key=None,
            eval_config=None,
        )

    assert result.skip_reason == "tag_source_fetch_failed"


@pytest.mark.asyncio
async def test_resolve_returns_skip_when_extraction_yields_empty_list():
    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    llm_client = MagicMock()
    llm_response = MagicMock()
    llm_response.parsed = _ExtractedTags(tags=[])
    llm_response.usage = None
    llm_client.complete.return_value = llm_response

    with (
        patch("posthog.temporal.llm_analytics.dynamic_tags.get_async_client", AsyncMock(return_value=redis_mock)),
        patch(
            "posthog.temporal.llm_analytics.dynamic_tags._fetch_url_as_markdown",
            AsyncMock(return_value="# Page with no tags"),
        ),
        patch("posthog.temporal.llm_analytics.dynamic_tags.Client", return_value=llm_client),
    ):
        result = await resolve_dynamic_tags(
            tagger_id="t",
            tag_source_url="https://x.example",
            tag_source_prompt="extract",
            provider="openai",
            model="gpt-5-mini",
            provider_key=None,
            eval_config=None,
        )

    assert result.skip_reason == "tag_source_empty"
    assert result.tags is None


@pytest.mark.asyncio
async def test_resolve_returns_skip_on_empty_markdown():
    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    with (
        patch("posthog.temporal.llm_analytics.dynamic_tags.get_async_client", AsyncMock(return_value=redis_mock)),
        patch("posthog.temporal.llm_analytics.dynamic_tags._fetch_url_as_markdown", AsyncMock(return_value="")),
    ):
        result = await resolve_dynamic_tags(
            tagger_id="t",
            tag_source_url="https://blank.example",
            tag_source_prompt="extract",
            provider="openai",
            model="gpt-5-mini",
            provider_key=None,
            eval_config=None,
        )

    assert result.skip_reason == "tag_source_empty"


@pytest.mark.asyncio
async def test_resolve_caches_extracted_tags_after_llm_call():
    redis_mock = AsyncMock()
    redis_mock.get.return_value = None

    llm_client = MagicMock()
    llm_response = MagicMock()
    llm_response.parsed = _ExtractedTags(tags=[TagDefinition(name="x")])
    llm_response.usage = MagicMock(input_tokens=1, output_tokens=1)
    llm_client.complete.return_value = llm_response

    with (
        patch("posthog.temporal.llm_analytics.dynamic_tags.get_async_client", AsyncMock(return_value=redis_mock)),
        patch(
            "posthog.temporal.llm_analytics.dynamic_tags._fetch_url_as_markdown",
            AsyncMock(return_value="# Has x"),
        ),
        patch("posthog.temporal.llm_analytics.dynamic_tags.Client", return_value=llm_client),
    ):
        await resolve_dynamic_tags(
            tagger_id="t",
            tag_source_url="https://x.example",
            tag_source_prompt="extract",
            provider="openai",
            model="gpt-5-mini",
            provider_key=None,
            eval_config=None,
        )

    redis_mock.setex.assert_called_once()
    args, _ = redis_mock.setex.call_args
    assert args[0] == cache_key("t")
    assert args[1] == 24 * 60 * 60  # 24h TTL
    # Stored payload contains the fingerprint and tag list
    decoded = json.loads(gzip.decompress(args[2]).decode("utf-8"))
    assert decoded["fingerprint"] == fingerprint("https://x.example", "extract")
    assert decoded["tags"] == [{"name": "x", "description": ""}]


@pytest.mark.asyncio
async def test_invalidate_cached_tags_deletes_the_key():
    redis_mock = AsyncMock()
    with patch("posthog.temporal.llm_analytics.dynamic_tags.get_async_client", AsyncMock(return_value=redis_mock)):
        await invalidate_cached_tags("t")
    redis_mock.delete.assert_called_once_with(cache_key("t"))


@pytest.mark.asyncio
async def test_invalidate_swallows_redis_errors():
    redis_mock = AsyncMock()
    redis_mock.delete.side_effect = Exception("redis down")
    with patch("posthog.temporal.llm_analytics.dynamic_tags.get_async_client", AsyncMock(return_value=redis_mock)):
        # Must not raise
        await invalidate_cached_tags("t")


def test_dynamic_tag_result_defaults():
    r = DynamicTagResult()
    assert r.tags is None
    assert r.extraction_llm_used is False
    assert r.skip_reason is None
