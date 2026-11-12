"""Facade for the AEO product.

The only module other products (and core) are allowed to import for data
capabilities. Celery wiring is re-exported from facade/tasks.py.
"""

from __future__ import annotations

import re
import uuid
import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import (
    Aggregate,
    Avg,
    BooleanField,
    Count,
    Exists,
    ExpressionWrapper,
    Max,
    Min,
    OuterRef,
    Q,
    QuerySet,
    Value,
)
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from posthog.exceptions_capture import capture_exception
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.user import User
from posthog.redis import get_client

from products.aeo.backend import (
    catalog,
    dashboard,
    engine_settings,
    gaps,
    keyword_suggestions,
    keywords,
    rankings,
    suggestions,
)
from products.aeo.backend.brand import brand_names, brand_pattern, branded_filter, mention_filter, segment_filter
from products.aeo.backend.engines import MAX_PROMPT_LENGTH, is_target_host, top_domains
from products.aeo.backend.facade.contracts import (
    PROMPT_TOPIC_MAX_LENGTH,
    Brand,
    BrandCreate,
    BrandCreateError,
    BrandedSegment,
    BrandKind,
    BrandNotFoundError,
    BrandSource,
    BrandStatus,
    BrandSyncResult,
    BrandUpdate,
    CheckMode,
    CitationGap,
    CitationRunSummary,
    EngineSetting,
    EngineSettingUpdate,
    Keyword,
    KeywordCreateResult,
    KeywordLimitError,
    KeywordModifierReport,
    KeywordReport,
    KeywordSuggestionJob,
    KeywordSuggestionRequest,
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
    PromptSetCounts,
    PromptSetDomain,
    PromptSetEngineCounts,
    PromptSetOverview,
    PromptSetRankings,
    PromptSetSearch,
    PromptSetSearchPrompt,
    PromptSetTopicCounts,
    PromptStats,
    PromptSuggestionJob,
    PromptSuggestionRequest,
    PromptTextConflictError,
    PromptTopic,
    PromptUpdate,
    PromptUpdateError,
    PromptVersion,
    VisibilityDashboard,
)
from products.aeo.backend.models import AEOBrand, AEOCitationCheck, AEOPrompt, AEOPromptVersion
from products.aeo.backend.runner import run_citation_checks
from products.aeo.backend.scope import SCOPE_SQL, CheckScope, scope_filter, scope_sql_params, scope_without_segment
from products.aeo.backend.seeding import PromptCandidate, normalize_prompt, prompt_hash, upsert_prompts
from products.aeo.backend.tasks.tasks import (
    recompute_aeo_own_citations_task,
    suggest_aeo_keywords_task,
    suggest_aeo_prompts_task,
)


def run_citation_checks_for_team(team_id: int) -> CitationRunSummary:
    """Run the team's active prompt set against every configured answer engine
    and record one citation check per prompt x engine."""
    team = Team.objects.get(id=team_id)
    summary, _ = run_citation_checks(team)
    return summary


def list_citation_gaps(team_id: int, *, since: dt.datetime) -> list[CitationGap]:
    return gaps.list_citation_gaps(team_id, since=since)


NEEDS_IMPROVEMENT_DAYS = 30


def list_prompts(
    team_id: int,
    *,
    limit: int,
    offset: int,
    topic: str | None = None,
    active: bool | None = None,
    include_archived: bool = False,
    needs_improvement: bool = False,
    branded: bool | None = None,
    needs_improvement_days: int = NEEDS_IMPROVEMENT_DAYS,
    needs_improvement_engine: str | None = None,
) -> tuple[list[Prompt], int]:
    """One page of the team's prompt set and the total count, paged in SQL.
    A topic of "" selects the prompts that have no topic. `needs_improvement` reads the answers of the last
    `needs_improvement_days` days, from one engine when `needs_improvement_engine` is set."""
    prompts = AEOPrompt.objects.for_team(team_id)
    if branded is not None:
        names_brand = branded_filter(catalog.own_domains(team_id), field="prompt")
        prompts = prompts.filter(names_brand if branded else ~names_brand)
    if not include_archived:
        prompts = prompts.filter(archived_at__isnull=True)
    if topic is not None:
        prompts = prompts.filter(topic=topic)
    if active is not None:
        prompts = prompts.filter(active=active)
    if needs_improvement:
        # Only the current wording counts, as in citation gaps: checks before version 2 carry no version.
        answered = AEOCitationCheck.objects.for_team(team_id).filter(
            Q(prompt_version=OuterRef("current_version")) | Q(prompt_version__isnull=True, prompt__current_version=1),
            prompt_id=OuterRef("pk"),
            mode=CheckMode.WEB_SEARCH,
            check_failed=False,
            created_at__gte=timezone.now() - dt.timedelta(days=needs_improvement_days),
        )
        if needs_improvement_engine is not None:
            answered = answered.filter(engine=needs_improvement_engine)
        prompts = prompts.filter(Exists(answered), ~Exists(answered.filter(cited=True)))
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
    since: dt.datetime | None = None,
    include_answer_text: bool = True,
) -> tuple[list[PromptCheck], int]:
    """One page of a prompt's check history on every engine, newest first, and the total count. With
    `include_answer_text` off, `answer_text` is None on every check and is not read from the database."""
    prompt = _get_prompt_row(team_id, prompt_id)
    checks = AEOCitationCheck.objects.for_team(team_id).filter(prompt_id=prompt.id)
    if engine is not None:
        checks = checks.filter(engine=engine)
    if since is not None:
        checks = checks.filter(created_at__gte=since)
    if version is not None:
        # Checks recorded before versions existed carry no version and ran version 1.
        in_version = (
            Q(prompt_version=version) | Q(prompt_version__isnull=True) if version == 1 else Q(prompt_version=version)
        )
        checks = checks.filter(in_version)
    fields = _CHECK_FIELDS if include_answer_text else tuple(f for f in _CHECK_FIELDS if f != "answer_text")
    page = checks.order_by("-created_at", "-id").values(*fields)[offset : offset + limit]
    return [_to_prompt_check(row) for row in page], checks.count()


MAX_OVERVIEW_DOMAINS = 20
MAX_OVERVIEW_SEARCHES = 20
MAX_SEARCH_PROMPTS = 5


def _check_counts(target_domains: list[str], *, prompts: bool = False) -> dict[str, Aggregate]:
    """Aggregates for a set of checks, with the distinct prompts behind them when `prompts` is set.
    `mentioned` and `prompts_cited` filter on the `cited` column, and an annotation named `cited`
    would shadow that column for every later annotation in the same call, so they must come first."""
    counts: dict[str, Aggregate] = {
        "checks": Count("id"),
        "mentioned": Count("id", filter=Q(check_failed=False) & mention_filter(target_domains)),
    }
    if prompts:
        counts["prompts_cited"] = Count("prompt_id", distinct=True, filter=Q(cited=True))
    counts["cited"] = Count("id", filter=Q(cited=True))
    counts["failed"] = Count("id", filter=Q(check_failed=True))
    # The position is null unless the answer cited the brand, so the mean covers cited answers only.
    counts["avg_position"] = Avg("target_best_position")
    if prompts:
        counts["prompts"] = Count("prompt_id", distinct=True)
    return counts


def _daily_engine_counts(
    checks: QuerySet[AEOCitationCheck], tz: ZoneInfo, target_domains: list[str]
) -> tuple[PromptDailyEngineStats, ...]:
    return tuple(
        PromptDailyEngineStats(
            date=row["date"],
            engine=row["engine"],
            checks=row["checks"],
            cited=row["cited"],
            mentioned=row["mentioned"],
            failed=row["failed"],
            avg_position=row["avg_position"],
        )
        for row in checks.annotate(date=TruncDate("created_at", tzinfo=tz))
        .values("date", "engine")
        # Spelled out rather than `**_check_counts(...)` so the row keys stay typed. `mentioned` filters on the
        # `cited` column, so it has to come before the annotation named `cited`.
        .annotate(
            checks=Count("id"),
            mentioned=Count("id", filter=Q(check_failed=False) & mention_filter(target_domains)),
            cited=Count("id", filter=Q(cited=True)),
            failed=Count("id", filter=Q(check_failed=True)),
            avg_position=Avg("target_best_position"),
        )
        .order_by("date", "engine")
    )


def get_prompt_stats(team_id: int, prompt_id: str, *, timezone_name: str, days: int) -> PromptStats:
    """Totals per engine over the prompt's whole history, plus per-day counts, engine consensus on
    the cited domains, brand sentiment and the words of the web searches over the last `days` days
    in the team's timezone."""
    prompt = _get_prompt_row(team_id, prompt_id)
    target_domains = catalog.own_domains(team_id)
    # Every engine gets its own row, the no-search ones included. Only the parts read from citations and
    # searches below use web-search answers alone.
    checks = AEOCitationCheck.objects.for_team(team_id).filter(prompt_id=prompt.id)
    engines = tuple(
        PromptEngineStats(
            engine=row["engine"],
            checks=row["checks"],
            cited=row["cited"],
            mentioned=row["mentioned"],
            failed=row["failed"],
            avg_position=row["avg_position"],
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
            avg_position=Avg("target_best_position"),
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
    daily = _daily_engine_counts(in_window, tz, target_domains)
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
    report = _PromptWindowReport.from_checks(answered.filter(mode=CheckMode.WEB_SEARCH))

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


_SET_COUNT_KEYS = ("checks", "failed", "cited", "mentioned", "prompts", "prompts_cited", "avg_position")


def _set_counts(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in _SET_COUNT_KEYS}


_TOP_DOMAINS_SQL = f"""
    SELECT host, count(*) AS checks_citing
    FROM posthog_aeo_citation_check AS check_row, jsonb_array_elements_text(check_row.top_cited_domains) AS host
    WHERE check_row.team_id = %s AND check_row.created_at >= %s AND check_row.check_failed = false
        AND check_row.mode = 'web_search' AND {SCOPE_SQL}
    GROUP BY host
    ORDER BY checks_citing DESC, host
    LIMIT %s
"""


def _top_domains(
    team_id: int, *, since: dt.datetime, answers: int, target_domains: list[str], scope: CheckScope
) -> tuple[PromptSetDomain, ...]:
    """Domains ranked by how many answered checks in the window cited them, counted in Postgres from
    each check's distinct hosts. `answers` is the number of answered checks the shares are over."""
    if answers == 0:
        return ()
    # The ORM reads above map a child environment to its parent; raw SQL has to do the same.
    team_id = resolve_effective_team_id(team_id)
    with connection.cursor() as cursor:
        cursor.execute(
            _TOP_DOMAINS_SQL,
            [team_id, since, *scope_sql_params(scope, target_domains), MAX_OVERVIEW_DOMAINS],
        )
        rows = cursor.fetchall()
    return tuple(
        PromptSetDomain(
            domain=domain,
            answers=count,
            share_of_answers=count / answers,
            is_target=is_target_host(domain, target_domains),
        )
        for domain, count in rows
    )


# One statement, so the window is read once: `searches` has one row per answered check and distinct
# search it ran, lowercased with whitespace collapsed; `ranked` keeps the top searches and `top_prompts`
# the prompts that ran each of them most. Postgres materializes `searches` because both read it.
_TOP_SEARCHES_SQL = f"""
    WITH searches AS MATERIALIZED (
        SELECT DISTINCT check_row.id, check_row.prompt_id, check_row.engine, check_row.cited,
            lower(btrim(regexp_replace(query, '\\s+', ' ', 'g'))) AS query
        FROM posthog_aeo_citation_check AS check_row,
            jsonb_array_elements_text(
                CASE WHEN jsonb_typeof(check_row.search_queries) = 'array' THEN check_row.search_queries ELSE '[]'::jsonb END
            ) AS query
        WHERE check_row.team_id = %s AND check_row.created_at >= %s AND check_row.check_failed = false
            AND check_row.mode = 'web_search'
            AND {SCOPE_SQL}
    ),
    ranked AS (
        SELECT query, count(DISTINCT prompt_id) AS prompts, count(*) AS answers,
            count(*) FILTER (WHERE cited) AS cited, array_agg(DISTINCT engine ORDER BY engine) AS engines
        FROM searches
        WHERE query <> ''
        GROUP BY query
        ORDER BY prompts DESC, answers DESC, query
        LIMIT %s
    ),
    top_prompts AS (
        SELECT query, prompt_id,
            row_number() OVER (PARTITION BY query ORDER BY count(*) DESC, prompt_id) AS prompt_rank
        FROM searches
        WHERE query IN (SELECT query FROM ranked)
        GROUP BY query, prompt_id
    )
    SELECT ranked.query, ranked.prompts, ranked.answers, ranked.cited, ranked.engines,
        array_remove(array_agg(top_prompts.prompt_id ORDER BY top_prompts.prompt_rank), NULL)
    FROM ranked
    LEFT JOIN top_prompts ON top_prompts.query = ranked.query AND top_prompts.prompt_rank <= %s
    GROUP BY ranked.query, ranked.prompts, ranked.answers, ranked.cited, ranked.engines
    ORDER BY ranked.prompts DESC, ranked.answers DESC, ranked.query
"""


def _top_searches(
    team_id: int, *, since: dt.datetime, target_domains: list[str], scope: CheckScope
) -> tuple[PromptSetSearch, ...]:
    """The searches the engines ran while answering, ranked by how many prompts triggered them,
    each with the prompts that ran it most."""
    team_id = resolve_effective_team_id(team_id)
    with connection.cursor() as cursor:
        cursor.execute(
            _TOP_SEARCHES_SQL,
            [
                team_id,
                since,
                *scope_sql_params(scope, target_domains),
                MAX_OVERVIEW_SEARCHES,
                MAX_SEARCH_PROMPTS,
            ],
        )
        rows = cursor.fetchall()
    texts = {
        row["id"]: row["prompt"]
        for row in AEOPrompt.objects.for_team(team_id)
        .filter(id__in={prompt_id for *_, prompt_ids in rows for prompt_id in prompt_ids})
        .values("id", "prompt")
    }
    return tuple(
        PromptSetSearch(
            query=query,
            prompts=prompts,
            answers=answers,
            cited=cited,
            engines=tuple(engines),
            top_prompts=tuple(
                PromptSetSearchPrompt(id=str(prompt_id), text=texts[prompt_id])
                for prompt_id in prompt_ids
                if prompt_id in texts
            ),
        )
        for query, prompts, answers, cited, engines, prompt_ids in rows
    )


def get_prompt_set_overview(
    team_id: int,
    *,
    timezone_name: str,
    days: int,
    branded: BrandedSegment = BrandedSegment.ALL,
    engine: str | None = None,
    topic: str | None = None,
) -> PromptSetOverview:
    """Web-search checks across the whole prompt set over the last `days` days in the team's timezone, the same
    counts for the `days` days before, the current window split per engine and per topic, and how often each
    engine names the brand without search against with it. `branded` keeps the checks, and the active prompts,
    on one side of the branded split. `engine` and `topic` keep the checks of one engine or one topic, and
    `topic` also keeps the active prompts that have it now."""
    scope = CheckScope(segment=branded, engine=engine, topic=topic)
    target_domains = catalog.own_domains(team_id)
    tz = ZoneInfo(timezone_name)
    window_to = timezone.now().astimezone(tz).date()
    window_from = window_to - dt.timedelta(days=days - 1)
    window_start = dt.datetime.combine(window_from, dt.time.min, tzinfo=tz)
    previous_start = window_start - dt.timedelta(days=days)
    counts = _check_counts(target_domains, prompts=True)

    # The branded split counts both sides, so it narrows by engine and topic only.
    all_checks = AEOCitationCheck.objects.for_team(team_id).filter(
        scope_filter(scope_without_segment(scope), target_domains), mode=CheckMode.WEB_SEARCH
    )
    split = all_checks.filter(created_at__gte=window_start, check_failed=False).aggregate(
        branded=Count("id", filter=branded_filter(target_domains)),
        answers=Count("id"),
    )
    checks = all_checks.filter(segment_filter(branded, target_domains))
    current = checks.filter(created_at__gte=window_start)
    previous = checks.filter(created_at__gte=previous_start, created_at__lt=window_start)
    engines = tuple(
        PromptSetEngineCounts(engine=row["engine"], **_set_counts(row))
        for row in current.values("engine").annotate(**counts).order_by("engine")
    )

    # Checks carry the topic they ran with, and prompts carry their topic now, so a topic with no
    # check in the window still gets a row, with its prompt count and no rate.
    prompts = AEOPrompt.objects.for_team(team_id).filter(
        segment_filter(branded, target_domains, field="prompt"), archived_at__isnull=True, active=True
    )
    if topic is not None:
        prompts = prompts.filter(topic=topic)
    active_prompts = {row["topic"]: row["prompts"] for row in prompts.values("topic").annotate(prompts=Count("id"))}
    topic_checks = {
        row["prompt_topic"]: row for row in current.values("prompt_topic").annotate(**counts).order_by("prompt_topic")
    }
    no_checks: dict[str, Any] = {**dict.fromkeys(_SET_COUNT_KEYS, 0), "avg_position": None}
    topics = tuple(
        PromptSetTopicCounts(
            topic=topic,
            active_prompts=active_prompts.get(topic, 0),
            **_set_counts(topic_checks.get(topic, no_checks)),
        )
        for topic in sorted(active_prompts.keys() | topic_checks.keys())
    )

    current_counts = PromptSetCounts(**_set_counts(current.aggregate(**counts)))
    return PromptSetOverview(
        daily=_daily_engine_counts(current, tz, target_domains),
        days=days,
        window_from=window_from,
        window_to=window_to,
        prompts_tracked=sum(active_prompts.values()),
        target_domains=tuple(target_domains),
        brand_names=brand_names(target_domains),
        branded=branded,
        engine=engine,
        topic=topic,
        current=current_counts,
        previous=PromptSetCounts(**_set_counts(previous.aggregate(**counts))),
        branded_answers=split["branded"],
        non_branded_answers=split["answers"] - split["branded"],
        engines=engines,
        topics=topics,
        top_domains=_top_domains(
            team_id,
            since=window_start,
            answers=current_counts.checks - current_counts.failed,
            target_domains=target_domains,
            scope=scope,
        ),
        top_searches=_top_searches(team_id, since=window_start, target_domains=target_domains, scope=scope),
    )


def get_prompt_set_rankings(
    team_id: int,
    *,
    timezone_name: str,
    days: int,
    branded: BrandedSegment = BrandedSegment.ALL,
    engine: str | None = None,
    topic: str | None = None,
) -> PromptSetRankings:
    """How often answers named the project against the brands behind the domains the engines cite
    most, over the last `days` days in the team's timezone, with the domains and pages cited most.
    `branded`, `engine` and `topic` keep the checks on one side of the branded split, of one engine, or of
    one topic."""
    return rankings.get_rankings(
        team_id,
        target_domains=catalog.own_domains(team_id),
        timezone_name=timezone_name,
        days=days,
        scope=CheckScope(segment=branded, engine=engine, topic=topic),
    )


def create_visibility_dashboard(team: Team, user: User) -> VisibilityDashboard:
    """Create the "AI visibility weekly" dashboard. Each call creates a new one, so a person who deleted or
    edited theirs can start over."""
    created = dashboard.create_visibility_dashboard(team, user)
    return VisibilityDashboard(id=created.id, name=created.name or dashboard.DASHBOARD_NAME)


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
            evidence={"via": item.origin.value}
            | ({"external_visibility": item.external_visibility} if item.external_visibility is not None else {}),
        )
        for item in prompts
    ]
    result = upsert_prompts(team, candidates)
    return PromptImportResult(created=result["created"], updated=result["updated"], skipped=result["skipped"])


def sync_brands_from_run(team_id: int, run_id: str) -> BrandSyncResult:
    return catalog.sync_brands_from_run(team_id, run_id)


def list_engine_settings(team_id: int) -> list[EngineSetting]:
    """Every engine the product knows, in display order, with whether and how often the project runs it."""
    return engine_settings.list_engine_settings(team_id)


def update_engine_setting(team_id: int, engine: str, change: EngineSettingUpdate) -> EngineSetting:
    """Raises EngineNotFoundError for an unknown engine id."""
    return engine_settings.update_engine_setting(team_id, engine, change)


def list_own_domains(team_id: int) -> list[str]:
    """The registrable domains that count as the team itself in citations, from its own brands."""
    return catalog.own_domains(team_id)


def list_brands(
    team_id: int,
    *,
    limit: int,
    offset: int,
    kind: BrandKind | None = None,
    status: BrandStatus | None = None,
    search: str | None = None,
) -> tuple[list[Brand], int]:
    """One page of the team's brand catalog, by domain, and the total count."""
    rows = AEOBrand.objects.for_team(team_id)
    if search:
        rows = rows.filter(Q(domain__icontains=search) | Q(name__icontains=search))
    if kind is not None:
        rows = rows.filter(kind=kind)
    if status is not None:
        rows = rows.filter(status=status)
    page = rows.order_by("domain")[offset : offset + limit]
    return [_to_brand(brand) for brand in page], rows.count()


def get_brand(team_id: int, brand_id: str) -> Brand:
    return _to_brand(_get_brand_row(team_id, brand_id))


# A burst of catalog edits shares one recompute, and each edit waits at most this long for it.
RECOMPUTE_DEBOUNCE_SECONDS = 60
# One DNS label: letters, digits and inner hyphens, at most 63 characters.
_DNS_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


def create_brand(team_id: int, new: BrandCreate) -> Brand:
    raw = new.domain.strip()
    domain = catalog.registrable_domain(raw if "//" in raw else f"//{raw}")
    if domain is None or not _is_dns_name(domain):
        raise BrandCreateError(f"'{new.domain}' is not a valid domain. Use a domain such as example.com.")
    duplicate = BrandCreateError(
        f"The catalog already has {domain}. Update the existing brand instead of adding it again."
    )
    if AEOBrand.objects.for_team(team_id).filter(domain=domain).exists():
        raise duplicate
    try:
        # A savepoint, so a concurrent add of the same domain surfaces as a duplicate, not a broken transaction.
        with transaction.atomic():
            brand = AEOBrand.objects.for_team(team_id).create(
                team_id=resolve_effective_team_id(team_id),
                name=new.name or catalog.placeholder_name(domain),
                domain=domain,
                kind=new.kind,
                status=BrandStatus.CONFIRMED,
                source=BrandSource.MANUAL,
                aliases=_clean_aliases(new.aliases),
            )
    except IntegrityError as error:
        raise duplicate from error
    if catalog.counts_as_own(brand.kind, brand.status):
        _recompute_own_citations_on_commit(brand.team_id)
    return _to_brand(brand)


def update_brand(team_id: int, brand_id: str, change: BrandUpdate) -> Brand:
    brand = _get_brand_row(team_id, brand_id)
    # Only the fields sent are written, so two people editing different fields do not undo each other.
    changed: list[str] = []
    if change.name is not None:
        brand.name = change.name
        changed.append("name")
    if change.kind is not None:
        brand.kind = change.kind
        changed.append("kind")
    if change.status is not None:
        brand.status = change.status
        changed.append("status")
    if change.aliases is not None:
        brand.aliases = _clean_aliases(change.aliases)
        changed.append("aliases")
    if changed:
        brand.save(update_fields=[*changed, "updated_at"])
    # Any kind or status edit, not only one that flips this row: two concurrent edits can each look
    # like no change and still make the brand own together. A recompute with nothing stale writes nothing.
    if "kind" in changed or "status" in changed:
        _recompute_own_citations_on_commit(brand.team_id)
    return _to_brand(brand)


def _recompute_own_citations_on_commit(team_id: int) -> None:
    """Past checks were scored against the own domains of their run day, so a change to the own
    domains recomputes them in the background, once the brand change is visible to the task.

    Edits within the debounce window share one task, which reads the domains when it starts. When the
    enqueue fails, the brand change stands and the reconcile after the next citation run catches up."""

    def enqueue() -> None:
        try:
            if get_client().set(
                f"aeo_own_citations_recompute_queued:{team_id}", 1, nx=True, ex=RECOMPUTE_DEBOUNCE_SECONDS
            ):
                recompute_aeo_own_citations_task.apply_async((team_id,), countdown=RECOMPUTE_DEBOUNCE_SECONDS)
        except Exception as error:
            capture_exception(error, {"team_id": team_id})

    transaction.on_commit(enqueue)


def _is_dns_name(domain: str) -> bool:
    labels = domain.split(".")
    return len(domain) <= 253 and len(labels) >= 2 and all(_DNS_LABEL.match(label) for label in labels)


def _clean_aliases(aliases: tuple[str, ...]) -> list[str]:
    # Order kept and duplicates dropped, so the mention regex gets each name once.
    return list(dict.fromkeys(alias.strip() for alias in aliases if alias.strip()))


def _get_brand_row(team_id: int, brand_id: str) -> AEOBrand:
    try:
        return AEOBrand.objects.for_team(team_id).get(id=brand_id)
    except (AEOBrand.DoesNotExist, ValueError, ValidationError) as error:
        raise BrandNotFoundError(brand_id) from error


def _to_brand(brand: AEOBrand) -> Brand:
    return Brand(
        id=str(brand.id),
        name=brand.name,
        domain=brand.domain,
        kind=BrandKind(brand.kind),
        status=BrandStatus(brand.status),
        source=BrandSource(brand.source),
        aliases=_strings(brand.aliases),
        created_at=brand.created_at,
        updated_at=brand.updated_at,
    )


def list_keywords(team_id: int) -> list[Keyword]:
    """The project's whole keyword list, by keyword. It is capped, so it is never paged."""
    return keywords.list_keywords(team_id)


def get_keyword(team_id: int, keyword_id: str) -> Keyword:
    """Raises KeywordNotFoundError when the project has no such keyword."""
    return keywords.get_keyword(team_id, keyword_id)


def create_keywords(team_id: int, texts: list[str]) -> KeywordCreateResult:
    """Raises KeywordLimitError when the new keywords would take the project past its cap."""
    return keywords.create_keywords(team_id, texts)


def delete_keyword(team_id: int, keyword_id: str) -> None:
    """Raises KeywordNotFoundError when the project has no such keyword."""
    keywords.delete_keyword(team_id, keyword_id)


def get_keyword_report(
    team_id: int,
    *,
    timezone_name: str,
    days: int,
    branded: BrandedSegment = BrandedSegment.ALL,
    engine: str | None = None,
    topic: str | None = None,
) -> KeywordReport:
    """How each keyword shows up in the prompts, the engines' searches and the answers over the last
    `days` days in the team's timezone, counting only the checks on one side of the branded split, of one
    engine, or of one topic when those are set."""
    return keywords.get_keyword_report(
        team_id,
        target_domains=catalog.own_domains(team_id),
        timezone_name=timezone_name,
        days=days,
        scope=CheckScope(segment=branded, engine=engine, topic=topic),
    )


def get_keyword_modifiers(
    team_id: int,
    *,
    timezone_name: str,
    days: int,
    keyword: str | None = None,
    branded: BrandedSegment = BrandedSegment.ALL,
    engine: str | None = None,
    topic: str | None = None,
) -> KeywordModifierReport:
    """The words the engines added to their searches beyond the prompt over the last `days` days,
    optionally only in answers whose searches contain `keyword`, and only in the checks on one side of the
    branded split, of one engine, or of one topic when those are set."""
    return keywords.get_keyword_modifiers(
        team_id,
        target_domains=catalog.own_domains(team_id),
        timezone_name=timezone_name,
        days=days,
        keyword=keyword,
        scope=CheckScope(segment=branded, engine=engine, topic=topic),
    )


def start_keyword_suggestions(team_id: int, request: KeywordSuggestionRequest) -> KeywordSuggestionJob:
    """Queue keyword suggestions and return the pending job. Poll get_keyword_suggestions for the result.
    Raises KeywordLimitError when the keyword list is already full."""
    if keyword_suggestions.suggestion_count(request.count, len(keyword_suggestions.existing_keywords(team_id))) == 0:
        raise KeywordLimitError(keyword_suggestions.NO_ROOM_ERROR)
    job = keyword_suggestions.create_job(team_id)
    try:
        # A task still queued when readers would see the job as failed is dropped by the broker instead of run.
        suggest_aeo_keywords_task.apply_async(
            args=(
                team_id,
                job.id,
                {
                    "domain": request.domain,
                    "brand": request.brand,
                    "description": request.description,
                    "count": request.count,
                },
            ),
            expires=keyword_suggestions.SUGGESTION_JOB_STALE_SECONDS,
        )
    except Exception:
        # Without a queued task nothing would ever finish the pending job.
        keyword_suggestions.fail_job(team_id, job.id, "Keyword suggestions could not start. Try again in a minute.")
        raise
    return job


def get_keyword_suggestions(team_id: int, job_id: str) -> KeywordSuggestionJob:
    """Raises KeywordSuggestionJobNotFoundError when the job is unknown or expired."""
    return keyword_suggestions.load_job(team_id, job_id)


def start_prompt_suggestions(team_id: int, request: PromptSuggestionRequest) -> PromptSuggestionJob:
    """Queue prompt suggestions and return the pending job. Poll get_prompt_suggestions for the result."""
    job = suggestions.create_job(team_id)
    try:
        suggest_aeo_prompts_task.delay(
            team_id,
            job.id,
            {
                "domain": request.domain,
                "brand": request.brand,
                "description": request.description,
                "competitors": list(request.competitors),
                "topics": list(request.topics),
                "count": request.count,
            },
        )
    except Exception:
        # Without a queued task nothing would ever finish the pending job.
        suggestions.fail_job(team_id, job.id, "Prompt suggestions could not start. Try again in a minute.")
        raise
    return job


def get_prompt_suggestions(team_id: int, job_id: str) -> PromptSuggestionJob:
    """Raises PromptSuggestionJobNotFoundError when the job is unknown or expired."""
    return suggestions.load_job(team_id, job_id)


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
    "mode",
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
        mode=CheckMode(row["mode"]),
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
        answer_text=row.get("answer_text"),
        prompt_version=row["prompt_version"],
        brand_sentiment=row["brand_sentiment"],
        brand_sentiment_score=row["brand_sentiment_score"],
    )


def _latest_checks(
    team_id: int, prompt_ids: list[uuid.UUID], target_domains: list[str]
) -> dict[uuid.UUID, tuple[PromptEngineCheck, ...]]:
    if not prompt_ids:
        return {}
    # Pick each prompt and engine's latest check first, so the mention regex only reads those answers.
    latest_ids = (
        AEOCitationCheck.objects.for_team(team_id)
        .filter(prompt_id__in=prompt_ids)
        .order_by("prompt_id", "engine", "-created_at")
        .distinct("prompt_id", "engine")
        .values("id")
    )
    rows = (
        AEOCitationCheck.objects.for_team(team_id)
        .filter(id__in=latest_ids)
        .annotate(
            # A check with no answer text makes the regex match NULL, so default it to not mentioned.
            mentioned=Coalesce(
                ExpressionWrapper(Q(check_failed=False) & mention_filter(target_domains), output_field=BooleanField()),
                Value(False),
            )
        )
        .order_by("prompt_id", "engine")
        .values(
            "prompt_id",
            "engine",
            "mode",
            "cited",
            "mentioned",
            "check_failed",
            "target_best_position",
            "search_queries",
            "created_at",
        )
    )
    checks: dict[uuid.UUID, list[PromptEngineCheck]] = defaultdict(list)
    for row in rows:
        checks[row["prompt_id"]].append(
            PromptEngineCheck(
                engine=row["engine"],
                mode=CheckMode(row["mode"]),
                cited=row["cited"],
                mentioned=row["mentioned"],
                check_failed=row["check_failed"],
                target_best_position=row["target_best_position"],
                search_queries=_strings(row["search_queries"]),
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
    target_domains = catalog.own_domains(team_id)
    latest_checks = _latest_checks(team_id, prompt_ids, target_domains)
    version_counts = _version_counts(team_id, prompt_ids)
    pattern = brand_pattern(target_domains)
    return [
        _to_prompt(
            row,
            latest_checks.get(row.id, ()),
            version_count=version_counts.get(row.id, 0),
            branded=bool(pattern and pattern.search(row.prompt)),
        )
        for row in rows
    ]


def _to_prompt(
    prompt: AEOPrompt, latest_checks: tuple[PromptEngineCheck, ...], *, version_count: int, branded: bool
) -> Prompt:
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
        branded=branded,
    )
