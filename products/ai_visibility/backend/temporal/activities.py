import json
import random
import asyncio
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.utils import timezone

import structlog
from openai import OpenAI
from pydantic import BaseModel, Field, conlist
from temporalio import activity

from posthog.storage import object_storage

from products.ai_visibility.backend.models import AiVisibilityRun

logger = structlog.get_logger(__name__)

# Lazily instantiate a single client per process
_client: OpenAI | None = None

# Hardcoded brand-based prompt templates (use {brand} placeholder)
BRAND_PROMPT_TEMPLATES = [
    "{brand} alternatives",
    "{brand} competitors ranked",
    "{brand} vs competitors",
    "best {brand} alternatives",
    "{brand} reviews",
]

_PROBE_CONCURRENCY = 20
_LLM_TIMEOUT_SECONDS = 30
_LLM_MAX_RETRIES = 3
_PROMPT_GEN_CONCURRENCY = 8


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


class BusinessInfo(BaseModel):
    name: str = Field(..., description="Name of the business or site")
    category: str = Field(..., description="Category/industry of the business")
    summary: str = Field(..., description="One sentence summary of what the business does")


class CategoryOutput(BaseModel):
    name: str = Field(..., description="Short category name (2-5 words)")
    description: str = Field(..., description="One sentence describing what this category covers")


class TopicsOutput(BaseModel):
    categories: list[CategoryOutput] = Field(
        ...,
        description="Topic categories customers search for (e.g., 'Self-hosted Analytics', 'Privacy-first Analytics')",
    )


class PromptVariant(BaseModel):
    category: str = Field(..., description="Category this prompt belongs to")
    prompt: str = Field(..., description="Natural freeform search prompt")


class CompetitorInfo(BaseModel):
    name: str = Field(..., description="Competitor brand name (not a generic category)")
    domain: str | None = Field(default=None, description="Primary domain for the competitor, no protocol")
    logo_url: str | None = Field(
        default=None,
        description="Logo URL; prefer https://www.google.com/s2/favicons?domain=<domain>&sz=128 when domain is known, else null",
    )


class PromptsOutput(BaseModel):
    prompts: list[PromptVariant]


class ProbeResult(BaseModel):
    prompt: str = Field(..., description="The exact prompt that was probed")
    category: str = Field(..., description="Category this prompt belongs to")
    mentions_target: bool
    competitors: conlist(CompetitorInfo, min_length=0, max_length=10) = Field(
        default_factory=list, description="Competitor brand details"
    )
    confidence: float
    reasoning: str = Field(
        ..., max_length=280, description="One-sentence evidence for mention/no-mention; keep concise and grounded"
    )


class PlatformResult(BaseModel):
    mentioned: bool
    position: int | None = None
    cited: bool | None = None


class PromptResult(BaseModel):
    id: str
    text: str
    topic: str  # The category/topic this prompt belongs to (e.g., "Self-hosted Analytics")
    category: str  # Intent type: commercial or informational
    you_mentioned: bool
    platforms: dict[str, PlatformResult]
    competitors: list[CompetitorInfo] = Field(default_factory=list)
    competitors_mentioned: list[str]
    last_checked: str
    reasoning: str


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
    topics: list[dict]  # List of category dicts with name/description
    info: dict


@dataclass
class AICallsInput:
    domain: str
    prompts: list[dict]
    info: dict
    topics: list[dict]


@dataclass
class CombineInput:
    domain: str
    info: dict
    topics: list[dict]
    ai_calls: list[dict]


@dataclass
class SaveResultsInput:
    run_id: str
    combined: dict


@dataclass
class MarkFailedInput:
    run_id: str
    error_message: str


@dataclass
class UpdateProgressInput:
    run_id: str
    step: str


def _compute_share_of_voice(probes: list[ProbeResult], target: str) -> ShareOfVoice:
    if not probes:
        return ShareOfVoice(you=0.0, competitors={})

    you_hits = sum(1 for p in probes if p.mentions_target)
    total = len(probes)
    you_ratio = you_hits / total if total else 0.0

    comp_counts: dict[str, int] = {}
    for p in probes:
        for comp in p.competitors:
            comp_counts[comp.name] = comp_counts.get(comp.name, 0) + 1

    comp_sum = sum(comp_counts.values()) or 1
    competitors = {k: v / comp_sum for k, v in comp_counts.items()}
    return ShareOfVoice(you=you_ratio, competitors=competitors)


def _build_openai_platforms(mentioned: bool, base_position: int) -> dict[str, PlatformResult]:
    if not mentioned:
        return {"openai": PlatformResult(mentioned=False)}
    return {"openai": PlatformResult(mentioned=True, position=max(1, base_position), cited=True)}


async def _call_structured_llm(
    prompt: str, schema_model: type[BaseModel], *, temperature: float = 0.2
) -> dict[str, Any]:
    client = get_client()

    def _call_sync() -> dict[str, Any]:
        response = client.responses.parse(
            model="gpt-5.1",
            input=[{"role": "user", "content": prompt}],
            text_format=schema_model,
            temperature=temperature,
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
        "Describe the primary customer problem they solve and the core solution in one concise sentence "
        "using generic capability terms, not marketing fluff.\n\n"
        f"Domain: {payload.domain}"
    )
    logger.info("ai_visibility.extract_info_from_url.start", domain=payload.domain)
    data = await _call_structured_llm(prompt, BusinessInfo)
    logger.info("ai_visibility.extract_info_from_url.done", domain=payload.domain, business=data.get("name"))
    return data


@activity.defn(name="getTopics")
async def get_topics(payload: TopicsInput) -> list[dict]:
    info = BusinessInfo.model_validate(payload.info)
    prompt = (
        "Generate topic categories that customers search for when looking for solutions like this business provides. "
        "Categories should be natural search themes, not product features. "
        "Examples for an analytics company: 'Self-hosted Analytics', 'Privacy-first Analytics', 'Open Source Analytics', 'GA4 Alternatives'. "
        "Examples for a payment company: 'Online Payment Processing', 'Subscription Billing', 'Payment Gateway Solutions'. "
        "Do NOT output brand names. Keep category names short (2-5 words). Return 5-8 diverse, non-overlapping categories.\n\n"
        f"Business: {info.name}\nIndustry: {info.category}\nSummary: {info.summary}"
    )
    logger.info("ai_visibility.get_topics.start", domain=payload.domain, business=info.name)
    data = await _call_structured_llm(prompt, TopicsOutput)
    categories = data.get("categories", [])
    logger.info("ai_visibility.get_topics.done", domain=payload.domain, categories=len(categories))
    return categories


async def _generate_prompts_for_category(
    info: BusinessInfo, category: dict | str, prompts_per_category: int
) -> list[dict]:
    """Generate prompts for a single category."""
    cat_name = category["name"] if isinstance(category, dict) else category
    cat_desc = category.get("description", "") if isinstance(category, dict) else ""

    prompt = (
        "Generate natural search prompts that customers would use when researching solutions in this category. "
        "Prompts should be freeform, varied, and sound like real questions people ask AI assistants. "
        "Do NOT mechanically append words like 'alternatives' or 'ranked' - be creative and natural. "
        "Do NOT include the target business name in prompts - we're testing if AI would recommend them organically. "
        "Competitor brand mentions are okay when they make the query more natural.\n\n"
        "Examples of good prompts:\n"
        "- 'recommend a self hosted product analytics stack'\n"
        "- 'tools for privacy first analytics'\n"
        "- 'open source analytics platforms ranked'\n"
        "- 'what's the best GA4 alternative that I can self-host'\n"
        "- 'comparing session replay tools for startups'\n\n"
        f"Business context: {info.name} - {info.summary}\n\n"
        f"Category: {cat_name}"
        + (f" - {cat_desc}" if cat_desc else "")
        + f"\n\nGenerate exactly {prompts_per_category} diverse prompts for this category. Keep prompts 6-15 words, natural, non-overlapping."
    )
    data = await _call_structured_llm(prompt, PromptsOutput, temperature=0.8)
    prompts = data.get("prompts", [])

    result: list[dict] = []
    for p in prompts:
        text = p.get("prompt") if isinstance(p, dict) else getattr(p, "prompt", None)
        if text:
            result.append({"category": cat_name, "prompt": text})
    return result


@activity.defn(name="generatePrompts")
async def generate_prompts(payload: PromptsInput) -> list[dict]:
    info = BusinessInfo.model_validate(payload.info)
    categories = payload.topics  # List of dicts with name/description

    prompts_per_category = random.choice([3, 5, 7, 9])
    semaphore = asyncio.Semaphore(_PROMPT_GEN_CONCURRENCY)

    async def run_category(category: dict | str) -> list[dict]:
        async with semaphore:
            return await _generate_prompts_for_category(info, category, prompts_per_category)

    logger.info("ai_visibility.generate_prompts.start", domain=payload.domain, categories=len(categories))

    # Run all categories in parallel
    tasks = [asyncio.create_task(run_category(cat)) for cat in categories]
    all_prompts: list[dict] = []
    for coro in asyncio.as_completed(tasks):
        try:
            result = await coro
            all_prompts.extend(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_visibility.generate_prompts.category_error", error=str(exc))

    # Dedupe prompts
    deduped: list[dict] = []
    seen: set[str] = set()
    for p in all_prompts:
        key = p["prompt"].strip().lower()
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    # Add hardcoded brand-based prompts
    brand_category = "Brand Comparison"
    for template in BRAND_PROMPT_TEMPLATES:
        text = template.format(brand=info.name)
        key = text.strip().lower()
        if key not in seen:
            seen.add(key)
            deduped.append({"category": brand_category, "prompt": text})

    logger.info("ai_visibility.generate_prompts.done", domain=payload.domain, prompts=len(deduped))
    return deduped


async def _probe_prompt(domain: str, info: BusinessInfo, search_prompt: str, category: str) -> dict:
    llm_prompt = (
        f"This is a search prompt: {search_prompt}\n"
        "Respond to it, and then analyze your response.\n"
        "For every company you mentioned in your response (brand names only, not generic categories), include it in the output."
        "Include the primary domain (no protocol) and a logo URL; "
        "use https://www.google.com/s2/favicons?domain=<domain>&sz=128 when the domain is known, else leave logo_url null."
        f"Exclude {info.name} from competitors.\n"
        "Provide one-sentence explaining why they were mentioned in the response.\n\n"
    )
    data = await _call_structured_llm(llm_prompt, ProbeResult)
    # Ensure prompt and category are set correctly
    data["prompt"] = search_prompt
    data["category"] = category
    return data


@activity.defn(name="makeAICalls")
async def make_ai_calls(payload: AICallsInput) -> list[dict]:
    info = BusinessInfo.model_validate(payload.info)
    tasks: list[asyncio.Task] = []
    semaphore = asyncio.Semaphore(_PROBE_CONCURRENCY)

    async def run_probe(search_prompt: str, category: str) -> dict:
        async with semaphore:
            return await _probe_prompt(payload.domain, info, search_prompt, category)

    logger.info("ai_visibility.make_ai_calls.start", domain=payload.domain, prompts=len(payload.prompts))
    for prompt_item in payload.prompts:
        search_prompt = prompt_item.get("prompt", "")
        category = prompt_item.get("category", "General")
        if search_prompt:
            tasks.append(asyncio.create_task(run_probe(search_prompt, category)))

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

    # Classify prompts as commercial vs informational based on category/content
    commercial_categories = {"Brand Comparison"}
    commercial_keywords = {"alternative", "competitor", "vs", "compare", "pricing", "best", "ranked"}

    prompt_items: list[PromptResult] = []
    for probe in probes:
        # Determine intent type
        prompt_lower = probe.prompt.lower()
        is_commercial = probe.category in commercial_categories or any(kw in prompt_lower for kw in commercial_keywords)
        intent_type = "commercial" if is_commercial else "informational"

        platforms = _build_openai_platforms(probe.mentions_target, base_position=max(1, int(5 - probe.confidence * 4)))
        prompt_items.append(
            PromptResult(
                id=f"{payload.domain}:{hash(probe.prompt) & 0xFFFFFFFF}",
                text=probe.prompt,
                topic=probe.category,  # The actual topic category (e.g., "Self-hosted Analytics")
                category=intent_type,  # commercial or informational
                you_mentioned=probe.mentions_target,
                platforms=platforms,
                competitors=probe.competitors,
                competitors_mentioned=[c.name for c in probe.competitors],
                last_checked=timezone.now().isoformat(),
                reasoning=probe.reasoning,
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


@activity.defn(name="markRunFailed")
async def mark_run_failed(payload: MarkFailedInput) -> None:
    await asyncio.sleep(0)
    logger.info("ai_visibility.mark_run_failed", run_id=payload.run_id, error=payload.error_message)

    run = await asyncio.to_thread(AiVisibilityRun.objects.get, id=payload.run_id)
    await asyncio.to_thread(run.mark_failed, payload.error_message)

    logger.info("ai_visibility.mark_run_failed.complete", run_id=payload.run_id)


@activity.defn(name="updateProgress")
async def update_progress(payload: UpdateProgressInput) -> None:
    await asyncio.sleep(0)
    logger.info("ai_visibility.update_progress", run_id=payload.run_id, step=payload.step)

    run = await asyncio.to_thread(AiVisibilityRun.objects.get, id=payload.run_id)
    step = AiVisibilityRun.ProgressStep(payload.step)
    await asyncio.to_thread(run.update_progress, step)

    logger.info("ai_visibility.update_progress.complete", run_id=payload.run_id, step=payload.step)
