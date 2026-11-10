"""The weekly AI visibility report: a scorecard, every topic's change, the pages to watch and up to
three actions, all derived by fixed rules from the citation checks of two consecutive weeks."""

from __future__ import annotations

import re
import datetime as dt
from collections.abc import Callable, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from django.db import connection
from django.db.models import Count, Q
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.utils import absolute_uri

from products.aeo.backend.brand import SEGMENT_SQL, brand_names, mention_filter, segment_filter, segment_sql_params
from products.aeo.backend.catalog import registrable_domain
from products.aeo.backend.facade.contracts import (
    WEEKLY_REPORT_ACTION_MIN_CHANGE,
    WEEKLY_REPORT_DAYS,
    WEEKLY_REPORT_MAX_ACTIONS,
    BrandedSegment,
    BrandKind,
    BrandStatus,
    WeeklyReport,
    WeeklyReportAction,
    WeeklyReportActionKind,
    WeeklyReportPage,
    WeeklyReportPageRole,
    WeeklyReportScorecard,
    WeeklyReportTopic,
)
from products.aeo.backend.models import AEOBrand, AEOCitationCheck

SEGMENT = BrandedSegment.NON_BRANDED
NO_TOPIC_LABEL = "No topic"

# Answered checks citing each URL, per topic and week. `is_current` splits the two weeks.
_TOPIC_PAGES_SQL = f"""
    SELECT check_row.prompt_topic, url, check_row.created_at >= %s AS is_current, count(DISTINCT check_row.id)
    FROM posthog_aeo_citation_check AS check_row,
        jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(check_row.cited_urls) = 'array' THEN check_row.cited_urls ELSE '[]'::jsonb END
        ) AS url
    WHERE url <> '' AND check_row.team_id = %s AND check_row.created_at >= %s AND check_row.created_at < %s
        AND check_row.check_failed = false AND {SEGMENT_SQL}
    GROUP BY check_row.prompt_topic, url, is_current
"""

_PATH_WORD = re.compile(r"[a-z0-9]+")


@frozen
class _Weeks:
    window_from: dt.date
    window_to: dt.date
    previous_start: dt.datetime
    window_start: dt.datetime
    window_end: dt.datetime


@frozen
class _TopicCounts:
    answers: int
    previous_answers: int
    mentioned: int
    previous_mentioned: int
    cited: int
    previous_cited: int


@frozen
class _TopicPage:
    topic: str
    url: str
    domain: str
    citation_rate: float
    previous_citation_rate: float

    @property
    def change(self) -> float:
        return self.citation_rate - self.previous_citation_rate


def build_weekly_report(
    team_id: int, *, target_domains: list[str], timezone_name: str, end_date: dt.date | None = None
) -> WeeklyReport:
    weeks = _weeks(timezone_name, end_date)
    topic_counts = _topic_counts(team_id, weeks=weeks, target_domains=target_domains)
    scorecard = _scorecard(topic_counts.values())
    topics = _topics(topic_counts)
    pages = _topic_pages(team_id, weeks=weeks, target_domains=target_domains, topic_counts=topic_counts)
    own_domains, competitor_domains = _catalog_domains(team_id, target_domains)
    owned = [page for page in pages if page.domain in own_domains]
    competitors = [page for page in pages if page.domain in competitor_domains]
    watched = _pages_to_watch(owned, competitors)
    app_url = absolute_uri(f"/project/{team_id}/web/content-autopilot")
    return WeeklyReport(
        window_from=weeks.window_from,
        window_to=weeks.window_to,
        previous_from=weeks.window_from - dt.timedelta(days=WEEKLY_REPORT_DAYS),
        previous_to=weeks.window_from - dt.timedelta(days=1),
        brand_names=brand_names(target_domains),
        scorecard=scorecard,
        topics=topics,
        pages=watched,
        actions=_actions(watched, topics, owned, app_url=app_url),
        app_url=app_url,
    )


def _weeks(timezone_name: str, end_date: dt.date | None) -> _Weeks:
    tz = ZoneInfo(timezone_name)
    # The default week ends yesterday, so every day in it is complete.
    window_to = end_date or timezone.now().astimezone(tz).date() - dt.timedelta(days=1)
    window_from = window_to - dt.timedelta(days=WEEKLY_REPORT_DAYS - 1)
    window_start = dt.datetime.combine(window_from, dt.time.min, tzinfo=tz)
    return _Weeks(
        window_from=window_from,
        window_to=window_to,
        previous_start=window_start - dt.timedelta(days=WEEKLY_REPORT_DAYS),
        window_start=window_start,
        window_end=dt.datetime.combine(window_to + dt.timedelta(days=1), dt.time.min, tzinfo=tz),
    )


def _topic_counts(team_id: int, *, weeks: _Weeks, target_domains: list[str]) -> dict[str, _TopicCounts]:
    current = Q(created_at__gte=weeks.window_start)
    previous = ~current
    mentioned = mention_filter(target_domains)
    rows = (
        AEOCitationCheck.objects.for_team(team_id)
        .filter(
            segment_filter(SEGMENT, target_domains),
            check_failed=False,
            created_at__gte=weeks.previous_start,
            created_at__lt=weeks.window_end,
        )
        .values("prompt_topic")
        # No annotation is named `cited`: it would shadow the column for the filters after it.
        .annotate(
            current_answers=Count("id", filter=current),
            previous_answers=Count("id", filter=previous),
            current_mentioned=Count("id", filter=current & mentioned),
            previous_mentioned=Count("id", filter=previous & mentioned),
            current_cited=Count("id", filter=current & Q(cited=True)),
            previous_cited=Count("id", filter=previous & Q(cited=True)),
        )
        .order_by("prompt_topic")
    )
    return {
        row["prompt_topic"]: _TopicCounts(
            answers=row["current_answers"],
            previous_answers=row["previous_answers"],
            mentioned=row["current_mentioned"],
            previous_mentioned=row["previous_mentioned"],
            cited=row["current_cited"],
            previous_cited=row["previous_cited"],
        )
        for row in rows
    }


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _change(current: float | None, previous: float | None) -> float | None:
    return current - previous if current is not None and previous is not None else None


def _scorecard(counts: Iterable[_TopicCounts]) -> WeeklyReportScorecard:
    rows = list(counts)
    answers = sum(row.answers for row in rows)
    previous_answers = sum(row.previous_answers for row in rows)
    visibility = _rate(sum(row.mentioned for row in rows), answers)
    previous_visibility = _rate(sum(row.previous_mentioned for row in rows), previous_answers)
    citation_rate = _rate(sum(row.cited for row in rows), answers)
    previous_citation_rate = _rate(sum(row.previous_cited for row in rows), previous_answers)
    return WeeklyReportScorecard(
        answers=answers,
        previous_answers=previous_answers,
        visibility=visibility,
        previous_visibility=previous_visibility,
        visibility_change=_change(visibility, previous_visibility),
        citation_rate=citation_rate,
        previous_citation_rate=previous_citation_rate,
        citation_rate_change=_change(citation_rate, previous_citation_rate),
    )


def _topics(topic_counts: dict[str, _TopicCounts]) -> tuple[WeeklyReportTopic, ...]:
    topics = []
    for topic, counts in topic_counts.items():
        if counts.answers == 0:
            continue
        visibility = _rate(counts.mentioned, counts.answers)
        previous_visibility = _rate(counts.previous_mentioned, counts.previous_answers)
        topics.append(
            WeeklyReportTopic(
                topic=topic,
                answers=counts.answers,
                previous_answers=counts.previous_answers,
                visibility=visibility,
                previous_visibility=previous_visibility,
                visibility_change=_change(visibility, previous_visibility),
            )
        )
    # Biggest move first, either way. Topics new this week have no change and go last.
    return tuple(
        sorted(
            topics,
            key=lambda topic: (
                topic.visibility_change is None,
                -abs(topic.visibility_change or 0),
                topic.topic,
            ),
        )
    )


def _topic_pages(
    team_id: int, *, weeks: _Weeks, target_domains: list[str], topic_counts: dict[str, _TopicCounts]
) -> list[_TopicPage]:
    """Every page cited in a topic that has answers in both weeks, with its citation rate in each."""
    with connection.cursor() as cursor:
        cursor.execute(
            _TOPIC_PAGES_SQL,
            [
                weeks.window_start,
                resolve_effective_team_id(team_id),
                weeks.previous_start,
                weeks.window_end,
                *segment_sql_params(SEGMENT, target_domains),
            ],
        )
        rows = cursor.fetchall()
    citing: dict[tuple[str, str], list[int]] = {}
    for topic, url, is_current, count in rows:
        citing.setdefault((topic, url), [0, 0])[0 if is_current else 1] += count
    pages = []
    for (topic, url), (current, previous) in citing.items():
        counts = topic_counts.get(topic)
        if counts is None or not counts.answers or not counts.previous_answers:
            continue
        domain = registrable_domain(url)
        if domain is None:
            continue
        pages.append(
            _TopicPage(
                topic=topic,
                url=url,
                domain=domain,
                citation_rate=current / counts.answers,
                previous_citation_rate=previous / counts.previous_answers,
            )
        )
    return pages


def _catalog_domains(team_id: int, target_domains: list[str]) -> tuple[set[str], set[str]]:
    """The project's own registrable domains and its competitors', from the brand catalog. The target
    domains are always the project's own, even before the catalog lists them."""
    own = {domain for target in target_domains if (domain := registrable_domain(f"//{target}"))}
    competitors: set[str] = set()
    rows = (
        AEOBrand.objects.for_team(team_id)
        .filter(kind__in=[BrandKind.OWN, BrandKind.COMPETITOR])
        .exclude(status=BrandStatus.IGNORED)
        .values_list("domain", "kind")
    )
    for domain, kind in rows:
        (own if kind == BrandKind.OWN else competitors).add(domain)
    return own, competitors - own


def _pick(pages: list[_TopicPage], key: Callable[[_TopicPage], float]) -> _TopicPage | None:
    # Ties break on topic and URL, so the same data always picks the same page.
    best = sorted(pages, key=lambda page: (-key(page), page.topic, page.url))
    return best[0] if best else None


def _pages_to_watch(owned: list[_TopicPage], competitors: list[_TopicPage]) -> tuple[WeeklyReportPage, ...]:
    picks = (
        (WeeklyReportPageRole.OWNED_GAINED, _pick([p for p in owned if p.change > 0], lambda p: p.change)),
        (WeeklyReportPageRole.OWNED_LOST, _pick([p for p in owned if p.change < 0], lambda p: -p.change)),
        (WeeklyReportPageRole.COMPETITOR_GAINED, _pick([p for p in competitors if p.change > 0], lambda p: p.change)),
    )
    return tuple(
        WeeklyReportPage(
            role=role,
            url=page.url,
            domain=page.domain,
            topic=page.topic,
            citation_rate=page.citation_rate,
            previous_citation_rate=page.previous_citation_rate,
            change=page.change,
        )
        for role, page in picks
        if page is not None
    )


def _path_words(url: str) -> set[str]:
    try:
        path = urlparse(url).path
    except ValueError:
        return set()
    return set(_PATH_WORD.findall(path.lower()))


def closest_owned_page(competitor_url: str, owned_urls: list[tuple[str, float]]) -> str | None:
    """The owned page whose URL path shares the most words with the competitor's, then the one the
    topic cites most. `owned_urls` holds each owned page with its citation rate this week."""
    words = _path_words(competitor_url)

    def overlap(url: str) -> float:
        other = _path_words(url)
        union = words | other
        return len(words & other) / len(union) if union else 0.0

    ranked = sorted(owned_urls, key=lambda item: (-overlap(item[0]), -item[1], item[0]))
    return ranked[0][0] if ranked else None


def page_label(url: str) -> str:
    """The URL without its scheme or trailing slash, as people read it."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    label = f"{parsed.netloc}{parsed.path}".rstrip("/")
    return label or url


def points(change: float) -> str:
    return f"{abs(change) * 100:.1f}".removesuffix(".0")


def topic_label(topic: str) -> str:
    return topic or NO_TOPIC_LABEL


def _actions(
    pages: tuple[WeeklyReportPage, ...],
    topics: tuple[WeeklyReportTopic, ...],
    owned: list[_TopicPage],
    *,
    app_url: str,
) -> tuple[WeeklyReportAction, ...]:
    """Up to three actions, most specific first: the owned page that lost most, then the competitor
    page that gained most, then the topics that fell most. Moves under the minimum change are left out."""
    actions: list[WeeklyReportAction] = []
    by_role = {page.role: page for page in pages}

    lost = by_role.get(WeeklyReportPageRole.OWNED_LOST)
    if lost is not None and -lost.change >= WEEKLY_REPORT_ACTION_MIN_CHANGE:
        actions.append(
            WeeklyReportAction(
                kind=WeeklyReportActionKind.UPDATE_OWNED_PAGE,
                text=f"Update {page_label(lost.url)}: its citations in {topic_label(lost.topic)} fell {points(lost.change)} pts.",
                url=app_url,
                topic=lost.topic,
                page_url=lost.url,
                compare_url=None,
            )
        )

    rival = by_role.get(WeeklyReportPageRole.COMPETITOR_GAINED)
    if rival is not None and rival.change >= WEEKLY_REPORT_ACTION_MIN_CHANGE:
        compare_url = closest_owned_page(
            rival.url,
            [(page.url, page.citation_rate) for page in owned if page.topic == rival.topic and page.citation_rate > 0],
        )
        against = f" against your {page_label(compare_url)}" if compare_url else ""
        actions.append(
            WeeklyReportAction(
                kind=WeeklyReportActionKind.REVIEW_COMPETITOR_PAGE,
                text=f"Review {page_label(rival.url)}{against}: it gained {points(rival.change)} pts in {topic_label(rival.topic)}.",
                url=app_url,
                topic=rival.topic,
                page_url=rival.url,
                compare_url=compare_url,
            )
        )

    falling = sorted(
        (
            (topic.visibility_change, topic)
            for topic in topics
            if topic.visibility_change is not None and -topic.visibility_change >= WEEKLY_REPORT_ACTION_MIN_CHANGE
        ),
        key=lambda item: (item[0], item[1].topic),
    )
    for change, topic in falling:
        if len(actions) == WEEKLY_REPORT_MAX_ACTIONS:
            break
        actions.append(
            WeeklyReportAction(
                kind=WeeklyReportActionKind.CHECK_TOPIC,
                text=f"{topic_label(topic.topic)} fell {points(change)} pts: check its prompts in AI visibility.",
                url=app_url,
                topic=topic.topic,
                page_url=None,
                compare_url=None,
            )
        )
    return tuple(actions[:WEEKLY_REPORT_MAX_ACTIONS])
