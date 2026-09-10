"""Detect clusters of tickets from distinct requesters about one topic inside a short window.

Volume alone does not discriminate: on a busy inbox a fixed count fires on half of all hours, and
the topics that recur every day are automated mail from one sender. What separates an incident is
several *different* requesters saying the same thing at once, so the requester count is the primary
guard and the learned per-topic baseline only moves the bar up or down from there.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from itertools import batched
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.models.comment import Comment
from posthog.models.scoping import team_scope

from products.conversations.backend.models import (
    Ticket,
    TicketPattern,
    TicketPatternEvidence,
    TicketPatternSource,
    TicketPatternStatus,
    TicketTopicBaseline,
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
MAX_TOPIC_LENGTH = 200
MIN_TOKEN_LENGTH = 4
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
    does doing down during each even every from further having here hers herself himself into itself
    just more most much must myself need never none only other ought ours ourselves over same shall
    should since some still such than that their theirs them themselves then there these they this
    those through under until very were what when where which while whom whose will with within would
    your yours yourself yourselves hello thanks thank please regards issue problem question help
    support ticket request team posthog
    """.split()
)
_TOKEN_RE = re.compile(r"[a-z]+")


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
    tokens = [t for t in _TOKEN_RE.findall(opening) if len(t) >= MIN_TOKEN_LENGTH and t not in _STOPWORDS]
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
            "id", "email_subject", "email_from", "anonymous_traits", "distinct_id", "organization_id", "created_at"
        )
    )
    if not tickets:
        return []
    needs_comment = [str(t.id) for t in tickets if not (t.email_subject or "").strip()]
    first_customer_message: dict[str, str] = {}
    platform_requesters: dict[str, str] = {}
    # Only the email channel carries a subject, so on a widget, Slack or Teams inbox this covers
    # every ticket. Each chunk asks the database for one comment per ticket rather than reading
    # whole conversations back to keep the first message of each.
    for chunk in batched(needs_comment, COMMENT_ID_CHUNK_SIZE, strict=False):
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
            # An absent author_type means a customer wrote it, which is why the missing key counts.
            .filter(
                Q(item_context__author_type="customer")
                | Q(item_context__author_type__isnull=True)
                | Q(item_context__isnull=True)
            )
            .order_by("item_id", "created_at")
            .distinct("item_id")
            .values_list("item_id", "content", "item_context")
        )
        for item_id, content, item_context in comments:
            first_customer_message[item_id] = content
            context = item_context or {}
            # The chat channels carry no email on the ticket, so the sender's platform id is
            # the only stable thing separating one person from a room full of them.
            if context.get("slack_user_id"):
                platform_requesters[item_id] = f"slack:{context['slack_user_id']}"
            elif context.get("teams_user_id"):
                platform_requesters[item_id] = f"teams:{context['teams_user_id']}"
    texts: list[TicketText] = []
    for ticket in tickets:
        text = (ticket.email_subject or "").strip() or first_customer_message.get(str(ticket.id), "")
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
) -> list[TopicCandidate]:
    by_topic: dict[str, list[TicketText]] = defaultdict(list)
    for item in texts:
        for topic in topics_for(item.text):
            by_topic[topic].append(item)

    qualifying: list[TopicCandidate] = []
    for topic, items in by_topic.items():
        if len(items) < settings.min_tickets:
            continue
        requesters = {i.requester for i in items if i.requester is not None}
        if len(requesters) < required_requesters(settings, baselines.get(topic), len(items)):
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
    most specific topic for each distinct ticket set and drop the rest."""
    ordered = sorted(candidates, key=lambda c: (-c.requester_count, -c.ticket_count, -len(c.topic), c.topic))
    kept: list[TopicCandidate] = []
    for candidate in ordered:
        ids = set(candidate.ticket_ids)
        duplicate = any(
            len(ids & set(k.ticket_ids)) / max(min(len(ids), len(k.ticket_ids)), 1) > OVERLAP_COLLAPSE_SHARE
            for k in kept
        )
        if not duplicate:
            kept.append(candidate)
    return kept


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
                pattern = TicketPattern.objects.create(
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
    return f"{candidate.ticket_count} tickets from {candidate.requester_count} customers about: {candidate.topic}"


def _sync_evidence(pattern: TicketPattern, ticket_ids: Iterable[UUID], *, team: Team) -> None:
    existing = pattern.evidence_tickets.count()
    room = MAX_EVIDENCE_TICKETS - existing
    if room <= 0:
        return
    TicketPatternEvidence.objects.bulk_create(
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


def run_detection(team: Team, *, now: datetime) -> DetectionOutcome:
    with team_scope(team.id):
        return _run_detection(team, now=now)


def _run_detection(team: Team, *, now: datetime) -> DetectionOutcome:
    settings = PatternSettings.from_team(team)
    texts = load_ticket_texts(team, since=now - timedelta(minutes=settings.window_minutes), until=now)
    baselines = {b.topic: b for b in TicketTopicBaseline.objects.for_team(team.id)} if texts else {}
    candidates = find_candidates(texts, settings, baselines)

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
    with team_scope(team.id):
        return _refresh_baselines(team, now=now, sample_window_days=sample_window_days)


def _refresh_baselines(team: Team, *, now: datetime, sample_window_days: int) -> int:
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
    feedback = {
        b.topic: (b.dismiss_count, b.confirm_count)
        for b in TicketTopicBaseline.objects.for_team(team.id).only("topic", "dismiss_count", "confirm_count")
    }
    # A topic carrying human feedback survives the delete below, so it is relearned here even when
    # the sample no longer holds it. Left out, its rate and day count would keep describing a window
    # that has passed, and nothing would ever correct them.
    with_feedback = {topic for topic, (dismissed, confirmed) in feedback.items() if dismissed or confirmed}
    rows: list[TicketTopicBaseline] = []
    for topic in sorted(set(per_topic_hours) | with_feedback):
        hours = per_topic_hours.get(topic, {})
        days = per_topic_days.get(topic, set())
        # Only topics seen on more than one day carry a rate worth learning; one-off terms stay unknown
        # so the default bar applies.
        if len(days) < 2 and topic not in with_feedback:
            continue
        counts = list(hours.values()) + [0] * (total_hours - len(hours))
        dismissed, confirmed = feedback.get(topic, (0, 0))
        rows.append(
            TicketTopicBaseline(
                team=team,
                topic=topic,
                mean_per_hour=statistics.fmean(counts),
                spread=statistics.pstdev(counts) if len(counts) > 1 else 0.0,
                distinct_days_seen=len(days),
                dismiss_count=dismissed,
                confirm_count=confirmed,
                sample_window_days=sample_window_days,
                refreshed_at=now,
            )
        )
    with transaction.atomic():
        TicketTopicBaseline.objects.for_team(team.id).exclude(topic__in=[r.topic for r in rows]).filter(
            dismiss_count=0, confirm_count=0
        ).delete()
        TicketTopicBaseline.objects.bulk_create(
            rows,
            update_conflicts=True,
            update_fields=["mean_per_hour", "spread", "distinct_days_seen", "sample_window_days", "refreshed_at"],
            unique_fields=["team", "topic"],
        )
    return len(rows)
