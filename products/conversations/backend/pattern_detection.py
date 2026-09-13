"""Detect clusters of tickets from distinct requesters about one topic inside a short window.

Volume alone does not discriminate: on a busy inbox a fixed count fires on half of all hours, and
the topics that recur every day are automated mail from one sender. What separates an incident is
several *different* requesters saying the same thing at once, so the requester count is the primary
guard and the learned per-topic baseline only moves the bar up or down from there.
"""

from __future__ import annotations

import re
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from itertools import batched
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import F, Func, JSONField, Q, Value
from django.db.models.functions import Coalesce

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.comment import Comment

from products.conversations.backend.models import (
    Channel,
    Ticket,
    TicketPattern,
    TicketPatternEvidence,
    TicketPatternSource,
    TicketPatternStatus,
    TicketTopicBaseline,
    TicketTopicOverride,
    TicketTopicOverrideKind,
)

DEFAULT_MIN_REQUESTERS = 5
DEFAULT_MIN_TICKETS = 5
MIN_REQUESTERS_FLOOR = 3
DEFAULT_WINDOW_MINUTES = 60
MINUTES_PER_HOUR = 60
DISMISS_COOLDOWN_MINUTES = 24 * 60
ESCALATION_MULTIPLE = 2
AUTO_RESOLVE_QUIET_WINDOWS = 2
MAX_EVIDENCE_TICKETS = 200
# One IN clause per chunk of subject-less tickets, matching the batch size the billing enrichment
# uses on the same comment index.
COMMENT_ID_CHUNK_SIZE = 1000
# Baseline rows go out in batches: psycopg inlines every value, so one statement for a whole
# team's topics is a multi-megabyte query crossing the connection pooler.
BASELINE_WRITE_BATCH_SIZE = 1000
MAX_TOPIC_LENGTH = 200
MIN_TOKEN_LENGTH = 4
# Subsystem names below the length floor. They are what a terse outage subject turns on, so without
# them "API down" has nothing left to cluster on. Lowering the floor instead would let filler in.
SHORT_TECHNICAL_TERMS = frozenset(
    """
    api cdn cpu css csv dns ftp gpu ios jwt mfa otp pdf php ram sdk sql ssh sso ssl tls url vpn xml
    """.split()
)
# What a ticket is about is in its opening lines. Past this the text is a pasted log or a quoted
# thread, and reading it only multiplies topics: the widget accepts 10k characters per message, and
# the daily refresh holds every topic of every ticket for 30 days at once.
MAX_ANALYZED_CHARS = 2000
# A topic seen on this many distinct days is part of the team's normal and needs a stronger spike.
RECURRING_DAYS = 5
# Two candidates whose ticket sets overlap by more than this share describe the same burst.
OVERLAP_COLLAPSE_SHARE = 0.5

# Requesters on shared mailboxes are distinct people; everyone else collapses to the sender domain.
FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
        "aol.com",
    }
)

_STOPWORDS = frozenset(
    """
    about after again against also another any because been before being between both cannot could
    does doing during each even every from further having here hers herself himself into itself
    just more most much must myself need never none only other ought ours ourselves over same shall
    should since some still such than that their theirs them themselves then there these they this
    those through under until very were what when where which while whom whose will with within would
    your yours yourself yourselves hello thanks thank please regards issue problem question help
    support ticket request team posthog
    """.split()
)
# Any letter, not just ASCII: the previous class silently returned nothing for a subject written
# in Cyrillic, Greek, Arabic or CJK, so those teams got a detector that could never fire. A CJK run
# still comes back as one token, which groups identical subjects but matches no sub-phrase; real
# segmentation is a bigger job than this.
_TOKEN_RE = re.compile(r"[^\W\d_]+")


@frozen
class PatternSettings:
    min_requesters: int = DEFAULT_MIN_REQUESTERS
    min_tickets: int = DEFAULT_MIN_TICKETS
    window_minutes: int = DEFAULT_WINDOW_MINUTES

    @classmethod
    def from_team(cls, team: Team) -> PatternSettings:
        settings = team.conversations_settings or {}
        return cls(
            min_requesters=_coerce_int(settings.get("pattern_min_requesters"), DEFAULT_MIN_REQUESTERS),
            min_tickets=_coerce_int(settings.get("pattern_min_tickets"), DEFAULT_MIN_TICKETS),
            window_minutes=_coerce_int(settings.get("pattern_window_minutes"), DEFAULT_WINDOW_MINUTES),
        )


@frozen
class TicketText:
    ticket_id: UUID
    requester: str | None
    text: str
    created_at: datetime


@frozen
class TopicCandidate:
    topic: str
    ticket_ids: tuple[UUID, ...]
    requester_count: int
    first_ticket_at: datetime

    @property
    def ticket_count(self) -> int:
        return len(self.ticket_ids)

    @property
    def fingerprint(self) -> str:
        return f"terms:{self.topic}"


@frozen
class DetectionOutcome:
    opened: tuple[UUID, ...] = ()
    updated: tuple[UUID, ...] = ()
    suppressed: tuple[str, ...] = ()
    auto_resolved: tuple[UUID, ...] = ()


def _coerce_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def tokenize(text: str) -> list[str]:
    opening = text[:MAX_ANALYZED_CHARS].lower()
    tokens = [
        t
        for t in _TOKEN_RE.findall(opening)
        if (len(t) >= MIN_TOKEN_LENGTH or t in SHORT_TECHNICAL_TERMS) and t not in _STOPWORDS
    ]
    return [_stem(t) for t in tokens]


def _stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_TOKEN_LENGTH:
            return token[: -len(suffix)]
    return token


def topics_for(text: str) -> set[str]:
    """Unigrams plus adjacent bigrams. Bigrams win the collapse step because they are more specific."""
    tokens = tokenize(text)
    topics = set(tokens)
    topics.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:]) if a != b)
    return {t for t in topics if len(t) <= MAX_TOPIC_LENGTH}


def resolve_requester(ticket: Ticket, *, platform_requester: str = "") -> str | None:
    """Who raised the ticket, or None when nothing on it identifies a person.

    None never counts toward the requester guard. Keying an unidentified ticket by its own id
    would make every one of them a new requester, so one person opening several threads would
    clear the bar the detector rests on. Slack and Teams reach this: both store an empty
    distinct id and no email when the platform does not give one.
    """
    if ticket.organization_id:
        return f"org:{ticket.organization_id}"
    # A public widget stores whatever email the browser claimed, so an unverified widget ticket is
    # only as distinct as the browser it came from. Five claimed emails from one session stay one.
    if ticket.channel_source == Channel.WIDGET and ticket.identity_verified is not True:
        return f"widget:{ticket.widget_session_id}" if ticket.widget_session_id else None
    email = (ticket.email_from or (ticket.anonymous_traits or {}).get("email") or "").strip().lower()
    if "@" in email:
        domain = email.rsplit("@", 1)[1]
        return f"email:{email}" if domain in FREE_MAIL_DOMAINS else f"domain:{domain}"
    if ticket.distinct_id:
        return f"distinct:{ticket.distinct_id}"
    return platform_requester or None


def load_ticket_texts(team: Team, *, since: datetime, until: datetime) -> list[TicketText]:
    """One text per ticket: the subject where the channel has one, else the first customer message.

    `Ticket.last_message_text` is deliberately not used; on an aged ticket it is usually a support
    reply, not what the customer asked.
    """
    tickets = list(
        Ticket.objects.filter(team=team, created_at__gte=since, created_at__lt=until).only(
            "id",
            "email_subject",
            "email_from",
            "anonymous_traits",
            "distinct_id",
            "organization_id",
            "channel_source",
            "identity_verified",
            "widget_session_id",
            "created_at",
        )
    )
    if not tickets:
        return []
    first_message: dict[str, str] = {}
    customer_opened: set[str] = set()
    platform_requesters: dict[str, str] = {}
    # One comment per ticket: the earliest public one. Its author decides whether the customer
    # opened the ticket, and it is the text for channels without a subject. A team-composed
    # ticket opens with a team message, and its subject is the team's words, not a report.
    for chunk in batched([str(t.id) for t in tickets], COMMENT_ID_CHUNK_SIZE, strict=False):
        comments = (
            Comment.objects.filter(
                team=team,
                scope="conversations_ticket",
                item_id__in=chunk,
                deleted=False,
            )
            .exclude(content__isnull=True)
            .exclude(content="")
            .filter(~Q(item_context__is_private=True) | Q(item_context__is_private__isnull=True))
            .order_by("item_id", "created_at")
            .distinct("item_id")
            .values_list("item_id", "content", "item_context")
        )
        for item_id, content, item_context in comments:
            context = item_context or {}
            # An absent author_type means a customer wrote it, which is why the missing key counts.
            if context.get("author_type", "customer") != "customer":
                continue
            customer_opened.add(item_id)
            first_message[item_id] = content
            # The chat channels carry no email on the ticket, so the sender's platform id is
            # the only stable thing separating one person from a room full of them.
            if context.get("slack_user_id"):
                platform_requesters[item_id] = f"slack:{context['slack_user_id']}"
            elif context.get("teams_user_id"):
                platform_requesters[item_id] = f"teams:{context['teams_user_id']}"
    texts: list[TicketText] = []
    for ticket in tickets:
        ticket_id = str(ticket.id)
        if ticket_id not in customer_opened:
            continue
        text = (ticket.email_subject or "").strip() or first_message.get(ticket_id, "")
        if text:
            texts.append(
                TicketText(
                    ticket_id=ticket.id,
                    requester=resolve_requester(ticket, platform_requester=platform_requesters.get(str(ticket.id), "")),
                    text=text,
                    created_at=ticket.created_at,
                )
            )
    return texts


def required_requesters(settings: PatternSettings, baseline: TicketTopicBaseline | None, observed_tickets: int) -> int:
    """The bar for one topic: the team default, moved by what the baseline knows about the topic."""
    bar = settings.min_requesters
    if baseline is not None:
        # The baseline learns an hourly rate, but observed_tickets covers the whole window, so the
        # rate is scaled to the window before the two are compared.
        expected_in_window = baseline.mean_per_hour * settings.window_minutes / MINUTES_PER_HOUR
        if baseline.distinct_days_seen >= RECURRING_DAYS:
            bar += 2
        elif baseline.mean_per_hour > 0 and observed_tickets >= 3 * expected_in_window + 3:
            bar -= 2
        bar += min(baseline.dismiss_count, 3)
        bar -= min(baseline.confirm_count, 2)
    return max(bar, MIN_REQUESTERS_FLOOR)


def find_candidates(
    texts: Iterable[TicketText],
    settings: PatternSettings,
    baselines: Mapping[str, TicketTopicBaseline],
    overrides: Mapping[str, str] | None = None,
) -> list[TopicCandidate]:
    overrides = overrides or {}
    muted = {topic for topic, kind in overrides.items() if kind == TicketTopicOverrideKind.MUTE}
    by_topic: dict[str, list[TicketText]] = defaultdict(list)
    for item in texts:
        topics = topics_for(item.text)
        # A mute means "this kind of ticket is not an incident", so the whole ticket leaves the
        # pool. Dropping only the muted term would let the same burst open under its other words.
        if topics & muted:
            continue
        for topic in topics:
            by_topic[topic].append(item)

    qualifying: list[TopicCandidate] = []
    for topic, items in by_topic.items():
        override = overrides.get(topic)
        if len(items) < settings.min_tickets:
            continue
        requesters = {i.requester for i in items if i.requester is not None}
        # A watched topic skips the learned bar and opens at the floor; the person has already said
        # this is worth a look at the first credible sign.
        bar = (
            MIN_REQUESTERS_FLOOR
            if override == TicketTopicOverrideKind.WATCH
            else required_requesters(settings, baselines.get(topic), len(items))
        )
        if len(requesters) < bar:
            continue
        qualifying.append(
            TopicCandidate(
                topic=topic,
                ticket_ids=tuple(sorted({i.ticket_id for i in items}, key=str)),
                requester_count=len(requesters),
                first_ticket_at=min(i.created_at for i in items),
            )
        )
    return _collapse_overlapping(qualifying)


def _collapse_overlapping(candidates: list[TopicCandidate]) -> list[TopicCandidate]:
    """One burst produces many qualifying topics ("login", "password", "login password"). Keep the
    most specific topic for each distinct ticket set and drop the rest.

    Overlap is measured against the larger set. Against the smaller one, a generic term that spans
    two unrelated bursts ("login" over "login password" and "login saml") swallows both, and two
    incidents read as one vague pattern. The larger set lets both specifics through, so the generic
    term is then dropped only when the specifics kept alongside it already cover its tickets.
    """
    ordered = sorted(candidates, key=lambda c: (-c.requester_count, -c.ticket_count, -len(c.topic), c.topic))
    kept: list[TopicCandidate] = []
    for candidate in ordered:
        ids = set(candidate.ticket_ids)
        duplicate = any(
            len(ids & set(k.ticket_ids)) / max(len(ids), len(k.ticket_ids), 1) > OVERLAP_COLLAPSE_SHARE for k in kept
        )
        if not duplicate:
            kept.append(candidate)
    return [c for c in kept if not _covered_by_others(c, kept)]


def _covered_by_others(candidate: TopicCandidate, kept: list[TopicCandidate]) -> bool:
    ids = set(candidate.ticket_ids)
    covered = set().union(*(set(k.ticket_ids) for k in kept if k is not candidate and set(k.ticket_ids) < ids))
    return bool(covered) and ids <= covered


def upsert_pattern(
    candidate: TopicCandidate, *, team: Team, now: datetime, settings: PatternSettings
) -> tuple[TicketPattern | None, bool]:
    """Returns (pattern, was_opened). Callers fire notifications on was_opened, never on the tick.

    None means the candidate was suppressed by a recent dismissal.
    """
    with transaction.atomic():
        quiet_since = now - timedelta(minutes=settings.window_minutes * AUTO_RESOLVE_QUIET_WINDOWS)
        existing = (
            TicketPattern.objects.for_team(team.id)
            .filter(fingerprint=candidate.fingerprint)
            .filter(
                Q(status=TicketPatternStatus.OPEN)
                # A confirmed pattern is the incident a human already acknowledged, so a topic that
                # is still firing updates it rather than opening a second row and alerting again.
                # It stops standing in the way once the topic has been quiet for as long as an
                # auto-resolve needs, which leaves a later flare free to open its own pattern. The
                # status is never rewritten, so the confirmation itself survives.
                | Q(status=TicketPatternStatus.CONFIRMED, last_seen_at__gte=quiet_since)
            )
            .order_by("-last_seen_at")
            .select_for_update()
            .first()
        )
        if existing is not None:
            existing.last_seen_at = now
            existing.ticket_count = candidate.ticket_count
            existing.requester_count = candidate.requester_count
            existing.peak_ticket_count = max(existing.peak_ticket_count, candidate.ticket_count)
            existing.save(
                update_fields=["last_seen_at", "ticket_count", "requester_count", "peak_ticket_count", "updated_at"]
            )
            _sync_evidence(existing, candidate.ticket_ids, team=team)
            return existing, False

        dismissed = (
            TicketPattern.objects.for_team(team.id)
            .filter(
                fingerprint=candidate.fingerprint,
                status=TicketPatternStatus.DISMISSED,
                resolved_at__gte=now - timedelta(minutes=DISMISS_COOLDOWN_MINUTES),
            )
            .order_by("-resolved_at")
            .first()
        )
        if dismissed is not None and candidate.ticket_count < dismissed.peak_ticket_count * ESCALATION_MULTIPLE:
            return None, False

        try:
            # The insert needs its own savepoint. A unique violation aborts the transaction it
            # runs in, so without one there would be nothing left to recover into and the retry
            # below would raise instead of finding the winner.
            with transaction.atomic():
                pattern = TicketPattern.objects.for_team(team.id).create(
                    team=team,
                    fingerprint=candidate.fingerprint,
                    topic=candidate.topic,
                    source=TicketPatternSource.TERMS,
                    title=_fallback_title(candidate),
                    ticket_count=candidate.ticket_count,
                    requester_count=candidate.requester_count,
                    peak_ticket_count=candidate.ticket_count,
                    first_ticket_at=candidate.first_ticket_at,
                    opened_at=now,
                    last_seen_at=now,
                )
        except IntegrityError:
            # A racing tick opened it first; treat this tick as the update it would have been.
            return upsert_pattern(candidate, team=team, now=now, settings=settings)
        _sync_evidence(pattern, candidate.ticket_ids, team=team)
        return pattern, True


def _fallback_title(candidate: TopicCandidate) -> str:
    # The counts sit next to the title everywhere it renders, so the title carries only the topic.
    return candidate.topic.capitalize()


def _sync_evidence(pattern: TicketPattern, ticket_ids: Iterable[UUID], *, team: Team) -> None:
    existing = TicketPatternEvidence.objects.for_team(team.id).filter(pattern=pattern).count()
    room = MAX_EVIDENCE_TICKETS - existing
    if room <= 0:
        return
    TicketPatternEvidence.objects.for_team(team.id).bulk_create(
        [TicketPatternEvidence(team=team, pattern=pattern, ticket_id=tid) for tid in list(ticket_ids)[:room]],
        ignore_conflicts=True,
    )


def auto_resolve_quiet_patterns(
    team: Team, *, now: datetime, settings: PatternSettings, still_firing: set[str]
) -> list[UUID]:
    quiet_since = now - timedelta(minutes=settings.window_minutes * AUTO_RESOLVE_QUIET_WINDOWS)
    quiet = list(
        TicketPattern.objects.for_team(team.id)
        .filter(status=TicketPatternStatus.OPEN, last_seen_at__lt=quiet_since)
        .exclude(fingerprint__in=still_firing)
    )
    resolved: list[UUID] = []
    for pattern in quiet:
        # The row is re-checked in the UPDATE, not held under a lock: an overlapping run that saw the
        # topic fire again, or a human who dismissed it, moves the row out of this filter and the
        # stale transition is dropped instead of applied.
        applied = (
            TicketPattern.objects.for_team(team.id)
            .filter(id=pattern.id, status=TicketPatternStatus.OPEN, last_seen_at__lt=quiet_since)
            .update(
                status=TicketPatternStatus.RESOLVED,
                resolved_at=now,
                evidence={**pattern.evidence, "auto_resolved": True},
                updated_at=now,
            )
        )
        if applied:
            resolved.append(pattern.id)
    return resolved


def load_overrides(team: Team) -> dict[str, str]:
    return dict(TicketTopicOverride.objects.for_team(team.id).filter(enabled=True).values_list("topic", "kind"))


def run_detection(team: Team, *, now: datetime) -> DetectionOutcome:
    settings = PatternSettings.from_team(team)
    texts = load_ticket_texts(team, since=now - timedelta(minutes=settings.window_minutes), until=now)
    baselines = {b.topic: b for b in TicketTopicBaseline.objects.for_team(team.id)} if texts else {}
    overrides = load_overrides(team) if texts else {}
    candidates = find_candidates(texts, settings, baselines, overrides)

    opened: list[UUID] = []
    updated: list[UUID] = []
    suppressed: list[str] = []
    for candidate in candidates:
        pattern, was_opened = upsert_pattern(candidate, team=team, now=now, settings=settings)
        if pattern is None:
            suppressed.append(candidate.topic)
        elif was_opened:
            opened.append(pattern.id)
        else:
            updated.append(pattern.id)
    auto_resolved = auto_resolve_quiet_patterns(
        team, now=now, settings=settings, still_firing={c.fingerprint for c in candidates}
    )
    return DetectionOutcome(
        opened=tuple(opened), updated=tuple(updated), suppressed=tuple(suppressed), auto_resolved=tuple(auto_resolved)
    )


def refresh_baselines(team: Team, *, now: datetime, sample_window_days: int = 30) -> int:
    """Learn each topic's normal hourly rate from the trailing window. Confirm and dismiss counts are
    feedback from humans and survive the refresh."""
    since = now - timedelta(days=sample_window_days)
    texts = load_ticket_texts(team, since=since, until=now)
    per_topic_hours: dict[str, dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
    per_topic_days: dict[str, set[date]] = defaultdict(set)
    for item in texts:
        hour = item.created_at.replace(minute=0, second=0, microsecond=0)
        for topic in topics_for(item.text):
            per_topic_hours[topic][hour] += 1
            per_topic_days[topic].add(item.created_at.date())

    total_hours = max(int((now - since).total_seconds() // 3600), 1)
    # Only rows a human acted on are worth reading back: every other topic starts from zero anyway.
    # A topic carrying feedback survives the delete below, so it is relearned here even when the
    # sample no longer holds it. Left out, its rate and day count would keep describing a window
    # that has passed, and nothing would ever correct them.
    feedback = {
        b.topic: (b.dismiss_count, b.confirm_count)
        for b in TicketTopicBaseline.objects.for_team(team.id)
        .exclude(dismiss_count=0, confirm_count=0)
        .only("topic", "dismiss_count", "confirm_count")
    }
    rows: list[TicketTopicBaseline] = []
    for topic in sorted(set(per_topic_hours) | set(feedback)):
        hours = per_topic_hours.get(topic, {})
        days = per_topic_days.get(topic, set())
        # Only topics seen on more than one day carry a rate worth learning; one-off terms stay unknown
        # so the default bar applies.
        if len(days) < 2 and topic not in feedback:
            continue
        # Every hour the topic missed counts as a zero. Zeros add nothing to either sum, so the
        # rate and the spread come from the hours it did appear in rather than from a list with
        # one entry per hour of the window.
        counts = hours.values()
        mean = sum(counts) / total_hours
        variance = sum(count * count for count in counts) / total_hours - mean * mean
        dismissed, confirmed = feedback.get(topic, (0, 0))
        rows.append(
            TicketTopicBaseline(
                team=team,
                topic=topic,
                mean_per_hour=mean,
                spread=math.sqrt(max(variance, 0.0)),
                distinct_days_seen=len(days),
                dismiss_count=dismissed,
                confirm_count=confirmed,
                sample_window_days=sample_window_days,
                refreshed_at=now,
            )
        )
    with transaction.atomic():
        TicketTopicBaseline.objects.for_team(team.id).bulk_create(
            rows,
            update_conflicts=True,
            update_fields=["mean_per_hour", "spread", "distinct_days_seen", "sample_window_days", "refreshed_at"],
            unique_fields=["team", "topic"],
            batch_size=BASELINE_WRITE_BATCH_SIZE,
        )
        # Everything relearned above carries this run's timestamp, so an older one marks a topic
        # that has dropped out of the window. Comparing on that keeps the team's whole topic list
        # out of the delete statement.
        TicketTopicBaseline.objects.for_team(team.id).filter(
            refreshed_at__lt=now, dismiss_count=0, confirm_count=0
        ).delete()
        mark_baselines_refreshed(team, now=now)
    return len(rows)


BASELINES_REFRESHED_AT_KEY = "pattern_baselines_refreshed_at"


def mark_baselines_refreshed(team: Team, *, now: datetime) -> None:
    """Freshness lives on the team, not on the topic rows: a refresh that learns nothing (an inbox
    imported on one day, a quiet fortnight) writes no rows, and without this the staleness check
    would rerun the 30-day scan on every tick."""
    Team.objects.filter(id=team.id).update(
        conversations_settings=Func(
            Coalesce(F("conversations_settings"), Value({}, output_field=JSONField())),
            Value([BASELINES_REFRESHED_AT_KEY]),
            Value(now.isoformat(), output_field=JSONField()),
            function="jsonb_set",
            output_field=JSONField(),
        )
    )
    settings = dict(team.conversations_settings or {})
    settings[BASELINES_REFRESHED_AT_KEY] = now.isoformat()
    team.conversations_settings = settings


def baselines_refreshed_at(team: Team) -> datetime | None:
    raw = (team.conversations_settings or {}).get(BASELINES_REFRESHED_AT_KEY)
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
