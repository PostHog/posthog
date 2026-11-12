"""The platform's occurrence registry: where appearance alerts read which identities are new, or back.

A source pushes facts into it with `record`: an identity is new, or reappeared, at a time. A source
with no detection of its own registers a feed instead, and the registrar, a scheduled workflow of its
own, records what the feed saw. The registry records every fact whatever any alert filters on, so
what "new" means does not depend on which alerts exist. A check reads facts by when the registry
recorded them, so a fact pushed late, or registered late, is still read by the next check.
"""

import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Final

from django.db import connection, transaction
from django.utils import timezone

from products.alerts_platform.backend.facade.contracts import (
    Occurrence,
    OccurrenceFeed,
    OccurrenceKind,
    OccurrenceWindow,
    SeenIdentity,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertKind
from products.alerts_platform.backend.facade.grouping import UNSTORABLE, bounded_grouping_key
from products.alerts_platform.backend.models import (
    PlatformAlertConfiguration,
    PlatformOccurrence,
    PlatformOccurrenceCursor,
)

# One read of a feed records at most this many identities. A window with more is read again from
# where this one stopped, so a burst takes several reads rather than one oversized transaction.
MAX_IDENTITIES_PER_READ: Final = 5000
# A registry far behind, such as one seeding from the feed's lookback, catches up one span per
# read, so each read scans its own span rather than everything since the cursor. A read the feed
# cannot finish halves the span its cursor keeps, and a finished one doubles it back.
MAX_READ_SPAN: Final = timedelta(days=1)
MIN_READ_SPAN: Final = timedelta(minutes=5)
MIN_STEP: Final = timedelta(microseconds=1)

# A fact is visible once its transaction commits, a moment after `recorded_at` is set. A check reads
# only up to this long ago, so it never passes a fact that is about to become visible.
RECORD_ALLOWANCE: Final = timedelta(seconds=10)
# Bounds on one pushed fact's write, well below a caller's own deadline, so a stalled write ends.
WRITE_LOCK_TIMEOUT_MS: Final = 5_000
WRITE_STATEMENT_TIMEOUT_MS: Final = 10_000

_feeds: dict[SourceKind, OccurrenceFeed] = {}


def has_enabled_alert(source: SourceKind, *, team_id: int) -> bool:
    """Whether the project has an enabled appearance alert on the source, so its facts have a reader."""
    return (
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(source_kind=source.value, alert_kind=PlatformAlertKind.APPEARANCE, enabled=True)
        .exists()
    )


def register_feed(source: SourceKind, feed: OccurrenceFeed) -> None:
    registered = _feeds.get(source)
    if registered is not None and registered is not feed:
        raise RuntimeError(f"A different occurrence feed is already registered for {source} alerts.")
    _feeds[source] = feed


def store_for(source: SourceKind) -> "RegistryStore":
    return RegistryStore(source, _feeds.get(source))


class RegistryStore:
    """The platform's per-project registry of one source's identities."""

    def __init__(self, source: SourceKind, feed: OccurrenceFeed | None) -> None:
        self.source = source
        self.feed = feed

    def ready_until(self, *, team_id: int, now: datetime) -> datetime:
        """How far a check may read. A feed's sightings are read by when the registrar recorded them,
        so a check never waits on the feed itself."""
        return now - RECORD_ALLOWANCE

    def appeared(self, *, team_id: int, since: datetime, until: datetime, limit: int) -> OccurrenceWindow:
        rows = list(
            PlatformOccurrence.objects.for_team(team_id)
            .filter(source_kind=self.source.value, recorded_at__gte=since, recorded_at__lt=until)
            .order_by("recorded_at", "id")[: limit + 1]
        )
        return OccurrenceWindow(
            occurrences=tuple(_occurrence(row) for row in rows[:limit]), truncated=len(rows) > limit
        )

    def catch_up(self, *, team_id: int, now: datetime, budget: timedelta) -> datetime:
        """Registers span after span until the registry reaches what the feed has finished, or `budget`
        runs out, and returns where it stopped. A registry that is far behind continues on the next run.

        Each span commits on its own, so a failed read raises without losing the spans before it.
        """
        assert self.feed is not None
        ready = self.feed.ready_until(team_id, now)
        deadline = time.monotonic() + budget.total_seconds()
        while True:
            reached = self.register(team_id=team_id, ready=ready)
            if reached >= ready or time.monotonic() >= deadline:
                return reached

    def register(self, *, team_id: int, ready: datetime) -> datetime:
        """Records what the feed saw in the next span after the cursor, up to `ready`, where the feed has
        finished, and returns where the registry stands.

        The feed's read runs outside the transaction, so no row lock waits on ClickHouse. The write
        then records only if the cursor has not moved, so two concurrent reads record one window once.
        A read that fails halves the cursor's span before it raises, so the next read asks for less.
        """
        assert self.feed is not None
        cursors = PlatformOccurrenceCursor.objects.for_team(team_id)
        cursor, _ = cursors.get_or_create(team_id=team_id, source_kind=self.source.value)
        since = cursor.registered_until or ready - self.feed.seed_lookback
        span = cursor.read_span or MAX_READ_SPAN
        until = min(ready, since + span)
        if until <= since:
            return since
        try:
            seen = list(self.feed.seen(team_id, since, until, MAX_IDENTITIES_PER_READ + 1))
        except Exception:
            if span > MIN_READ_SPAN:
                cursors.filter(id=cursor.id, read_span=cursor.read_span).update(read_span=max(span / 2, MIN_READ_SPAN))
            raise
        seen, until = _within_read_limit(seen, since, until)
        with transaction.atomic():
            locked = cursors.select_for_update().get(id=cursor.id)
            if locked.registered_until != cursor.registered_until:
                return locked.registered_until or since
            _record_sightings(self.source, team_id, seen)
            locked.registered_until = until
            locked.read_span = min(span * 2, MAX_READ_SPAN)
            locked.save(update_fields=["registered_until", "read_span"])
        return until


def _within_read_limit(
    seen: list[SeenIdentity], since: datetime, until: datetime
) -> tuple[list[SeenIdentity], datetime]:
    """The sightings one read records, and where that read stops, so a read never records more than its limit."""
    if len(seen) <= MAX_IDENTITIES_PER_READ:
        return seen, until
    seen.sort(key=lambda identity: identity.seen_at)
    cut = seen[MAX_IDENTITIES_PER_READ].seen_at
    if cut > since:
        return [identity for identity in seen if identity.seen_at < cut], cut
    # One instant holds more first sightings than a read. Record those the read returned and move
    # just past that instant, so later sightings are read again rather than skipped.
    return [identity for identity in seen if identity.seen_at == since], since + MIN_STEP


def registrar_targets() -> list[tuple[SourceKind, int]]:
    """Each source with a feed, with each project that has an enabled appearance alert on it."""
    if not _feeds:
        return []
    # The registrar serves every project, so it opts out of team scoping rather than running once per team.
    rows = (
        PlatformAlertConfiguration.objects.unscoped()
        .filter(alert_kind=PlatformAlertKind.APPEARANCE, enabled=True, source_kind__in=[s.value for s in _feeds])
        .values_list("source_kind", "team_id")
        .distinct()
        .order_by("source_kind", "team_id")
    )
    return [(SourceKind(source_kind), team_id) for source_kind, team_id in rows]


def _occurrence(row: PlatformOccurrence) -> Occurrence:
    back = row.reappeared_at is not None
    return Occurrence(
        identity_key=row.identity_key,
        kind=OccurrenceKind.REAPPEARED if back else OccurrenceKind.NEW,
        first_seen_at=row.first_seen_at,
        occurred_at=row.reappeared_at if row.reappeared_at is not None else row.first_seen_at,
        labels=dict(row.labels),
        detail=dict(row.detail),
    )


def _record_sightings(source: SourceKind, team_id: int, seen: Sequence[SeenIdentity]) -> None:
    """A feed's sightings as facts: an unknown identity is new, and a resolved one seen after its resolve is back."""
    earliest: dict[str, SeenIdentity] = {}
    latest: dict[str, datetime] = {}
    for identity in seen:
        key = bounded_grouping_key(identity.identity_key)
        if key not in earliest or identity.seen_at < earliest[key].seen_at:
            earliest[key] = identity
        last = identity.last_seen_at or identity.seen_at
        latest[key] = max(latest.get(key, last), last)
    if not earliest:
        return
    resolved = PlatformOccurrence.objects.for_team(team_id).filter(
        source_kind=source.value, identity_key__in=list(earliest), resolved_at__isnull=False
    )
    for key, resolved_at in resolved.values_list("identity_key", "resolved_at"):
        assert resolved_at is not None
        sighting = earliest[key]
        back_at = sighting.seen_at if sighting.seen_at > resolved_at else latest[key]
        if back_at > resolved_at:
            record(
                source,
                team_id=team_id,
                identity_key=sighting.identity_key,
                kind=OccurrenceKind.REAPPEARED,
                occurred_at=back_at,
                first_seen_at=sighting.seen_at,
                labels=sighting.labels,
                detail=sighting.detail,
            )
    _insert_new(
        source,
        team_id,
        [(key, identity.seen_at, identity.labels, identity.detail) for key, identity in earliest.items()],
    )


def record(
    source: SourceKind,
    *,
    team_id: int,
    identity_key: str,
    kind: OccurrenceKind,
    occurred_at: datetime,
    first_seen_at: datetime,
    labels: dict[str, str],
    detail: dict[str, Any],
) -> None:
    """Records one fact. Idempotent: a repeated fact, or an older one arriving late, changes nothing."""
    key = bounded_grouping_key(identity_key)
    with transaction.atomic():
        _bound_statements()
        if kind == OccurrenceKind.NEW:
            _insert_new(source, team_id, [(key, first_seen_at, labels, detail)])
            return
        _record_reappearance(source, team_id, key, occurred_at, first_seen_at, labels, detail)


def _bound_statements() -> None:
    """Ends a write that waits on a lock or runs long, so a caller's own deadline really stops it."""
    with connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = '{WRITE_LOCK_TIMEOUT_MS}ms'")
        cursor.execute(f"SET LOCAL statement_timeout = '{WRITE_STATEMENT_TIMEOUT_MS}ms'")


def _record_reappearance(
    source: SourceKind,
    team_id: int,
    key: str,
    occurred_at: datetime,
    first_seen_at: datetime,
    labels: dict[str, str],
    detail: dict[str, Any],
) -> None:
    rows = PlatformOccurrence.objects.for_team(team_id).filter(source_kind=source.value, identity_key=key)
    row = rows.select_for_update().first()
    if row is None:
        PlatformOccurrence.objects.for_team(team_id).create(
            team_id=team_id,
            source_kind=source.value,
            identity_key=key,
            first_seen_at=first_seen_at,
            reappeared_at=occurred_at,
            labels=_storable(labels),
            detail=_storable(detail),
        )
        return
    # Older than the latest return, or than a resolve since, so it is not news.
    if any(moment is not None and occurred_at <= moment for moment in (row.reappeared_at, row.resolved_at)):
        return
    row.reappeared_at = occurred_at
    row.resolved_at = None
    # What came back may differ from what was first seen, and filters and messages read the latest.
    row.labels = _storable(labels)
    row.detail = _storable(detail)
    row.recorded_at = timezone.now()
    row.save(update_fields=["reappeared_at", "resolved_at", "labels", "detail", "recorded_at"])


def _insert_new(
    source: SourceKind, team_id: int, facts: Sequence[tuple[str, datetime, dict[str, str], dict[str, Any]]]
) -> None:
    # A conflict is an identity the registry already knows, which is not new.
    PlatformOccurrence.objects.for_team(team_id).bulk_create(
        [
            PlatformOccurrence(
                team_id=team_id,
                source_kind=source.value,
                identity_key=key,
                first_seen_at=first_seen_at,
                labels=_storable(labels),
                detail=_storable(detail),
            )
            for key, first_seen_at, labels, detail in facts
        ],
        ignore_conflicts=True,
        batch_size=500,
    )


def _storable(value: Any) -> Any:
    """`value` with every string JSONB can store, because one bad string rolls back the whole read."""
    if isinstance(value, str):
        return UNSTORABLE.sub("\ufffd", value)
    if isinstance(value, dict):
        return {_storable(key): _storable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_storable(item) for item in value]
    return value


def resolve(source: SourceKind, *, team_id: int, identity_key: str, at: datetime) -> bool:
    """Marks an identity resolved, so its next sighting announces it again. False when the registry does not know it."""
    return bool(
        PlatformOccurrence.objects.for_team(team_id)
        .filter(source_kind=source.value, identity_key=bounded_grouping_key(identity_key))
        .update(resolved_at=at)
    )
