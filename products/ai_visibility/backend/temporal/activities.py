import json
import asyncio
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.utils import timezone

import structlog
from openai import OpenAI
from pydantic import BaseModel, Field
from temporalio import activity

from posthog.storage import object_storage

from products.ai_visibility.backend.models import AiVisibilityRun

logger = structlog.get_logger(__name__)

# Lazily instantiate a single client per process
_client: OpenAI | None = None

# Shared prompt suffixes to keep probes and generation in sync
SUFFIXES = ["alternatives", "competitors", "best", "pricing", "reviews"]
# Limit concurrent probes to avoid flooding the LLM/API
_PROBE_CONCURRENCY = 10
# LLM call protection
_LLM_TIMEOUT_SECONDS = 20
_LLM_MAX_RETRIES = 3


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


class BusinessInfo(BaseModel):
    name: str = Field(..., description="Name of the business or site")
    category: str = Field(..., description="Category/industry of the business")
    summary: str = Field(..., description="One sentence summary of what the business does")


class TopicsOutput(BaseModel):
    topics: list[str] = Field(..., description="Key features, solutions, or topics associated with the business")


class PromptVariant(BaseModel):
    intent: str
    prompt: str


class PromptsOutput(BaseModel):
    prompts: list[PromptVariant]


class ProbeResult(BaseModel):
    suffix: str
    topic: str
    mentions_target: bool
    competitors: list[str]
    confidence: float
    reasoning: str


class PlatformResult(BaseModel):
    mentioned: bool
    position: int | None = None
    cited: bool | None = None


class PromptResult(BaseModel):
    id: str
    text: str
    category: str
    you_mentioned: bool
    platforms: dict[str, PlatformResult]
    competitors_mentioned: list[str]
    last_checked: str


class ShareOfVoice(BaseModel):
    you: float
    competitors: dict[str, float]


class DashboardData(BaseModel):
    visibility_score: int
    share_of_voice: ShareOfVoice
    prompts: list[PromptResult]


@dataclass
class ExtractInfoInput:
    domain: str


@dataclass
class TopicsInput:
    domain: str
    info: dict


@dataclass
class PromptsInput:
    domain: str
    topics: list[str]
    info: dict


@dataclass
class AICallsInput:
    domain: str
    prompts: list[dict]
    info: dict
    topics: list[str]


@dataclass
class CombineInput:
    domain: str
    info: dict
    topics: list[str]
    ai_calls: list[dict]


@dataclass
class SaveResultsInput:
    run_id: str
    combined: dict


def _compute_share_of_voice(probes: list[ProbeResult], target: str) -> ShareOfVoice:
    if not probes:
        return ShareOfVoice(you=0.0, competitors={})

    you_hits = sum(1 for p in probes if p.mentions_target)
    total = len(probes)
    you_ratio = you_hits / total if total else 0.0

    comp_counts: dict[str, int] = {}
    for p in probes:
        for comp in p.competitors:
            comp_counts[comp] = comp_counts.get(comp, 0) + 1

    comp_sum = sum(comp_counts.values()) or 1
    competitors = {k: v / comp_sum for k, v in comp_counts.items()}
    return ShareOfVoice(you=you_ratio, competitors=competitors)


def _build_openai_platforms(mentioned: bool, base_position: int) -> dict[str, PlatformResult]:
    if not mentioned:
        return {"openai": PlatformResult(mentioned=False)}
    return {"openai": PlatformResult(mentioned=True, position=max(1, base_position), cited=True)}


async def _call_structured_llm(prompt: str, schema_model: type[BaseModel]) -> dict[str, Any]:
    client = get_client()

    def _call_sync() -> dict[str, Any]:
        response = client.responses.parse(
            model="gpt-5.1",
            input=[{"role": "user", "content": prompt}],
            text_format=schema_model,
            temperature=0.2,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("LLM response missing parsed payload")
        # output_parsed is already the Pydantic model instance
        return parsed.model_dump()

    last_error: Exception | None = None
    for attempt in range(1, _LLM_MAX_RETRIES + 1):
        try:
            return await asyncio.wait_for(asyncio.to_thread(_call_sync), timeout=_LLM_TIMEOUT_SECONDS)
        except (TimeoutError, Exception) as exc:  # noqa: BLE001
            last_error = exc
            if attempt == _LLM_MAX_RETRIES:
                break
            # brief backoff; avoid tight loops on transient failures
            await asyncio.sleep(0.5 * attempt)
    raise last_error  # type: ignore[misc]


@activity.defn(name="extractInfoFromURL")
async def extract_info_from_url(payload: ExtractInfoInput) -> dict:
    prompt = (
        "You are an analyst. Given a domain URL, identify the business name and category. "
        "Return a concise summary of what it does.\n\n"
        f"Domain: {payload.domain}"
    )
    logger.info("ai_visibility.extract_info_from_url.start", domain=payload.domain)
    data = await _call_structured_llm(prompt, BusinessInfo)
    logger.info("ai_visibility.extract_info_from_url.done", domain=payload.domain, business=data.get("name"))
    return data


@activity.defn(name="getTopics")
async def get_topics(payload: TopicsInput) -> list[str]:
    info = BusinessInfo.model_validate(payload.info)
    prompt = (
        "List the top features/solutions/topics this business is known for. "
        "Keep topics short (2-5 words each). Return 5-10 items.\n\n"
        f"Business: {info.name}\nCategory: {info.category}\nSummary: {info.summary}"
    )
    logger.info("ai_visibility.get_topics.start", domain=payload.domain, business=info.name)
    data = await _call_structured_llm(prompt, TopicsOutput)
    topics = data.get("topics", [])
    logger.info("ai_visibility.get_topics.done", domain=payload.domain, topics=len(topics))
    return topics


@activity.defn(name="generatePrompts")
async def generate_prompts(payload: PromptsInput) -> list[dict]:
    info = BusinessInfo.model_validate(payload.info)
    prompt = (
        "Generate search-style prompts to probe AI assistants about a target business and its space. "
        "For each suffix, craft one prompt using the business name, category, and topics. "
        "Prompts should be concise and natural.\n\n"
        f"Business: {info.name}\nCategory: {info.category}\nTopics: {payload.topics}\nSuffixes: {SUFFIXES}"
    )
    logger.info("ai_visibility.generate_prompts.start", domain=payload.domain)
    data = await _call_structured_llm(prompt, PromptsOutput)
    prompts = data.get("prompts", [])
    logger.info("ai_visibility.generate_prompts.done", domain=payload.domain, prompts=len(prompts))
    return [p for p in prompts if isinstance(p, dict)]


async def _probe_suffix(domain: str, info: BusinessInfo, topic: str, suffix: str) -> dict:
    prompt = (
        "You are evaluating how well a business appears in AI responses.\n"
        "Given a topic and suffix, determine if the target business is prominently mentioned, and list competitors.\n"
        "Return mentions_target=true if the business is a clear top result.\n\n"
        f"Business: {info.name}\nCategory: {info.category}\nTopic: {topic}\nSuffix: {suffix}"
    )
    data = await _call_structured_llm(prompt, ProbeResult)
    return data


@activity.defn(name="makeAICalls")
async def make_ai_calls(payload: AICallsInput) -> list[dict]:
    info = BusinessInfo.model_validate(payload.info)
    tasks: list[asyncio.Task] = []
    semaphore = asyncio.Semaphore(_PROBE_CONCURRENCY)

    async def run_probe(topic: str, suffix: str) -> dict:
        async with semaphore:
            return await _probe_suffix(payload.domain, info, topic, suffix)

    logger.info("ai_visibility.make_ai_calls.start", domain=payload.domain, topics=len(payload.topics))
    for topic in payload.topics:
        for suffix in SUFFIXES:
            tasks.append(asyncio.create_task(run_probe(topic, suffix)))

    results: list[dict] = []
    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_visibility.make_ai_calls.error", error=str(exc))
    logger.info("ai_visibility.make_ai_calls.done", domain=payload.domain, results=len(results))
    return results


@activity.defn(name="combineCalls")
async def combine_calls(payload: CombineInput) -> dict:
    info = BusinessInfo.model_validate(payload.info)
    probes = [ProbeResult.model_validate(p) for p in payload.ai_calls]

    share = _compute_share_of_voice(probes, target=info.name)

    # Build prompt-like objects from probes: one per (topic, suffix)
    prompt_items: list[PromptResult] = []
    for probe in probes:
        # Heuristic prompt text and category
        category = "commercial" if probe.suffix in {"alternatives", "competitors", "best"} else "informational"
        text = f"{probe.topic} {probe.suffix}".strip()
        platforms = _build_openai_platforms(probe.mentions_target, base_position=max(1, int(5 - probe.confidence * 4)))
        prompt_items.append(
            PromptResult(
                id=f"{payload.domain}:{probe.topic}:{probe.suffix}",
                text=text,
                category=category,
                you_mentioned=probe.mentions_target,
                platforms=platforms,
                competitors_mentioned=probe.competitors,
                last_checked=timezone.now().isoformat(),
            )
        )

    visibility_score = int(min(100, max(0, share.you * 100)))
    dashboard = DashboardData(
        visibility_score=visibility_score,
        share_of_voice=share,
        prompts=prompt_items,
    )

    logger.info(
        "ai_visibility.combine_calls.done", domain=payload.domain, probes=len(probes), visibility_score=visibility_score
    )
    return dashboard.model_dump()


@activity.defn(name="saveResults")
async def save_results(payload: SaveResultsInput) -> str:
    await asyncio.sleep(0)
    logger.info("ai_visibility.save_results", run_id=payload.run_id)

    s3_key = f"{settings.OBJECT_STORAGE_AI_VISIBILITY_FOLDER}/{payload.run_id}.json"
    content = json.dumps(payload.combined)
    object_storage.write(s3_key, content)

    run = await asyncio.to_thread(AiVisibilityRun.objects.get, id=payload.run_id)
    await asyncio.to_thread(run.mark_ready, s3_key)

    logger.info("ai_visibility.save_results.complete", run_id=payload.run_id, s3_path=s3_key)
    return s3_key
