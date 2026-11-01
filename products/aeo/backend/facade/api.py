"""Facade for the AEO product.

The only module other products (and core) are allowed to import for data
capabilities. Celery wiring is re-exported from facade/tasks.py.
"""

from __future__ import annotations

import re
import uuid
import datetime as dt
from collections import Counter, defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Min, Q, QuerySet
from django.db.models.functions import TruncDate
from django.utils import timezone

from posthog.models.team import Team

from products.aeo.backend import gaps
from products.aeo.backend.brand import brand_names, mention_filter
from products.aeo.backend.engines import MAX_PROMPT_LENGTH, top_domains
from products.aeo.backend.facade.contracts import (
    PROMPT_TOPIC_MAX_LENGTH,
    CitationGap,
    CitationRunSummary,
    Prompt,
    PromptAuthor,
    PromptCheck,
    PromptDailyEngineStats,
    PromptEngineCheck,
    PromptEngineDomainShare,
    PromptEngineSentiment,
    PromptEngineStats,
    PromptImport,
    PromptImportResult,
    PromptNotFoundError,
    PromptSearchWord,
    PromptStats,
    PromptTextConflictError,
    PromptTopic,
    PromptUpdate,
    PromptUpdateError,
    PromptVersion,
)
from products.aeo.backend.models import AEOCitationCheck, AEOPrompt, AEOPromptVersion
from products.aeo.backend.runner import run_citation_checks
from products.aeo.backend.seeding import PromptCandidate, normalize_prompt, prompt_hash, upsert_prompts


def run_citation_checks_for_team(team_id: int) -> CitationRunSummary:
    """Run the team's active prompt set against every configured answer engine
    and record one citation check per prompt x engine."""
    team = Team.objects.get(id=team_id)
    summary, _ = run_citation_checks(team)
    return summary


def list_citation_gaps(team_id: int, *, since: dt.datetime) -> list[CitationGap]:
    return gaps.list_citation_gaps(team_id, since=since)


def list_prompts(
    team_id: int,
    *,
    limit: int,
    offset: int,
    topic: str | None = None,
    active: bool | None = None,
    include_archived: bool = False,
) -> tuple[list[Prompt], int]:
    """One page of the team's prompt set and the total count, paged in SQL.
    A topic of "" selects the prompts that have no topic."""
    prompts = AEOPrompt.objects.for_team(team_id)
    if not include_archived:
        prompts = prompts.filter(archived_at__isnull=True)
    if topic is not None:
        prompts = prompts.filter(topic=topic)
    if active is not None:
        prompts = prompts.filter(active=active)
    page = list(prompts.order_by("topic", "-rank", "created_at", "id")[offset : offset + limit])
    return _to_prompts(team_id, page), prompts.count()


def list_prompt_topics(team_id: int) -> list[PromptTopic]:
    rows = (
        AEOPrompt.objects.for_team(team_id)
        .filter(archived_at__isnull=True)
        .values("topic")
        .annotate(prompts=Count("id"))
        .order_by("topic")
    )
    return [PromptTopic(topic=row["topic"], prompts=row["prompts"]) for row in rows]


def get_prompt(team_id: int, prompt_id: str) -> Prompt:
    return _to_prompts(team_id, [_get_prompt_row(team_id, prompt_id)])[0]


def update_prompt(team_id: int, prompt_id: str, change: PromptUpdate, *, user_id: int | None) -> Prompt:
    """Apply a partial edit and return the prompt.

    The prompt keeps its id. A text change adds the next version and makes it current;
    `current_version` points back or forward at an existing one. Archived prompts accept
    only a restore.
    """
    text = _validated_text(change.prompt) if change.prompt is not None else None
    with transaction.atomic():
        # Locks the prompt row, so two concurrent text edits cannot take the same version number.
        prompt = _get_prompt_row(team_id, prompt_id, lock=True)
        _check_update_allowed(prompt, change)
        if change.archived:
            _archive(prompt)
        else:
            if prompt.archived_at is not None:
                prompt.archived_at = None
                # A restore leaves the prompt off unless the request turns it on, so it does not start spending.
                prompt.active = False
            if change.active is not None:
                prompt.active = change.active
            if change.topic is not None:
                prompt.topic = normalize_prompt(change.topic)[:PROMPT_TOPIC_MAX_LENGTH]
            if text is not None and prompt_hash(text) != prompt.prompt_hash:
                _add_version(prompt, text, description=change.version_description or "", user_id=user_id)
            elif change.current_version is not None and change.current_version != prompt.current_version:
                _switch_to_version(prompt, change.current_version)
            _save_edit(prompt)
    return _to_prompts(team_id, [prompt])[0]


def archive_prompt(team_id: int, prompt_id: str) -> None:
    """Archive a prompt so it never runs again. Its versions and checks are kept. Archiving twice is a no-op."""
    with transaction.atomic():
        _archive(_get_prompt_row(team_id, prompt_id, lock=True))


def list_prompt_versions(team_id: int, prompt_id: str) -> list[PromptVersion]:
    """Every version of a prompt, newest first."""
    prompt = _get_prompt_row(team_id, prompt_id)
    rows = (
        AEOPromptVersion.objects.for_team(team_id)
        .filter(prompt_id=prompt.id)
        .select_related("created_by")
        .order_by("-version")
    )
    return [
        PromptVersion(
            version=row.version,
            text=row.text,
            version_description=row.version_description,
            created_by=PromptAuthor(email=row.created_by.email, name=row.created_by.first_name)
            if row.created_by
            else None,
            created_at=row.created_at,
            is_current=row.version == prompt.current_version,
        )
        for row in rows
    ]


def list_prompt_checks(
    team_id: int,
    prompt_id: str,
    *,
    limit: int,
    offset: int,
    engine: str | None = None,
    version: int | None = None,
) -> tuple[list[PromptCheck], int]:
    """One page of a prompt's check history, newest first, and the total count."""
    prompt = _get_prompt_row(team_id, prompt_id)
    checks = AEOCitationCheck.objects.for_team(team_id).filter(prompt_id=prompt.id)
    if engine is not None:
        checks = checks.filter(engine=engine)
    if version is not None:
        # Checks recorded before versions existed carry no version and ran version 1.
        in_version = (
            Q(prompt_version=version) | Q(prompt_version__isnull=True) if version == 1 else Q(prompt_version=version)
        )
        checks = checks.filter(in_version)
    page = checks.order_by("-created_at", "-id").values(*_CHECK_FIELDS)[offset : offset + limit]
    return [_to_prompt_check(row) for row in page], checks.count()


def get_prompt_stats(team_id: int, prompt_id: str, *, timezone_name: str, days: int) -> PromptStats:
    """Totals per engine over the prompt's whole history, plus per-day counts, engine consensus on
    the cited domains, brand sentiment and the words of the web searches over the last `days` days
    in the team's timezone."""
    prompt = _get_prompt_row(team_id, prompt_id)
    target_domains: list[str] = settings.AEO_TARGET_DOMAINS
    checks = AEOCitationCheck.objects.for_team(team_id).filter(prompt_id=prompt.id)
    engines = tuple(
        PromptEngineStats(
            engine=row["engine"],
            checks=row["checks"],
            cited=row["cited"],
            mentioned=row["mentioned"],
            failed=row["failed"],
            first_checked_at=row["first_checked_at"],
            last_checked_at=row["last_checked_at"],
        )
        for row in checks.values("engine")
        # `mentioned` filters on the `cited` column, and an annotation named `cited` would shadow that
        # column for every later annotation in the same call, so it must come first.
        .annotate(
            checks=Count("id"),
            mentioned=Count("id", filter=Q(check_failed=False) & mention_filter(target_domains)),
            cited=Count("id", filter=Q(cited=True)),
            failed=Count("id", filter=Q(check_failed=True)),
            first_checked_at=Min("created_at"),
            last_checked_at=Max("created_at"),
        )
        .order_by("engine")
    )

    tz = ZoneInfo(timezone_name)
    daily_to = timezone.now().astimezone(tz).date()
    daily_from = daily_to - dt.timedelta(days=days - 1)
    window_start = dt.datetime.combine(daily_from, dt.time.min, tzinfo=tz)
    in_window = checks.filter(created_at__gte=window_start)
    daily = tuple(
        PromptDailyEngineStats(
            date=row["date"],
            engine=row["engine"],
            checks=row["checks"],
            cited=row["cited"],
            mentioned=row["mentioned"],
            failed=row["failed"],
        )
        for row in in_window.annotate(date=TruncDate("created_at", tzinfo=tz))
        .values("date", "engine")
        .annotate(
            checks=Count("id"),
            mentioned=Count("id", filter=Q(check_failed=False) & mention_filter(target_domains)),
            cited=Count("id", filter=Q(cited=True)),
            failed=Count("id", filter=Q(check_failed=True)),
        )
        .order_by("date", "engine")
    )
    answered = in_window.filter(check_failed=False)
    sentiment = tuple(
        PromptEngineSentiment(
            engine=row["engine"],
            positive=row["positive"],
            neutral=row["neutral"],
            negative=row["negative"],
            unscored=row["unscored"],
        )
        for row in answered.values("engine")
        .annotate(
            positive=Count("id", filter=Q(brand_sentiment="positive")),
            neutral=Count("id", filter=Q(brand_sentiment="neutral")),
            negative=Count("id", filter=Q(brand_sentiment="negative")),
            unscored=Count("id", filter=Q(brand_sentiment__isnull=True) & mention_filter(target_domains)),
        )
        .order_by("engine")
    )
    report = _PromptWindowReport.from_checks(answered)

    return PromptStats(
        total_checks=sum(engine.checks for engine in engines),
        brand_names=brand_names(target_domains),
        engines=engines,
        daily_from=daily_from,
        daily_to=daily_to,
        daily=daily,
        consensus=report.consensus(),
        sentiment=sentiment,
        top_words=report.top_words(),
    )


MAX_CONSENSUS_DOMAINS = 10
MAX_STATS_WORDS = 20
MIN_SEARCH_WORD_LENGTH = 3
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
SEARCH_STOP_WORDS = frozenset(
    """a an and are as at be best by can do does for from how i in is it its my of on or that the this to top vs
    what which who with without your you""".split()
)


class _PromptWindowReport:
    """Cited domains and web searches across one prompt's answered checks in the window.

    Counts are per check: a domain cited twice in one answer counts once, so every number reads as
    "how many answers", the same unit as the citation rate."""

    def __init__(self) -> None:
        self._domain_checks: Counter[str] = Counter()
        self._engine_checks: Counter[str] = Counter()
        self._engine_domain_checks: Counter[tuple[str, str]] = Counter()
        self._queries: Counter[str] = Counter()

    @classmethod
    def from_checks(cls, answered: QuerySet[AEOCitationCheck]) -> _PromptWindowReport:
        report = cls()
        for row in answered.values("engine", "cited_urls", "search_queries"):
            report.add(row["engine"], _strings(row["cited_urls"]), _strings(row["search_queries"]))
        return report

    def add(self, engine: str, cited_urls: tuple[str, ...], search_queries: tuple[str, ...]) -> None:
        self._engine_checks[engine] += 1
        domains = top_domains(list(cited_urls))
        self._domain_checks.update(domains)
        self._engine_domain_checks.update((engine, domain) for domain in domains)
        self._queries.update(key for key in (" ".join(query.casefold().split()) for query in search_queries) if key)

    def consensus(self) -> tuple[PromptEngineDomainShare, ...]:
        domains = [domain for domain, _ in self._ranked(self._domain_checks, MAX_CONSENSUS_DOMAINS)]
        return tuple(
            PromptEngineDomainShare(
                engine=engine,
                domain=domain,
                checks_citing=self._engine_domain_checks[(engine, domain)],
                checks=checks,
            )
            for engine, checks in sorted(self._engine_checks.items())
            for domain in domains
        )

    def top_words(self) -> tuple[PromptSearchWord, ...]:
        words: Counter[str] = Counter()
        for key, count in self._queries.items():
            for word in set(_WORD.findall(key)):
                if len(word) >= MIN_SEARCH_WORD_LENGTH and word not in SEARCH_STOP_WORDS:
                    words[word] += count
        return tuple(PromptSearchWord(word=word, count=count) for word, count in self._ranked(words, MAX_STATS_WORDS))

    @staticmethod
    def _ranked(counter: Counter[str], limit: int) -> list[tuple[str, int]]:
        # Ties break on the value, so the order is stable between two requests.
        return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit]


def import_prompts(team_id: int, prompts: list[PromptImport]) -> PromptImportResult:
    """Add prompts to the team's set, or update the topic and evidence of
    prompts that already exist. Existing prompts keep their active state."""
    team = Team.objects.get(id=team_id)
    candidates = [
        PromptCandidate(
            text=item.prompt,
            source=AEOPrompt.Source.IMPORTED,
            topic=item.topic,
            evidence={"via": "api"}
            | ({"external_visibility": item.external_visibility} if item.external_visibility is not None else {}),
        )
        for item in prompts
    ]
    result = upsert_prompts(team, candidates)
    return PromptImportResult(created=result["created"], updated=result["updated"], skipped=result["skipped"])


def _get_prompt_row(team_id: int, prompt_id: str, *, lock: bool = False) -> AEOPrompt:
    prompts = AEOPrompt.objects.for_team(team_id)
    try:
        return (prompts.select_for_update() if lock else prompts).get(id=prompt_id)
    except (AEOPrompt.DoesNotExist, ValueError, ValidationError) as error:
        raise PromptNotFoundError(prompt_id) from error


def _validated_text(text: str) -> str:
    normalized = normalize_prompt(text)
    if not normalized:
        raise PromptUpdateError("The prompt text can't be empty.")
    if len(normalized) > MAX_PROMPT_LENGTH:
        raise PromptUpdateError(f"The prompt text can be at most {MAX_PROMPT_LENGTH} characters.")
    return normalized


def _check_update_allowed(prompt: AEOPrompt, change: PromptUpdate) -> None:
    if change.prompt is not None and change.current_version is not None:
        raise PromptUpdateError("Send either 'prompt' or 'current_version', not both.")
    if change.version_description is not None and change.prompt is None:
        raise PromptUpdateError("'version_description' describes a text change. Send it with 'prompt'.")
    changes_text = change.prompt is not None or change.current_version is not None
    if change.archived:
        if changes_text or change.topic is not None or change.active:
            raise PromptUpdateError("Archive a prompt on its own, without other changes.")
    elif prompt.archived_at is None:
        return
    elif change.archived is None:
        raise PromptUpdateError("This prompt is archived. Restore it first.")
    elif changes_text:
        raise PromptUpdateError("Restore the prompt before you change its text.")


def _archive(prompt: AEOPrompt) -> None:
    if prompt.archived_at is None:
        prompt.archived_at = timezone.now()
    prompt.active = False
    prompt.save(update_fields=["archived_at", "active", "updated_at"])


def _add_version(prompt: AEOPrompt, text: str, *, description: str, user_id: int | None) -> None:
    _check_text_is_free(prompt, text)
    versions = AEOPromptVersion.objects.for_team(prompt.team_id).filter(prompt_id=prompt.id)
    latest = versions.aggregate(latest=Max("version"))["latest"]
    if latest is None:
        # A prompt imported by a release without versions has none yet, so record its text as version 1 first.
        AEOPromptVersion.objects.for_team(prompt.team_id).create(
            team_id=prompt.team_id, prompt=prompt, version=1, text=prompt.prompt, created_by_id=prompt.created_by_id
        )
        latest = 1
    version = AEOPromptVersion.objects.for_team(prompt.team_id).create(
        team_id=prompt.team_id,
        prompt=prompt,
        version=latest + 1,
        text=text,
        version_description=description,
        created_by_id=user_id,
    )
    _use_text(prompt, text, version.version)


def _switch_to_version(prompt: AEOPrompt, number: int) -> None:
    version = (
        AEOPromptVersion.objects.for_team(prompt.team_id)
        .filter(prompt_id=prompt.id, version=number)
        .only("text", "version")
        .first()
    )
    if version is None:
        raise PromptUpdateError(f"This prompt has no version {number}.")
    _check_text_is_free(prompt, version.text)
    _use_text(prompt, version.text, version.version)


def _use_text(prompt: AEOPrompt, text: str, version: int) -> None:
    prompt.prompt = text
    prompt.prompt_hash = prompt_hash(text)
    prompt.current_version = version


def _check_text_is_free(prompt: AEOPrompt, text: str) -> None:
    clash = (
        AEOPrompt.objects.for_team(prompt.team_id)
        .filter(prompt_hash=prompt_hash(text))
        .exclude(id=prompt.id)
        .only("archived_at")
        .first()
    )
    if clash is not None:
        raise _text_conflict(archived=clash.archived_at is not None)


def _save_edit(prompt: AEOPrompt) -> None:
    fields = ["active", "topic", "archived_at", "prompt", "prompt_hash", "current_version", "updated_at"]
    try:
        # A savepoint, so a concurrent write of the same text surfaces as a conflict, not a broken transaction.
        with transaction.atomic():
            prompt.save(update_fields=fields)
    except IntegrityError as error:
        raise _text_conflict(archived=False) from error


def _text_conflict(*, archived: bool) -> PromptTextConflictError:
    if archived:
        return PromptTextConflictError("An archived prompt already has this text. Restore that prompt instead.")
    return PromptTextConflictError("Another prompt in the set already has this text.")


_CHECK_FIELDS = (
    "id",
    "run_id",
    "engine",
    "model",
    "created_at",
    "cited",
    "check_failed",
    "error",
    "cited_urls",
    "target_urls",
    "target_best_position",
    "top_cited_domains",
    "search_queries",
    "answer_text",
    "prompt_version",
    "brand_sentiment",
    "brand_sentiment_score",
)


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in value) if isinstance(value, list) else ()


def _to_prompt_check(row: dict[str, Any]) -> PromptCheck:
    return PromptCheck(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        engine=row["engine"],
        model=row["model"],
        created_at=row["created_at"],
        cited=row["cited"],
        check_failed=row["check_failed"],
        error=row["error"],
        cited_urls=_strings(row["cited_urls"]),
        target_urls=_strings(row["target_urls"]),
        target_best_position=row["target_best_position"],
        top_cited_domains=_strings(row["top_cited_domains"]),
        search_queries=_strings(row["search_queries"]),
        answer_text=row["answer_text"],
        prompt_version=row["prompt_version"],
        brand_sentiment=row["brand_sentiment"],
        brand_sentiment_score=row["brand_sentiment_score"],
    )


def _latest_checks(team_id: int, prompt_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[PromptEngineCheck, ...]]:
    if not prompt_ids:
        return {}
    rows = (
        AEOCitationCheck.objects.for_team(team_id)
        .filter(prompt_id__in=prompt_ids)
        .order_by("prompt_id", "engine", "-created_at")
        .distinct("prompt_id", "engine")
        .values("prompt_id", "engine", "cited", "check_failed", "created_at")
    )
    checks: dict[uuid.UUID, list[PromptEngineCheck]] = defaultdict(list)
    for row in rows:
        checks[row["prompt_id"]].append(
            PromptEngineCheck(
                engine=row["engine"],
                cited=row["cited"],
                check_failed=row["check_failed"],
                checked_at=row["created_at"],
            )
        )
    return {prompt_id: tuple(engine_checks) for prompt_id, engine_checks in checks.items()}


def _version_counts(team_id: int, prompt_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not prompt_ids:
        return {}
    rows = (
        AEOPromptVersion.objects.for_team(team_id)
        .filter(prompt_id__in=prompt_ids)
        .values("prompt_id")
        .annotate(versions=Count("id"))
    )
    return {row["prompt_id"]: row["versions"] for row in rows}


def _to_prompts(team_id: int, rows: list[AEOPrompt]) -> list[Prompt]:
    prompt_ids = [row.id for row in rows]
    latest_checks = _latest_checks(team_id, prompt_ids)
    version_counts = _version_counts(team_id, prompt_ids)
    return [_to_prompt(row, latest_checks.get(row.id, ()), version_count=version_counts.get(row.id, 0)) for row in rows]


def _to_prompt(prompt: AEOPrompt, latest_checks: tuple[PromptEngineCheck, ...], *, version_count: int) -> Prompt:
    visibility = (prompt.evidence or {}).get("external_visibility")
    return Prompt(
        id=str(prompt.id),
        prompt=prompt.prompt,
        topic=prompt.topic,
        prompt_source=prompt.prompt_source,
        rank=prompt.rank,
        active=prompt.active,
        last_checked_at=prompt.last_checked_at,
        external_visibility=float(visibility) if isinstance(visibility, int | float) else None,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
        archived_at=prompt.archived_at,
        current_version=prompt.current_version,
        version_count=version_count,
        latest_checks=latest_checks,
    )
