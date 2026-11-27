"""Suggest prompts for a team's AEO prompt set with Claude, through the AI gateway.

Generation runs in a Celery task, and the result waits in the cache for the client to poll.
Suggestions are never saved as prompts. A person reviews them and imports the ones they keep,
so every prompt the runner sends to an engine is still one a person chose.
"""

from __future__ import annotations

import re
import json
import time
import uuid
import dataclasses
from typing import Any

from django.conf import settings
from django.core.cache import caches
from django.db.models.functions import Lower

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import AIGatewayConfig, resolve_ai_gateway_config
from posthog.security.llm_prompt_sanitization import sanitize_user_text

from products.aeo.backend import catalog
from products.aeo.backend.brand import brand_pattern
from products.aeo.backend.engines import MAX_PROMPT_LENGTH, AICreditsExhausted
from products.aeo.backend.facade.contracts import (
    BRAND_NAME_MAX_LENGTH,
    MAX_SUGGESTED_COMPETITORS,
    OUT_OF_AI_CREDITS_MESSAGE,
    PROMPT_TOPIC_MAX_LENGTH,
    FunnelStage,
    PromptCircle,
    PromptSuggestion,
    PromptSuggestionError,
    PromptSuggestionJob,
    PromptSuggestionJobNotFoundError,
    PromptSuggestionRequest,
    SuggestedCompetitor,
    SuggestionJobStatus,
)
from products.aeo.backend.llm import (
    DEADLINE_SECONDS,
    ClaudeAnswer,
    UnreadableAnswerError,
    answer_items,
    ask_with_web_search,
    visible,
)
from products.aeo.backend.models import AEOPrompt, AEOPromptVersion
from products.aeo.backend.seeding import normalize_prompt

logger = structlog.get_logger(__name__)

MAX_SUGGESTIONS = 50
MAX_SUGGESTION_SEARCHES = 3
# Each suggestion takes roughly 150 tokens of JSON. The base covers the competitors and any text the model writes
# between searches, which counts against the limit too; an answer cut off by the limit loses the prompts it never
# reached, so the budget errs high. The cap keeps the largest request inside one call's timeout.
BASE_SUGGESTION_TOKENS = 6000
TOKENS_PER_SUGGESTION = 300
MAX_SUGGESTION_TOKENS = 16000
MAX_EXISTING_PROMPTS_IN_INSTRUCTIONS = 100
REASON_MAX_LENGTH = 300
# Pinned to the Redis writer: jobs are polled right after they are created, and a replica can lag.
# Keyword suggestion jobs use it too, under their own key prefix.
SUGGESTION_CACHE_ALIAS = "aeo_prompt_suggestions"
SUGGESTION_JOB_TTL_SECONDS = 60 * 60
# A job still pending past the task's hard time limit lost its worker, so readers see it as failed.
SUGGESTION_JOB_STALE_SECONDS = 8 * 60
SPEND_LIMIT_ERROR = "PostHog AI has reached its spend limit, so setup can't run right now. Contact support to raise it."
TRANSIENT_RETRY_SECONDS = 3
UNREADABLE_ANSWER_ERROR = "The suggestions couldn't be read. Try again."
STALE_JOB_ERROR = "Prompt suggestions stopped before they finished. Try again."


# TODO: write prompts and keywords in the site's language. A pt-BR site such as a Brazilian store gets English prompts
# today, which people there don't ask. The locale could come from the site's <html lang> or its content during the
# research step, or from the team's settings, and the keyword instructions need the same rule.
_RESEARCH_PARAGRAPH = """Research first. Use web search to read {domain} (its homepage, product and pricing pages) and, if \
given, the competitors' sites, so you understand who the product is for, what it does differently and who it \
competes with."""
_KNOWN_PARAGRAPH = """The site was already researched: use what is known about it below. You do not need to search."""

_INSTRUCTIONS = """You help a team choose the prompts to track for AI visibility: the questions people ask AI assistants \
like ChatGPT and Claude, where the team wants its site to be mentioned and cited.

{research}

Then write {count} prompts that a real buyer would type into an AI assistant. Follow these rules:
- Keep each prompt short and broad, the way people type into an AI assistant: usually 3 to 10 words. Don't add \
details people rarely type, such as team size, budget, region or a list of integrations.
- Write this mix of prompts:
{mix}
- {branded_rule}
- Never write a prompt rigged in the brand's favor, such as one that lists a feature only this brand has.
- Only write questions people plausibly ask. Skip niche wording nobody would type.
- Spread the prompts across the topics. Keep each topic to two or three words.

Label every prompt with its circle, from where the buyer, the brand and its competitors overlap:
- differentiation: a need the buyer has that this brand meets and competitors do not.
- battleground: a need the buyer has that this brand and its competitors all meet.
- vulnerability: a need the buyer has that competitors meet better than this brand.
- table_stakes: something every tool in the category does.
- branded: the prompt names the brand.
And with its funnel stage: top (learning), middle (comparing options) or bottom (choosing or buying).

Brand: {brand}
Site: {domain}
{known}
Competitors: {competitors}
Topics to cover: {topics}
Prompts the team already tracks, which you must not repeat or rephrase:
{existing}

Answer with only one JSON object. Do not write research notes, summaries or any other text before or after it. \
Put "competitors" first, then "prompts":
{{"competitors": [{{"name": "...", "domain": "..."}}], "prompts": [{{"prompt": "...", ...}}]}}
"competitors" lists at most {max_competitors} companies that sell to the same buyers, with "name" (string) and \
"domain" (the domain of its site, such as example.com). When competitors are given above, list those. \
Leave out {domain} itself, and leave out partners, integrations, marketplaces and review sites.
Each item in "prompts" has these keys:
"prompt" (string), "topic" (string), "circle" (one of {circles}), "funnel_stage" (one of {stages}), \
"branded" (true or false), "reason" (one short sentence on why a buyer asks this)."""


_RESEARCH_INSTRUCTIONS = """You research a company so a team can track how AI assistants like ChatGPT and Claude talk \
about it.

Use web search to read {domain} itself: search for site:{domain} first and read its homepage, product and pricing \
pages. Describe only what the pages on {domain} say the company sells. Other companies may share its name, so ignore \
every result that is not on {domain}. If you can't find pages on {domain}, set "category" and "description" to \
"unknown" instead of guessing. Then answer with only one JSON object. Do not write research notes or any other text \
before or after it:
{{"brand": "...", "category": "...", "description": "...", "competitors": [{{"name": "...", "domain": "..."}}]}}
"brand" is the name people use for the company. "category" is what buyers call this kind of product, in two to four \
words, such as "product analytics" or "brand template software". "description" is one sentence on what it does and \
who it is for. "competitors" lists at most {max_competitors} companies that sell to the same buyers, with "name" and \
"domain" (the domain of its site, such as example.com). When competitors are given below, list those. Leave out \
{domain} itself, and leave out partners, integrations, marketplaces and review sites.

Brand: {brand}
Competitors: {competitors}"""

RESEARCH_TOKENS = 3000


@frozen
class SiteResearch:
    brand: str
    category: str
    description: str
    competitors: tuple[SuggestedCompetitor, ...]


@frozen
class PromptPattern:
    name: str
    share: float
    instruction: str


# The mix of prompt kinds, modelled on the short, broad prompts PostHog tracks for itself: mostly qualified best-of
# prompts, then competitor alternatives and price, then the brand against a competitor. Branded kinds (comparison and
# about the brand) add up to the branded cap, 20%, so the cap never drops prompts the mix asked for. It leans B2B:
# consumer sites, such as stores, will need other patterns later (product type for a need, gift and price-range
# questions). Change the mix here; the shares are rounded to whole prompts and sum to the count.
PROMPT_MIX: tuple[PromptPattern, ...] = (
    PromptPattern(
        name="best-of",
        share=0.40,
        instruction='best-of prompts, such as "best {category} tool", "best {category} for <an audience or a stack>" '
        'or "best {category} with <a feature buyers ask about>"',
    ),
    PromptPattern(
        name="alternatives and price",
        share=0.25,
        instruction='alternatives and price prompts, such as "best <competitor> alternatives", "cheaper '
        'alternatives to <competitor>" or "cheapest {category} tool for <an audience>"',
    ),
    PromptPattern(
        name="which to use",
        share=0.15,
        instruction='"which to use" prompts, such as "which {category} tool should I use for <a stack or a '
        'situation>?"',
    ),
    PromptPattern(
        name="comparison",
        share=0.15,
        instruction='comparison prompts that name {brand}, such as "{brand} vs <competitor>", "{brand} vs '
        '<competitor> for <a use case>" or "which {category} tool is better, {brand} or <competitor>?"',
    ),
    PromptPattern(
        name="about the brand",
        share=0.05,
        instruction='prompts about {brand} itself, such as "{brand} pricing", "is {brand} free?" or "is {brand} good '
        'for <an audience>?"',
    ),
)


def mix_counts(count: int, mix: tuple[PromptPattern, ...] = PROMPT_MIX) -> list[tuple[PromptPattern, int]]:
    total = sum(pattern.share for pattern in mix)
    exact = [count * pattern.share / total for pattern in mix]
    counts = [int(value) for value in exact]
    by_remainder = sorted(range(len(mix)), key=lambda i: exact[i] - counts[i], reverse=True)
    for i in by_remainder[: count - sum(counts)]:
        counts[i] += 1
    return list(zip(mix, counts))


@frozen
class SuggestedPromptSet:
    prompts: tuple[PromptSuggestion, ...]
    competitors: tuple[SuggestedCompetitor, ...]


@frozen
class _AnswerParts:
    competitors: list[Any]
    prompts: list[Any]


def branded_limit(count: int) -> int:
    """How many prompts in a set of `count` may name the brand. A set heavy with them inflates the visibility
    number, because assistants name a brand whenever the question does."""
    return max(1, count // 5)


def _plain(value: str, max_len: int) -> str:
    return sanitize_user_text(value, max_len)


def _count(request: PromptSuggestionRequest) -> int:
    return min(max(request.count, 1), MAX_SUGGESTIONS)


def build_suggestion_instructions(
    request: PromptSuggestionRequest,
    existing_prompts: list[str],
    *,
    branded_max: int | None = None,
    research: SiteResearch | None = None,
) -> str:
    count = _count(request)
    brand = _plain(request.brand, 200)
    if research is not None:
        brand = brand or _plain(research.brand, 200)
    brand_name = brand or "the brand"
    existing = [_plain(prompt, MAX_PROMPT_LENGTH) for prompt in existing_prompts[:MAX_EXISTING_PROMPTS_IN_INSTRUCTIONS]]
    branded_max = branded_limit(count) if branded_max is None else branded_max
    branded_rule = (
        f"Most prompts must not name {brand_name}. Add at most {branded_max} branded prompts, such as "
        f'"what is {brand_name}" or "{brand_name} vs [competitor]"; those check how accurately assistants describe '
        "the brand."
        if branded_max > 0
        else f"Do not name {brand_name} in any prompt."
    )
    instructions = _INSTRUCTIONS.format(
        domain=_plain(request.domain, 200),
        count=count,
        brand=brand or "infer it from the site",
        branded_rule=branded_rule,
        max_competitors=MAX_SUGGESTED_COMPETITORS,
        research=_KNOWN_PARAGRAPH
        if research is not None
        else _RESEARCH_PARAGRAPH.format(domain=_plain(request.domain, 200)),
        known=(
            f"What it does and who it is for: {_plain(research.description, 1000) or 'unknown'}\n"
            f"Category: {_plain(research.category, 200) or 'unknown'}"
            if research is not None
            else f"What it does and who it is for: {_plain(request.description, 1000) or 'infer it from the site'}"
        ),
        competitors=", ".join(_plain(c, 200) for c in request.competitors) or "infer the main ones",
        topics=", ".join(_plain(t, PROMPT_TOPIC_MAX_LENGTH) for t in request.topics) or "choose 3 to 6 topics",
        existing="\n".join(f"- {prompt}" for prompt in existing) or "- none",
        circles=", ".join(PromptCircle.values),
        stages=", ".join(FunnelStage.values),
        mix="\n".join(
            "  - "
            + str(n)
            + " "
            + pattern.instruction.replace("{brand}", brand_name).replace(
                "{category}", _plain(research.category, 200) if research and research.category else "<category>"
            )
            for pattern, n in mix_counts(count)
            if n > 0
        ),
    )
    return instructions


def prompt_key(text: str) -> str:
    return normalize_prompt(text).lower()


def parse_suggestions(text: str, *, count: int, existing_keys: set[str]) -> list[PromptSuggestion]:
    """Turn the model's answer into suggestions, dropping malformed items, duplicates and prompts
    the team already tracks. The model read third-party pages, so every string is sanitized."""
    seen = set(existing_keys)
    suggestions: list[PromptSuggestion] = []
    for item in _answer_parts(text).prompts:
        if not isinstance(item, dict):
            continue
        raw_prompt = normalize_prompt(visible(str(item.get("prompt") or "")))
        prompt = normalize_prompt(_plain(raw_prompt, MAX_PROMPT_LENGTH))
        # Sanitizing that changes visible text (a stripped tag, a cut) would track wording nobody asks, so the item goes.
        if not prompt or prompt != raw_prompt or prompt_key(prompt) in seen:
            continue
        circle = str(item.get("circle") or "")
        stage = str(item.get("funnel_stage") or "")
        if circle not in PromptCircle.values or stage not in FunnelStage.values:
            continue
        seen.add(prompt_key(prompt))
        suggestions.append(
            PromptSuggestion(
                prompt=prompt,
                topic=_plain(str(item.get("topic") or ""), PROMPT_TOPIC_MAX_LENGTH),
                circle=PromptCircle(circle),
                funnel_stage=FunnelStage(stage),
                branded=item.get("branded") is True or circle == PromptCircle.BRANDED,
                reason=_plain(str(item.get("reason") or ""), REASON_MAX_LENGTH),
            )
        )
        if len(suggestions) >= count:
            break
    return suggestions


def _answer_parts(text: str) -> _AnswerParts:
    """The competitors and prompt items of the answer: an object holding both, or a bare array of prompt items,
    which earlier instructions asked for and a model can still return."""
    decoder = json.JSONDecoder()
    for start in (i for i, char in enumerate(text) if char == "{"):
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("prompts"), list):
            competitors = value.get("competitors")
            return _AnswerParts(
                competitors=competitors if isinstance(competitors, list) else [], prompts=value["prompts"]
            )
    try:
        return _AnswerParts(competitors=[], prompts=answer_items(text))
    except UnreadableAnswerError as error:
        raise PromptSuggestionError(UNREADABLE_ANSWER_ERROR) from error


def _registrable(raw: str) -> str | None:
    raw = raw.strip()
    domain = catalog.registrable_domain(raw if "//" in raw else f"//{raw}") if raw else None
    return domain if domain and "." in domain else None


def parse_competitors(text: str, *, own_domain: str | None) -> list[SuggestedCompetitor]:
    return _competitors_from(_answer_parts(text).competitors, own_domain=own_domain)


def _competitors_from(items: list[Any], *, own_domain: str | None) -> list[SuggestedCompetitor]:
    competitors: list[SuggestedCompetitor] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        domain = _registrable(visible(str(item.get("domain") or "")))
        if domain is None or domain == own_domain or any(c.domain == domain for c in competitors):
            continue
        name = _plain(visible(str(item.get("name") or "")), BRAND_NAME_MAX_LENGTH).strip()
        competitors.append(SuggestedCompetitor(name=name or catalog.placeholder_name(domain), domain=domain))
        if len(competitors) >= MAX_SUGGESTED_COMPETITORS:
            break
    return competitors


def _requested_competitors(given: tuple[str, ...], found: tuple[SuggestedCompetitor, ...]) -> list[SuggestedCompetitor]:
    competitors: list[SuggestedCompetitor] = []
    for raw in given:
        text = _plain(raw, BRAND_NAME_MAX_LENGTH).strip()
        domain = _registrable(text) if " " not in text else None
        match = next(
            (c for c in found if (c.domain == domain if domain else c.name.lower() == text.lower())),
            None,
        )
        if match is None and text:
            match = SuggestedCompetitor(name=catalog.placeholder_name(domain) if domain else text, domain=domain or "")
        if match is not None and match not in competitors:
            competitors.append(match)
    return competitors


def _transient(error: Exception) -> bool:
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    response = getattr(error, "response", None)
    return response is not None and (response.status_code == 429 or response.status_code >= 500)


def _ask(
    gateway: AIGatewayConfig,
    instructions: str,
    *,
    team_id: int,
    trace_id: str,
    deadline: float,
    max_tokens: int,
    max_searches: int,
    failure: str = "Prompt suggestions failed. Try again in a minute.",
) -> ClaudeAnswer:
    for attempt in (1, 2):
        try:
            answer = ask_with_web_search(
                gateway,
                instructions,
                team_id=team_id,
                trace_id=trace_id,
                aeo_feature="prompt_suggestions",
                max_tokens=max_tokens,
                max_searches=max_searches,
                deadline=deadline,
                model=settings.AEO_SETUP_MODEL,
            )
        except AICreditsExhausted as error:
            logger.info("aeo_prompt_suggestions_out_of_credits", team_id=team_id, trace_id=trace_id)
            raise PromptSuggestionError(OUT_OF_AI_CREDITS_MESSAGE) from error
        except (requests.RequestException, ValueError) as error:
            logger.warning(
                "aeo_prompt_suggestions_failed",
                team_id=team_id,
                trace_id=trace_id,
                error=type(error).__name__,
                attempt=attempt,
            )
            # A rate limit or a gateway hiccup usually clears in seconds, and failing here fails the whole setup.
            if attempt == 1 and _transient(error) and deadline - time.monotonic() > TRANSIENT_RETRY_SECONDS * 2:
                time.sleep(TRANSIENT_RETRY_SECONDS)
                continue
            if getattr(getattr(error, "response", None), "status_code", None) == 402:
                raise PromptSuggestionError(SPEND_LIMIT_ERROR) from error
            raise PromptSuggestionError(failure) from error
        break
    if answer is None:
        logger.warning("aeo_prompt_suggestions_timed_out", team_id=team_id, trace_id=trace_id)
        raise PromptSuggestionError("Prompt suggestions took too long. Try again with fewer prompts.")
    return answer


def generate_suggestions(
    team_id: int,
    request: PromptSuggestionRequest,
    *,
    context_prompts: list[str],
    existing_keys: set[str],
    deadline: float | None = None,
    branded_max: int | None = None,
    retry_unreadable: bool = True,
    research: SiteResearch | None = None,
) -> SuggestedPromptSet:
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        raise PromptSuggestionError("Prompt suggestions are not available on this instance")
    if deadline is None:
        deadline = time.monotonic() + DEADLINE_SECONDS
    instructions = build_suggestion_instructions(request, context_prompts, branded_max=branded_max, research=research)
    attempts = 2 if retry_unreadable else 1
    for attempt in range(1, attempts + 1):
        trace_id = str(uuid.uuid4())
        answer = _ask(
            gateway,
            instructions,
            team_id=team_id,
            trace_id=trace_id,
            deadline=deadline,
            max_tokens=min(BASE_SUGGESTION_TOKENS + TOKENS_PER_SUGGESTION * _count(request), MAX_SUGGESTION_TOKENS),
            # After research the call only writes, but the search tool still needs a use to be offered.
            max_searches=1 if research is not None else MAX_SUGGESTION_SEARCHES,
        )
        try:
            prompts = parse_suggestions(answer.text, count=MAX_SUGGESTIONS, existing_keys=existing_keys)
        except PromptSuggestionError:
            # The gateway logs this call as a success, so an unreadable answer is only visible here.
            logger.warning(
                "aeo_prompt_suggestions_unreadable",
                team_id=team_id,
                trace_id=trace_id,
                stop_reason=answer.stop_reason,
                attempt=attempt,
            )
            if attempt == attempts:
                raise
            continue
        return SuggestedPromptSet(
            prompts=tuple(prompts),
            competitors=tuple(parse_competitors(answer.text, own_domain=_registrable(request.domain))),
        )
    raise PromptSuggestionError(UNREADABLE_ANSWER_ERROR)


def _research_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for start in (i for i, char in enumerate(text) if char == "{"):
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and ("category" in value or "competitors" in value):
            return value
    raise PromptSuggestionError(UNREADABLE_ANSWER_ERROR)


def parse_research(text: str, *, own_domain: str | None) -> SiteResearch:
    value = _research_object(text)
    found = value.get("competitors")
    competitors = _competitors_from(found if isinstance(found, list) else [], own_domain=own_domain)
    return SiteResearch(
        brand=_plain(visible(str(value.get("brand") or "")), BRAND_NAME_MAX_LENGTH).strip(),
        category=_plain(visible(str(value.get("category") or "")), PROMPT_TOPIC_MAX_LENGTH * 2).strip(),
        description=_plain(visible(str(value.get("description") or "")), 1000).strip(),
        competitors=tuple(competitors),
    )


def research_site(team_id: int, request: PromptSuggestionRequest, *, deadline: float | None = None) -> SiteResearch:
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        raise PromptSuggestionError("Prompt suggestions are not available on this instance")
    if deadline is None:
        deadline = time.monotonic() + DEADLINE_SECONDS
    instructions = _RESEARCH_INSTRUCTIONS.format(
        domain=_plain(request.domain, 200),
        brand=_plain(request.brand, 200) or "infer it from the site",
        competitors=", ".join(_plain(c, 200) for c in request.competitors) or "infer the main ones",
        max_competitors=MAX_SUGGESTED_COMPETITORS,
    )
    for attempt in (1, 2):
        trace_id = str(uuid.uuid4())
        answer = _ask(
            gateway,
            instructions,
            team_id=team_id,
            trace_id=trace_id,
            deadline=deadline,
            max_tokens=RESEARCH_TOKENS,
            max_searches=MAX_SUGGESTION_SEARCHES,
            failure="Reading your site failed. Try again in a minute.",
        )
        try:
            return parse_research(answer.text, own_domain=_registrable(request.domain))
        except PromptSuggestionError:
            logger.warning("aeo_site_research_unreadable", team_id=team_id, trace_id=trace_id, attempt=attempt)
            if attempt == 2:
                raise
    raise PromptSuggestionError(UNREADABLE_ANSWER_ERROR)


def _job_key(team_id: int, job_id: str) -> str:
    return f"aeo_prompt_suggestions:{team_id}:{job_id}"


def _save_job(team_id: int, job: PromptSuggestionJob, *, started_at: float | None = None) -> None:
    if started_at is None:
        stored = caches[SUGGESTION_CACHE_ALIAS].get(_job_key(team_id, job.id))
        started_at = stored.get("started_at", time.time()) if isinstance(stored, dict) else time.time()
    caches[SUGGESTION_CACHE_ALIAS].set(
        _job_key(team_id, job.id),
        {
            "started_at": started_at,
            "status": job.status.value,
            "error": job.error,
            "suggestions": [
                {
                    "prompt": s.prompt,
                    "topic": s.topic,
                    "circle": s.circle.value,
                    "funnel_stage": s.funnel_stage.value,
                    "branded": s.branded,
                    "reason": s.reason,
                }
                for s in job.suggestions
            ],
            "competitors": [{"name": c.name, "domain": c.domain} for c in job.competitors],
        },
        timeout=SUGGESTION_JOB_TTL_SECONDS,
    )


def load_job(team_id: int, job_id: str) -> PromptSuggestionJob:
    stored = caches[SUGGESTION_CACHE_ALIAS].get(_job_key(team_id, job_id))
    if not isinstance(stored, dict):
        raise PromptSuggestionJobNotFoundError(job_id)
    started_at = stored.get("started_at", 0)
    if stored["status"] == SuggestionJobStatus.PENDING and time.time() - started_at > SUGGESTION_JOB_STALE_SECONDS:
        # A hard kill or a lost task never writes a final status.
        job = PromptSuggestionJob(id=job_id, status=SuggestionJobStatus.FAILED, error=STALE_JOB_ERROR)
        _save_job(team_id, job, started_at=started_at)
        return job
    return PromptSuggestionJob(
        id=job_id,
        status=SuggestionJobStatus(stored["status"]),
        error=stored["error"],
        suggestions=tuple(
            PromptSuggestion(
                prompt=item["prompt"],
                topic=item["topic"],
                circle=PromptCircle(item["circle"]),
                funnel_stage=FunnelStage(item["funnel_stage"]),
                branded=item["branded"],
                reason=item["reason"],
            )
            for item in stored["suggestions"]
        ),
        competitors=tuple(
            SuggestedCompetitor(name=item["name"], domain=item["domain"]) for item in stored.get("competitors", [])
        ),
    )


def create_job(team_id: int) -> PromptSuggestionJob:
    job = PromptSuggestionJob(id=str(uuid.uuid4()), status=SuggestionJobStatus.PENDING)
    _save_job(team_id, job, started_at=time.time())
    return job


def fail_job(team_id: int, job_id: str, error: str) -> None:
    _save_job(team_id, PromptSuggestionJob(id=job_id, status=SuggestionJobStatus.FAILED, error=error))


def _untracked(team_id: int, candidates: tuple[PromptSuggestion, ...]) -> list[PromptSuggestion]:
    # Every version of every prompt counts, archived ones included, so a suggestion never revives retired wording.
    # Only the candidates are looked up, so the work does not grow with the team's prompt history.
    tracked = set(
        AEOPromptVersion.objects.for_team(team_id)
        .annotate(key=Lower("text"))
        .filter(key__in=[prompt_key(candidate.prompt) for candidate in candidates])
        .values_list("key", flat=True)
    )
    return [c for c in candidates if prompt_key(c.prompt) not in tracked]


def _cap_branded(
    candidates: list[PromptSuggestion], *, limit: int, pattern: re.Pattern[str] | None
) -> list[PromptSuggestion]:
    """Keep the first `limit` prompts that name the brand and drop the rest. A prompt counts as branded by the
    same name match the dashboard's branded split uses, whatever the model labeled it."""
    kept: list[PromptSuggestion] = []
    branded = 0
    for candidate in candidates:
        if not candidate.branded and pattern is not None and pattern.search(candidate.prompt):
            candidate = dataclasses.replace(candidate, branded=True)
        if candidate.branded:
            if branded >= limit:
                continue
            branded += 1
        kept.append(candidate)
    return kept


def suggest_prompts(
    team_id: int, request: PromptSuggestionRequest, *, research: SiteResearch | None = None
) -> SuggestedPromptSet:
    count = _count(request)
    limit = branded_limit(count)
    own_domain = _registrable(request.domain)
    pattern = brand_pattern([own_domain]) if own_domain else None
    prompts = list(
        AEOPrompt.objects.for_team(team_id)
        .order_by("-created_at")
        .values_list("prompt", flat=True)[:MAX_EXISTING_PROMPTS_IN_INSTRUCTIONS]
    )
    # The calls share one deadline, so a retry or a top-up cannot outlast the task's time limit.
    deadline = time.monotonic() + DEADLINE_SECONDS
    if research is not None and not request.competitors:
        request = dataclasses.replace(request, competitors=tuple(c.name for c in research.competitors))
    first = generate_suggestions(
        team_id, request, context_prompts=prompts, existing_keys=set(), deadline=deadline, research=research
    )
    found = _cap_branded(_untracked(team_id, first.prompts), limit=limit, pattern=pattern)[:count]
    competitors = research.competitors if research is not None else first.competitors
    if len(found) < count:
        try:
            more = generate_suggestions(
                team_id,
                dataclasses.replace(
                    request,
                    count=count - len(found),
                    competitors=request.competitors or tuple(c.name for c in competitors),
                ),
                context_prompts=[*(s.prompt for s in found), *prompts],
                existing_keys={prompt_key(s.prompt) for s in found},
                deadline=deadline,
                branded_max=limit - sum(1 for s in found if s.branded),
                retry_unreadable=False,
                research=research,
            )
        except PromptSuggestionError:
            logger.warning("aeo_prompt_suggestions_top_up_failed", team_id=team_id, missing=count - len(found))
        else:
            found = _cap_branded([*found, *_untracked(team_id, more.prompts)], limit=limit, pattern=pattern)[:count]
            competitors = competitors or more.competitors
    if request.competitors:
        competitors = tuple(_requested_competitors(request.competitors, competitors))
    return SuggestedPromptSet(prompts=tuple(found), competitors=competitors)


def run_job(team_id: int, job_id: str, request: PromptSuggestionRequest) -> None:
    try:
        found = suggest_prompts(team_id, request)
    except PromptSuggestionError as error:
        fail_job(team_id, job_id, str(error))
        return
    _save_job(
        team_id,
        PromptSuggestionJob(
            id=job_id,
            status=SuggestionJobStatus.COMPLETED,
            suggestions=found.prompts,
            competitors=found.competitors,
        ),
    )
