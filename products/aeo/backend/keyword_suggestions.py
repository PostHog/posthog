"""Suggest keywords for a project's keyword list with Claude, through the AI gateway.

Claude ranks the keywords from the site, the tracked prompts and topics, and the web searches the engines ran
while answering those prompts. PostHog has no search-volume data, so the only number on a suggestion is how many
answers searched for it, which PostHog counts itself the way the keyword report does.

Generation runs in a Celery task, and the result waits in the cache for the client to poll. Suggestions are never
saved as keywords. A person reviews them and adds the ones they keep.
"""

from __future__ import annotations

import re
import time
import uuid
import datetime as dt
from collections import Counter
from collections.abc import Sequence

from django.core.cache import caches
from django.utils import timezone

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import resolve_ai_gateway_config
from posthog.security.llm_prompt_sanitization import sanitize_user_text

from products.aeo.backend import catalog
from products.aeo.backend.brand import brand_names
from products.aeo.backend.facade.contracts import (
    KEYWORD_MAX_LENGTH,
    KEYWORD_SUGGESTION_SEARCH_CHECKS,
    KEYWORD_SUGGESTION_SEARCH_DAYS,
    MAX_KEYWORDS_PER_TEAM,
    MAX_SUGGESTED_KEYWORDS,
    BrandKind,
    BrandStatus,
    KeywordSuggestion,
    KeywordSuggestionError,
    KeywordSuggestionJob,
    KeywordSuggestionJobNotFoundError,
    KeywordSuggestionRequest,
    SuggestionJobStatus,
)
from products.aeo.backend.keywords import normalize_keyword
from products.aeo.backend.llm import UnreadableAnswerError, answer_items, ask_with_web_search, visible
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOKeyword, AEOPrompt
from products.aeo.backend.suggestions import (
    REASON_MAX_LENGTH,
    SUGGESTION_CACHE_ALIAS,
    SUGGESTION_JOB_STALE_SECONDS,
    SUGGESTION_JOB_TTL_SECONDS,
)

logger = structlog.get_logger(__name__)

MAX_KEYWORD_WORDS = 4
MAX_KEYWORD_SEARCHES = 2
# Each keyword takes roughly 40 tokens of JSON; the rest leaves room for research notes.
BASE_KEYWORD_TOKENS = 2000
TOKENS_PER_KEYWORD = 80
MAX_SEARCHES_IN_INSTRUCTIONS = 80
MAX_PROMPTS_IN_INSTRUCTIONS = 60
MAX_TOPICS_IN_INSTRUCTIONS = 30
MAX_COMPETITORS_IN_INSTRUCTIONS = 20
NO_ROOM_ERROR = (
    f"The keyword list is full. A project tracks up to {MAX_KEYWORDS_PER_TEAM} keywords. Remove some keywords first."
)
FAILED_ERROR = "Keyword suggestions failed. Try again in a minute."
STALE_JOB_ERROR = "Keyword suggestions stopped before they finished. Try again."
UNREADABLE_ANSWER_ERROR = "The suggestions couldn't be read. Try again."


@frozen
class SearchCount:
    search: str
    checks: int


@frozen
class KeywordContext:
    """What the project already has, read once per job and given to Claude and to the parser."""

    brand_names: tuple[str, ...]
    competitors: tuple[str, ...]
    prompts: tuple[str, ...]
    topics: tuple[str, ...]
    # One tuple per answered check, most recent first, with that check's distinct searches lowercased.
    searches: tuple[tuple[str, ...], ...]
    existing_keywords: frozenset[str]

    @property
    def top_searches(self) -> list[SearchCount]:
        counts = Counter(search for check in self.searches for search in check)
        return [
            SearchCount(search=search, checks=checks)
            for search, checks in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
                :MAX_SEARCHES_IN_INSTRUCTIONS
            ]
        ]


_INSTRUCTIONS = """You help a team choose the keywords to track for AI visibility. A keyword is a word or short phrase, \
such as a product category, a feature or a problem, that the team wants AI assistants like ChatGPT and Claude to \
connect with its brand. For each keyword, the team sees how often it appears in the questions it tracks, in the web \
searches the assistants run while answering, and in their answers.

If the information below is not enough to understand the product, use web search to read {domain}.

Then choose the {count} keywords most worth tracking, the most important first. Follow these rules:
- Prefer keywords the assistants already search for. The searches below come from the team's tracked questions, \
and a keyword that many of them contain is a strong choice.
- Write each keyword in lowercase, in one to {max_words} words, the way a person types it. Use no quotes and no \
punctuation other than hyphens.
- Keep keywords about the category, the problems and the features. Do not name {brand_name} or a competitor, and do \
not add a year.
- Write each keyword so it can appear word for word inside a question or an answer, because it matches as a phrase.
- Do not repeat or reword a keyword the team already tracks.

Brand: {brand}
Site: {domain}
What it does and who it is for: {description}
Competitors: {competitors}
Topics of the tracked questions: {topics}
Questions the team tracks:
{prompts}
Web searches the assistants ran while answering, with the number of answers that ran each:
{searches}
Keywords the team already tracks, which you must not repeat:
{existing}

Answer with only a JSON array, no other text. Each item has these keys:
"keyword" (string), "reason" (one short sentence on why the team should track it)."""


def _plain(value: str, max_len: int) -> str:
    return sanitize_user_text(value, max_len)


def _bullets(values: Sequence[str]) -> str:
    return "\n".join(f"- {value}" for value in values) or "- none"


def build_keyword_instructions(request: KeywordSuggestionRequest, context: KeywordContext, *, count: int) -> str:
    brand = _plain(request.brand, 200)
    return _INSTRUCTIONS.format(
        domain=_plain(request.domain, 200),
        count=count,
        max_words=MAX_KEYWORD_WORDS,
        brand=brand or "infer it from the site",
        brand_name=brand or "the brand",
        description=_plain(request.description, 1000) or "infer it from the site",
        competitors=", ".join(_plain(c, 200) for c in context.competitors[:MAX_COMPETITORS_IN_INSTRUCTIONS])
        or "unknown",
        topics=", ".join(_plain(t, 100) for t in context.topics[:MAX_TOPICS_IN_INSTRUCTIONS]) or "none yet",
        prompts=_bullets([_plain(p, 300) for p in context.prompts[:MAX_PROMPTS_IN_INSTRUCTIONS]]),
        searches=_bullets([f"{_plain(s.search, 200)} ({s.checks})" for s in context.top_searches]),
        existing=_bullets([_plain(k, KEYWORD_MAX_LENGTH) for k in sorted(context.existing_keywords)]),
    )


def _names_a_term(keyword: str, terms: frozenset[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", keyword) for term in terms)


def parse_keyword_suggestions(
    text: str,
    *,
    count: int,
    existing_keywords: frozenset[str],
    excluded_terms: frozenset[str],
    searches: Sequence[Sequence[str]],
) -> list[KeywordSuggestion]:
    """Turn the model's answer into suggestions in the model's order, dropping malformed items, duplicates,
    keywords the list has, and keywords that name the brand. The model read third-party pages,
    so every string is sanitized."""
    try:
        items = answer_items(text)
    except UnreadableAnswerError as error:
        raise KeywordSuggestionError(UNREADABLE_ANSWER_ERROR) from error
    seen = set(existing_keywords)
    suggestions: list[KeywordSuggestion] = []
    for item in items:
        if len(suggestions) >= count:
            break
        if not isinstance(item, dict):
            continue
        raw = normalize_keyword(visible(str(item.get("keyword") or "")))
        keyword = normalize_keyword(_plain(raw, KEYWORD_MAX_LENGTH))
        # Sanitizing that changes visible text (a stripped tag, a cut) would track wording nobody chose, so the item goes.
        if not keyword or keyword != raw or keyword in seen:
            continue
        if len(keyword.split()) > MAX_KEYWORD_WORDS or _names_a_term(keyword, excluded_terms):
            continue
        seen.add(keyword)
        suggestions.append(
            KeywordSuggestion(
                keyword=keyword,
                reason=_plain(str(item.get("reason") or ""), REASON_MAX_LENGTH),
                # Counted per answer, as the keyword report counts `searched_checks`.
                searched_checks=sum(1 for check in searches if any(keyword in search for search in check)),
            )
        )
    return suggestions


def suggestion_count(requested: int, existing: int) -> int:
    """How many keywords to ask for: the request, capped by the suggestion limit and the room left in the list."""
    return max(0, min(requested, MAX_SUGGESTED_KEYWORDS, MAX_KEYWORDS_PER_TEAM - existing))


def existing_keywords(team_id: int) -> frozenset[str]:
    return frozenset(AEOKeyword.objects.for_team(team_id).values_list("keyword", flat=True))


def read_context(team_id: int) -> KeywordContext:
    live_prompts = AEOPrompt.objects.for_team(team_id).filter(archived_at__isnull=True)
    prompts = live_prompts.order_by("-active", "-rank", "-created_at").values_list("prompt", flat=True)
    topics = live_prompts.exclude(topic="").order_by("topic").values_list("topic", flat=True).distinct()
    competitors = (
        AEOBrand.objects.for_team(team_id)
        .filter(kind=BrandKind.COMPETITOR)
        .exclude(status=BrandStatus.IGNORED)
        .order_by("name")
        .values_list("name", flat=True)[:MAX_COMPETITORS_IN_INSTRUCTIONS]
    )
    checks = (
        AEOCitationCheck.objects.for_team(team_id)
        .filter(created_at__gte=timezone.now() - dt.timedelta(days=KEYWORD_SUGGESTION_SEARCH_DAYS), check_failed=False)
        .order_by("-created_at")
        .values_list("search_queries", flat=True)[:KEYWORD_SUGGESTION_SEARCH_CHECKS]
    )
    searches = [
        tuple(dict.fromkeys(" ".join(str(query).split()).lower() for query in queries if query))
        for queries in checks
        if isinstance(queries, list)
    ]
    return KeywordContext(
        brand_names=brand_names(catalog.own_domains(team_id)),
        competitors=tuple(competitors),
        prompts=tuple(prompts[:MAX_PROMPTS_IN_INSTRUCTIONS]),
        topics=tuple(topics[:MAX_TOPICS_IN_INSTRUCTIONS]),
        searches=tuple(searches),
        existing_keywords=existing_keywords(team_id),
    )


def _excluded_terms(request: KeywordSuggestionRequest, context: KeywordContext) -> frozenset[str]:
    terms = set(context.brand_names)
    if request.brand:
        terms.add(normalize_keyword(request.brand))
    terms.discard("")
    return frozenset(terms)


def generate_keyword_suggestions(
    team_id: int, request: KeywordSuggestionRequest, context: KeywordContext, *, count: int
) -> list[KeywordSuggestion]:
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        raise KeywordSuggestionError("Keyword suggestions are not available on this instance")
    trace_id = str(uuid.uuid4())
    try:
        answer = ask_with_web_search(
            gateway,
            build_keyword_instructions(request, context, count=count),
            team_id=team_id,
            trace_id=trace_id,
            aeo_feature="keyword_suggestions",
            max_tokens=BASE_KEYWORD_TOKENS + TOKENS_PER_KEYWORD * count,
            max_searches=MAX_KEYWORD_SEARCHES,
        )
    except (requests.RequestException, ValueError) as error:
        logger.warning("aeo_keyword_suggestions_failed", team_id=team_id, trace_id=trace_id, error=type(error).__name__)
        raise KeywordSuggestionError(FAILED_ERROR) from error
    if answer is None:
        logger.warning("aeo_keyword_suggestions_timed_out", team_id=team_id, trace_id=trace_id)
        raise KeywordSuggestionError("Keyword suggestions took too long. Try again with fewer keywords.")
    try:
        # Keywords added while Claude worked are removed later, so every usable item is kept here.
        return parse_keyword_suggestions(
            answer.text,
            count=MAX_SUGGESTED_KEYWORDS,
            existing_keywords=context.existing_keywords,
            excluded_terms=_excluded_terms(request, context),
            searches=context.searches,
        )
    except KeywordSuggestionError:
        # The gateway logs this call as a success, so an unreadable answer is only visible here.
        logger.warning(
            "aeo_keyword_suggestions_unreadable", team_id=team_id, trace_id=trace_id, stop_reason=answer.stop_reason
        )
        raise


def _job_key(team_id: int, job_id: str) -> str:
    return f"aeo_keyword_suggestions:{team_id}:{job_id}"


def _save_job(team_id: int, job: KeywordSuggestionJob, *, started_at: float | None = None) -> None:
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
                {"keyword": s.keyword, "reason": s.reason, "searched_checks": s.searched_checks}
                for s in job.suggestions
            ],
        },
        timeout=SUGGESTION_JOB_TTL_SECONDS,
    )


def load_job(team_id: int, job_id: str) -> KeywordSuggestionJob:
    stored = caches[SUGGESTION_CACHE_ALIAS].get(_job_key(team_id, job_id))
    if not isinstance(stored, dict):
        raise KeywordSuggestionJobNotFoundError(job_id)
    started_at = stored.get("started_at", 0)
    if stored["status"] == SuggestionJobStatus.PENDING and time.time() - started_at > SUGGESTION_JOB_STALE_SECONDS:
        # A hard kill or a lost task never writes a final status.
        job = KeywordSuggestionJob(id=job_id, status=SuggestionJobStatus.FAILED, error=STALE_JOB_ERROR)
        _save_job(team_id, job, started_at=started_at)
        return job
    return KeywordSuggestionJob(
        id=job_id,
        status=SuggestionJobStatus(stored["status"]),
        error=stored["error"],
        suggestions=tuple(
            KeywordSuggestion(keyword=item["keyword"], reason=item["reason"], searched_checks=item["searched_checks"])
            for item in stored["suggestions"]
        ),
    )


def create_job(team_id: int) -> KeywordSuggestionJob:
    job = KeywordSuggestionJob(id=str(uuid.uuid4()), status=SuggestionJobStatus.PENDING)
    _save_job(team_id, job, started_at=time.time())
    return job


def fail_job(team_id: int, job_id: str, error: str) -> None:
    _save_job(team_id, KeywordSuggestionJob(id=job_id, status=SuggestionJobStatus.FAILED, error=error))


def suggest_keywords(team_id: int, request: KeywordSuggestionRequest) -> list[KeywordSuggestion]:
    """Ask the model for keywords that fit the room left in the list. Raises KeywordSuggestionError."""
    context = read_context(team_id)
    count = suggestion_count(request.count, len(context.existing_keywords))
    if count == 0:
        raise KeywordSuggestionError(NO_ROOM_ERROR)
    candidates = generate_keyword_suggestions(team_id, request, context, count=count)
    # Read the list again, so keywords a person added while the model worked are neither suggested nor overflow the cap.
    existing = existing_keywords(team_id)
    room = suggestion_count(request.count, len(existing))
    return [candidate for candidate in candidates if candidate.keyword not in existing][:room]


def run_job(team_id: int, job_id: str, request: KeywordSuggestionRequest) -> None:
    # A task that waited in a backed-up queue may start after readers saw the job fail, so it must not pay for a call.
    try:
        if load_job(team_id, job_id).status != SuggestionJobStatus.PENDING:
            return
    except KeywordSuggestionJobNotFoundError:
        return
    try:
        suggestions = suggest_keywords(team_id, request)
    except KeywordSuggestionError as error:
        fail_job(team_id, job_id, str(error))
        return
    _save_job(
        team_id,
        KeywordSuggestionJob(id=job_id, status=SuggestionJobStatus.COMPLETED, suggestions=tuple(suggestions)),
    )
