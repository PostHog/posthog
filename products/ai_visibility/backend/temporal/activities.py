import asyncio
from dataclasses import dataclass

import structlog
from temporalio import activity

logger = structlog.get_logger(__name__)


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


@dataclass
class AICallsInput:
    domain: str
    prompts: list[str]


@dataclass
class CombineInput:
    domain: str
    info: dict
    topics: list[str]
    ai_calls: list[dict]


@activity.defn(name="extractInfoFromURL")
async def extract_info_from_url(payload: ExtractInfoInput) -> dict:
    await asyncio.sleep(0)
    logger.info("ai_visibility.extract_info_from_url", domain=payload.domain)
    return {"domain": payload.domain, "description": f"Mock info for {payload.domain}"}


@activity.defn(name="getTopics")
async def get_topics(payload: TopicsInput) -> list[str]:
    await asyncio.sleep(0)
    logger.info("ai_visibility.get_topics", domain=payload.domain)
    return [f"{payload.domain}-topic-a", f"{payload.domain}-topic-b"]


@activity.defn(name="generatePrompts")
async def generate_prompts(payload: PromptsInput) -> list[str]:
    await asyncio.sleep(0)
    logger.info("ai_visibility.generate_prompts", domain=payload.domain)
    return [f"Prompt for {topic}" for topic in payload.topics]


@activity.defn(name="makeAICalls")
async def make_ai_calls(payload: AICallsInput) -> list[dict]:
    await asyncio.sleep(0)
    logger.info("ai_visibility.make_ai_calls", domain=payload.domain)
    return [{"prompt": prompt, "result": f"Mock result for {prompt}"} for prompt in payload.prompts]


@activity.defn(name="combineCalls")
async def combine_calls(payload: CombineInput) -> dict:
    await asyncio.sleep(0)
    logger.info("ai_visibility.combine_calls", domain=payload.domain)
    return {
        "domain": payload.domain,
        "summary": f"Combined {len(payload.ai_calls)} mock calls for {payload.domain}",
        "info": payload.info,
        "topics": payload.topics,
        "ai_calls": payload.ai_calls,
    }
