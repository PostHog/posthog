import asyncio
from dataclasses import dataclass
from typing import Any

import structlog
from openai import OpenAI
from pydantic import BaseModel, Field
from temporalio import activity

logger = structlog.get_logger(__name__)

# Lazily instantiate a single client per process
_client: OpenAI | None = None


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


class CombinedOutput(BaseModel):
    business: BusinessInfo
    topics: list[str]
    probes: list[ProbeResult]


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

    return await asyncio.to_thread(_call_sync)


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
    suffixes = ["alternatives", "competitors", "best", "pricing", "reviews"]
    prompt = (
        "Generate search-style prompts to probe AI assistants about a target business and its space. "
        "For each suffix, craft one prompt using the business name, category, and topics. "
        "Prompts should be concise and natural.\n\n"
        f"Business: {info.name}\nCategory: {info.category}\nTopics: {payload.topics}\nSuffixes: {suffixes}"
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
    suffixes = ["alternatives", "competitors", "best", "pricing", "reviews"]
    tasks: list[asyncio.Task] = []
    logger.info("ai_visibility.make_ai_calls.start", domain=payload.domain, topics=len(payload.topics))
    for topic in payload.topics:
        for suffix in suffixes:
            tasks.append(asyncio.create_task(_probe_suffix(payload.domain, info, topic, suffix)))

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
    combined = CombinedOutput(business=info, topics=payload.topics, probes=probes)
    logger.info("ai_visibility.combine_calls.done", domain=payload.domain, probes=len(probes))
    return combined.model_dump()
