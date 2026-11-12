"""Suggest prompts for a team's AEO prompt set with Claude, through the AI gateway.

Generation runs in a Celery task, and the result waits in the cache for the client to poll.
Suggestions are never saved as prompts. A person reviews them and imports the ones they keep,
so every prompt the runner sends to an engine is still one a person chose.
"""

from __future__ import annotations

import time
import uuid

from django.core.cache import caches
from django.db.models.functions import Lower

import requests
import structlog

from posthog.llm.gateway_client import resolve_ai_gateway_config
from posthog.security.llm_prompt_sanitization import sanitize_user_text

from products.aeo.backend.engines import MAX_PROMPT_LENGTH
from products.aeo.backend.facade.contracts import (
    PROMPT_TOPIC_MAX_LENGTH,
    FunnelStage,
    PromptCircle,
    PromptSuggestion,
    PromptSuggestionError,
    PromptSuggestionJob,
    PromptSuggestionJobNotFoundError,
    PromptSuggestionRequest,
    SuggestionJobStatus,
)
from products.aeo.backend.llm import UnreadableAnswerError, answer_items, ask_with_web_search, visible
from products.aeo.backend.models import AEOPrompt, AEOPromptVersion
from products.aeo.backend.seeding import normalize_prompt

logger = structlog.get_logger(__name__)

MAX_SUGGESTIONS = 50
MAX_SUGGESTION_SEARCHES = 3
# Each suggestion takes roughly 150 tokens of JSON; the rest leaves room for research notes.
BASE_SUGGESTION_TOKENS = 3000
TOKENS_PER_SUGGESTION = 200
MAX_EXISTING_PROMPTS_IN_INSTRUCTIONS = 100
REASON_MAX_LENGTH = 300
# Pinned to the Redis writer: jobs are polled right after they are created, and a replica can lag.
# Keyword suggestion jobs use it too, under their own key prefix.
SUGGESTION_CACHE_ALIAS = "aeo_prompt_suggestions"
SUGGESTION_JOB_TTL_SECONDS = 60 * 60
# A job still pending past the task's hard time limit lost its worker, so readers see it as failed.
SUGGESTION_JOB_STALE_SECONDS = 8 * 60
UNREADABLE_ANSWER_ERROR = "Claude's answer couldn't be read. Try again."
STALE_JOB_ERROR = "Prompt suggestions stopped before they finished. Try again."


_INSTRUCTIONS = """You help a team choose the prompts to track for AI visibility: the questions people ask AI assistants \
like ChatGPT and Claude, where the team wants its site to be mentioned and cited.

Research first. Use web search to read {domain} (its homepage, product and pricing pages) and, if given, the \
competitors' sites, so you understand who the product is for and what it does differently.

Then write {count} prompts that a real buyer would type into an AI assistant. Follow these rules:
- Write each prompt the way a person asks it, in full sentences, not as a search keyword.
- Weight toward prompts where someone is choosing a tool, comparing options or solving a concrete problem. \
Keep only a few prompts about learning a concept.
- Most prompts must not name {brand_name}. Add at most {branded_max} branded prompts, such as "what is {brand_name}" \
or "{brand_name} vs [competitor]"; those check how accurately assistants describe the brand.
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
What it does and who it is for: {description}
Competitors: {competitors}
Topics to cover: {topics}
Prompts the team already tracks, which you must not repeat or rephrase:
{existing}

Answer with only a JSON array, no other text. Each item has these keys:
"prompt" (string), "topic" (string), "circle" (one of {circles}), "funnel_stage" (one of {stages}), \
"branded" (true or false), "reason" (one short sentence on why a buyer asks this)."""


def _plain(value: str, max_len: int) -> str:
    return sanitize_user_text(value, max_len)


def build_suggestion_instructions(request: PromptSuggestionRequest, existing_prompts: list[str]) -> str:
    count = min(max(request.count, 1), MAX_SUGGESTIONS)
    brand = _plain(request.brand, 200)
    existing = [_plain(prompt, MAX_PROMPT_LENGTH) for prompt in existing_prompts[:MAX_EXISTING_PROMPTS_IN_INSTRUCTIONS]]
    return _INSTRUCTIONS.format(
        domain=_plain(request.domain, 200),
        count=count,
        brand=brand or "infer it from the site",
        brand_name=brand or "the brand",
        branded_max=max(1, count // 5),
        description=_plain(request.description, 1000) or "infer it from the site",
        competitors=", ".join(_plain(c, 200) for c in request.competitors) or "infer the main ones",
        topics=", ".join(_plain(t, PROMPT_TOPIC_MAX_LENGTH) for t in request.topics) or "choose 3 to 6 topics",
        existing="\n".join(f"- {prompt}" for prompt in existing) or "- none",
        circles=", ".join(PromptCircle.values),
        stages=", ".join(FunnelStage.values),
    )


def prompt_key(text: str) -> str:
    return normalize_prompt(text).lower()


def parse_suggestions(text: str, *, count: int, existing_keys: set[str]) -> list[PromptSuggestion]:
    """Turn the model's answer into suggestions, dropping malformed items, duplicates and prompts
    the team already tracks. The model read third-party pages, so every string is sanitized."""
    seen = set(existing_keys)
    suggestions: list[PromptSuggestion] = []
    try:
        items = answer_items(text)
    except UnreadableAnswerError as error:
        raise PromptSuggestionError(UNREADABLE_ANSWER_ERROR) from error
    for item in items:
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


def generate_suggestions(
    team_id: int, request: PromptSuggestionRequest, *, context_prompts: list[str], existing_keys: set[str]
) -> list[PromptSuggestion]:
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        raise PromptSuggestionError("Prompt suggestions are not available on this instance")
    count = min(max(request.count, 1), MAX_SUGGESTIONS)
    trace_id = str(uuid.uuid4())
    try:
        answer = ask_with_web_search(
            gateway,
            build_suggestion_instructions(request, context_prompts),
            team_id=team_id,
            trace_id=trace_id,
            aeo_feature="prompt_suggestions",
            max_tokens=BASE_SUGGESTION_TOKENS + TOKENS_PER_SUGGESTION * count,
            max_searches=MAX_SUGGESTION_SEARCHES,
        )
    except (requests.RequestException, ValueError) as error:
        logger.warning("aeo_prompt_suggestions_failed", team_id=team_id, trace_id=trace_id, error=type(error).__name__)
        raise PromptSuggestionError("Prompt suggestions failed. Try again in a minute.") from error
    if answer is None:
        logger.warning("aeo_prompt_suggestions_timed_out", team_id=team_id, trace_id=trace_id)
        raise PromptSuggestionError("Prompt suggestions took too long. Try again with fewer prompts.")
    try:
        # Tracked prompts are removed later, so every usable item is kept here.
        return parse_suggestions(answer.text, count=MAX_SUGGESTIONS, existing_keys=existing_keys)
    except PromptSuggestionError:
        # The gateway logs this call as a success, so an unreadable answer is only visible here.
        logger.warning(
            "aeo_prompt_suggestions_unreadable", team_id=team_id, trace_id=trace_id, stop_reason=answer.stop_reason
        )
        raise


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
    )


def create_job(team_id: int) -> PromptSuggestionJob:
    job = PromptSuggestionJob(id=str(uuid.uuid4()), status=SuggestionJobStatus.PENDING)
    _save_job(team_id, job, started_at=time.time())
    return job


def fail_job(team_id: int, job_id: str, error: str) -> None:
    _save_job(team_id, PromptSuggestionJob(id=job_id, status=SuggestionJobStatus.FAILED, error=error))


def run_job(team_id: int, job_id: str, request: PromptSuggestionRequest) -> None:
    prompts = list(
        AEOPrompt.objects.for_team(team_id)
        .order_by("-created_at")
        .values_list("prompt", flat=True)[:MAX_EXISTING_PROMPTS_IN_INSTRUCTIONS]
    )
    try:
        candidates = generate_suggestions(team_id, request, context_prompts=prompts, existing_keys=set())
    except PromptSuggestionError as error:
        fail_job(team_id, job_id, str(error))
        return
    # Every version of every prompt counts, archived ones included, so a suggestion never revives retired wording.
    # Only the candidates are looked up, so the work does not grow with the team's prompt history.
    tracked = set(
        AEOPromptVersion.objects.for_team(team_id)
        .annotate(key=Lower("text"))
        .filter(key__in=[prompt_key(candidate.prompt) for candidate in candidates])
        .values_list("key", flat=True)
    )
    suggestions = [c for c in candidates if prompt_key(c.prompt) not in tracked][
        : min(max(request.count, 1), MAX_SUGGESTIONS)
    ]
    _save_job(
        team_id,
        PromptSuggestionJob(id=job_id, status=SuggestionJobStatus.COMPLETED, suggestions=tuple(suggestions)),
    )
