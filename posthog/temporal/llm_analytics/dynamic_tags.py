"""Dynamic tag-vocabulary resolution for LLM analytics taggers.

When a tagger has ``tag_source == "dynamic"`` it doesn't ship with a fixed
tag list — instead it carries a URL plus an extraction prompt, and at run
time we fetch the URL, convert it to markdown, and ask the LLM to derive a
``list[TagDefinition]`` from it. The result is cached in Redis so we only
hit the URL + LLM once per tagger per cache window.

Failure modes return ``None`` from :func:`resolve_dynamic_tags` and set a
``skip_reason`` on the supplied result holder. The caller decides whether
to surface that as a workflow ``skipped`` outcome.
"""

import gzip
import json
import hashlib
from dataclasses import dataclass
from typing import Any

import httpx
import html2text
import structlog
from pydantic import BaseModel, Field
from temporalio.exceptions import ApplicationError

from posthog.redis import get_async_client

from products.llm_analytics.backend.llm import Client, CompletionRequest
from products.llm_analytics.backend.llm.errors import (
    AuthenticationError,
    ModelNotFoundError,
    ModelPermissionError,
    QuotaExceededError,
    RateLimitError,
    StructuredOutputParseError,
)
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey
from products.llm_analytics.backend.models.taggers import TagDefinition

logger = structlog.get_logger(__name__)

REDIS_KEY_PREFIX = "llma:tagger"
REDIS_TTL_SECONDS = 24 * 60 * 60  # 24h, matches D3 from the workflows-llm-step skill
FETCH_TIMEOUT_SECONDS = 10.0
FETCH_MAX_BYTES = 1_048_576  # 1 MiB — anything larger is a sign the URL isn't a reasonable tag source

EXTRACTION_SYSTEM_PROMPT = """You are extracting a tag vocabulary from a source document.
Given the document content and the user's extraction instruction, produce a list of
distinct tag definitions. Each tag has a short snake_case-friendly `name` and an
optional `description` that helps the downstream classifier decide when the tag applies.

Rules:
- Names must be unique and concise (1-3 words, no punctuation other than dashes/underscores).
- Descriptions should be one sentence and explain *what kind of input* maps to this tag.
- Do not invent tags that aren't grounded in the document. If the document is empty or
  unrelated, return an empty list.
"""


def cache_key(tagger_id: str) -> str:
    """Single cache key per tagger.

    The tagger's saved post_save signal busts this key, so we don't need to vary the
    key by URL or prompt — those changes go hand-in-hand with a save anyway.
    """
    return f"{REDIS_KEY_PREFIX}:{tagger_id}:dynamic_tags"


def fingerprint(url: str, prompt: str) -> str:
    """Short fingerprint of the URL+prompt pair stored alongside the cached tags.

    Used to invalidate the cache when the URL or prompt changes without an explicit
    tagger save (defense-in-depth — the save signal should already invalidate, but
    if a worker reads a stale cache entry post-save we still recover).
    """
    h = hashlib.sha256()
    h.update(url.encode("utf-8"))
    h.update(b"\0")
    h.update(prompt.encode("utf-8"))
    return h.hexdigest()[:16]


class _ExtractedTags(BaseModel):
    """LLM-side response shape for tag-vocabulary extraction."""

    tags: list[TagDefinition] = Field(default_factory=list)


@dataclass
class DynamicTagResult:
    """Outcome of resolving a tagger's dynamic tag vocabulary.

    Either ``tags`` is populated (success) or ``skip_reason`` is set (caller should
    short-circuit the tagger run with a workflow ``skipped`` outcome).
    """

    tags: list[dict[str, str]] | None = None
    extraction_llm_used: bool = False
    extraction_input_tokens: int = 0
    extraction_output_tokens: int = 0
    skip_reason: str | None = None
    skip_message: str | None = None


async def _fetch_url_as_markdown(url: str) -> str:
    """Fetch ``url`` and convert HTML → markdown.

    Raises ``ApplicationError(error_type="tag_source_fetch_failed")`` on any
    network / content error so the caller can map it to a workflow skip.
    """
    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_redirects=5,
            headers={"User-Agent": "PostHog-Tagger/1.0 (+https://posthog.com)"},
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise ApplicationError(
            f"Failed to fetch tag source URL: {exc}",
            {"error_type": "tag_source_fetch_failed", "url": url},
            non_retryable=True,
        ) from exc

    if response.status_code >= 400:
        raise ApplicationError(
            f"Tag source URL returned HTTP {response.status_code}",
            {"error_type": "tag_source_fetch_failed", "url": url, "status_code": response.status_code},
            non_retryable=True,
        )

    body = response.content[:FETCH_MAX_BYTES]
    # Decode with fallback so we don't blow up on misconfigured Content-Type headers.
    try:
        text = body.decode(response.encoding or "utf-8", errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")

    converter = html2text.HTML2Text()
    converter.ignore_images = True
    converter.ignore_links = False
    converter.body_width = 0  # don't hard-wrap; markdown lines stay logical
    markdown = converter.handle(text)
    return markdown.strip()


async def _load_cached_tags(tagger_id: str, expected_fingerprint: str) -> list[dict[str, str]] | None:
    """Load tags from Redis if the entry matches ``expected_fingerprint``.

    Stale entries (different fingerprint) are ignored and overwritten on next set.
    """
    redis = await get_async_client()
    try:
        raw = await redis.get(cache_key(tagger_id))
    except Exception:
        logger.warning("Failed to read dynamic-tag cache; falling back to LLM call", tagger_id=tagger_id, exc_info=True)
        return None

    if raw is None:
        return None

    try:
        decoded = json.loads(gzip.decompress(raw).decode("utf-8"))
    except Exception:
        logger.warning("Corrupt dynamic-tag cache entry; ignoring", tagger_id=tagger_id, exc_info=True)
        return None

    if decoded.get("fingerprint") != expected_fingerprint:
        return None

    tags = decoded.get("tags")
    if not isinstance(tags, list):
        return None
    return tags


async def _store_cached_tags(tagger_id: str, fp: str, tags: list[dict[str, str]]) -> None:
    redis = await get_async_client()
    payload = json.dumps({"fingerprint": fp, "tags": tags}).encode("utf-8")
    try:
        await redis.setex(cache_key(tagger_id), REDIS_TTL_SECONDS, gzip.compress(payload))
    except Exception:
        # A cache write failure is non-fatal — the LLM call already succeeded and the
        # workflow can proceed. Next run will re-derive the tags.
        logger.warning("Failed to write dynamic-tag cache", tagger_id=tagger_id, exc_info=True)


async def invalidate_cached_tags(tagger_id: str) -> None:
    """Bust the dynamic-tag cache for a tagger.

    Called from the ``Tagger`` post_save signal so URL/prompt edits take effect on
    the next tagger run instead of waiting for the 24h TTL to expire.
    """
    redis = await get_async_client()
    try:
        await redis.delete(cache_key(tagger_id))
    except Exception:
        logger.warning("Failed to invalidate dynamic-tag cache", tagger_id=tagger_id, exc_info=True)


async def resolve_dynamic_tags(
    *,
    tagger_id: str,
    tag_source_url: str,
    tag_source_prompt: str,
    provider: str,
    model: str,
    provider_key: LLMProviderKey | None,
    eval_config: Any,
) -> DynamicTagResult:
    """Resolve the working tag vocabulary for a dynamic-source tagger.

    Returns either a populated ``DynamicTagResult.tags`` (cache hit or fresh LLM
    extraction) or a result with ``skip_reason`` set if anything went wrong in a
    way the caller should surface as a workflow skip.

    LLM/auth errors that look like infrastructure problems (rate limits, etc.)
    are re-raised so the surrounding activity retry policy can handle them.
    """
    fp = fingerprint(tag_source_url, tag_source_prompt)
    cached = await _load_cached_tags(tagger_id, fp)
    if cached is not None:
        logger.debug("Dynamic-tag cache hit", tagger_id=tagger_id)
        return DynamicTagResult(tags=cached, extraction_llm_used=False)

    try:
        markdown = await _fetch_url_as_markdown(tag_source_url)
    except ApplicationError as exc:
        details = exc.details[0] if exc.details else {}
        return DynamicTagResult(
            skip_reason=details.get("error_type", "tag_source_fetch_failed"),
            skip_message=str(exc.message),
        )

    if not markdown:
        return DynamicTagResult(
            skip_reason="tag_source_empty",
            skip_message=f"Tag source URL {tag_source_url} returned no readable content",
        )

    user_prompt = f"""Extraction instruction:
{tag_source_prompt}

Source document (markdown):
{markdown}
"""

    client = Client(
        provider_key=provider_key,
        config=eval_config if provider_key is None else None,
        capture_analytics=False,
    )

    try:
        response = client.complete(
            CompletionRequest(
                model=model,
                system=EXTRACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                provider=provider,
                response_format=_ExtractedTags,
            )
        )
    except (AuthenticationError, ModelPermissionError, QuotaExceededError, RateLimitError, ModelNotFoundError):
        # Bubble up — these have the same recovery semantics as the classification call
        # and the existing run_tagger activity error handling maps them to ApplicationErrors.
        raise
    except StructuredOutputParseError as exc:
        return DynamicTagResult(
            skip_reason="tag_source_extract_failed",
            skip_message=f"LLM extraction returned unparseable output: {exc}",
        )

    parsed = response.parsed
    if parsed is None or not isinstance(parsed, _ExtractedTags):
        return DynamicTagResult(
            skip_reason="tag_source_extract_failed",
            skip_message="LLM extraction returned no structured response",
        )

    if not parsed.tags:
        return DynamicTagResult(
            skip_reason="tag_source_empty",
            skip_message="LLM extraction produced no tags from the source document",
        )

    tags_serialised = [{"name": t.name, "description": t.description} for t in parsed.tags]
    await _store_cached_tags(tagger_id, fp, tags_serialised)

    usage = response.usage
    return DynamicTagResult(
        tags=tags_serialised,
        extraction_llm_used=True,
        extraction_input_tokens=usage.input_tokens if usage else 0,
        extraction_output_tokens=usage.output_tokens if usage else 0,
    )
