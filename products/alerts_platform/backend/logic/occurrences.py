"""Occurrence stores: where appearance alerts read which identities are new.

A source with detection of its own registers a store that reads its own tables. A source without
one registers a feed, and the platform's registry becomes its store. The registry records every
identity the feed reports, whatever any alert filters on, so what "new" means does not depend on
which alerts exist.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final

from django.db import transaction

from products.alerts_platform.backend.facade.contracts import (
    Occurrence,
    OccurrenceFeed,
    OccurrenceKind,
    OccurrenceStore,
    OccurrenceWindow,
    SeenIdentity,
    SourceKind,
)
from products.alerts_platform.backend.facade.grouping import bounded_grouping_key
from products.alerts_platform.backend.models import PlatformOccurrence, PlatformOccurrenceCursor

# One read of a feed records at most this many identities. A window with more is read again from
# where this one stopped, so a burst takes several checks rather than one oversized transaction.
MAX_IDENTITIES_PER_READ: Final = 5000
# A registry far behind, such as one seeding from the feed's lookback, catches up one slice per
# read, so each read scans its own slice rather than everything since the cursor.
MAX_READ_SPAN: Final = timedelta(days=1)

_stores: dict[SourceKind, OccurrenceStore] = {}


def register_store(source: SourceKind, store: OccurrenceStore) -> None:
    registered = _stores.get(source)
    if registered is not None and registered is not store:
        raise RuntimeError(f"A different occurrence store is already registered for {source} alerts.")
    _stores[source] = store


def register_feed(source: SourceKind, feed: OccurrenceFeed) -> None:
    registered = _stores.get(source)
    if isinstance(registered, RegistryStore) and registered.feed is feed:
        return
    register_store(source, RegistryStore(source, feed))


def store_for(source: SourceKind) -> OccurrenceStore | None:
    return _stores.get(source)


class RegistryStore:
    """The default store: the platform's per-project registry of one source's identities."""

    def __init__(self, source: SourceKind, feed: OccurrenceFeed) -> None:
        self.source = source
        self.feed = feed

    def ready_until(self, *, team_id: int, now: datetime) -> datetime:
        """Records what the feed saw since the last read first, so the answer covers it."""
        return self.register(team_id=team_id, now=now)

    def appeared(self, *, team_id: int, since: datetime, until: datetime, limit: int) -> OccurrenceWindow:
        rows = PlatformOccurrence.objects.for_team(team_id).filter(source_kind=self.source.value)
        new = rows.filter(first_seen_at__gte=since, first_seen_at__lt=until).order_by("first_seen_at")[: limit + 1]
        back = rows.filter(reappeared_at__gte=since, reappeared_at__lt=until).order_by("reappeared_at")[: limit + 1]
        occurrences = sorted(
            [_occurrence(row, OccurrenceKind.NEW) for row in new]
            + [_occurrence(row, OccurrenceKind.REAPPEARED) for row in back],
            key=lambda occurrence: occurrence.occurred_at,
        )
        return OccurrenceWindow(occurrences=tuple(occurrences[:limit]), truncated=len(occurrences) > limit)

    def register(self, *, team_id: int, now: datetime) -> datetime:
        """Records what the feed saw since the last read, and returns how far the registry is complete.

        The feed's read runs outside the transaction, so no row lock waits on ClickHouse. The write
        then records only if the cursor has not moved, so two concurrent reads record one window once.
        """
        cursors = PlatformOccurrenceCursor.objects.for_team(team_id)
        cursor, _ = cursors.get_or_create(team_id=team_id, source_kind=self.source.value)
        ready = self.feed.ready_until(team_id, now)
        since = cursor.registered_until or ready - self.feed.seed_lookback
        until = min(ready, since + MAX_READ_SPAN)
        if until <= since:
            return since
        seen = list(self.feed.seen(team_id, since, until, MAX_IDENTITIES_PER_READ + 1))
        if len(seen) > MAX_IDENTITIES_PER_READ:
            seen.sort(key=lambda identity: identity.seen_at)
            cut = seen[MAX_IDENTITIES_PER_READ].seen_at
            # Stop before the first sighting left out, so the next read starts on it. When one
            # instant holds more sightings than a read, record what this read returned and move on,
            # which loses some of them but never stalls on that instant.
            if cut > since:
                until = cut
                seen = [identity for identity in seen if identity.seen_at < cut]
        with transaction.atomic():
            locked = cursors.select_for_update().get(id=cursor.id)
            if locked.registered_until != cursor.registered_until:
                return locked.registered_until or since
            _record(self.source, team_id, seen)
            locked.registered_until = until
            locked.save(update_fields=["registered_until"])
        return until


def _occurrence(row: PlatformOccurrence, kind: OccurrenceKind) -> Occurrence:
    occurred_at = row.first_seen_at if kind == OccurrenceKind.NEW else row.reappeared_at
    assert occurred_at is not None
    return Occurrence(
        identity_key=row.identity_key,
        kind=kind,
        first_seen_at=row.first_seen_at,
        occurred_at=occurred_at,
        labels=dict(row.labels),
        detail=dict(row.detail),
    )


def _record(source: SourceKind, team_id: int, seen: Sequence[SeenIdentity]) -> None:
    earliest: dict[str, SeenIdentity] = {}
    for identity in seen:
        key = bounded_grouping_key(identity.identity_key)
        if key not in earliest or identity.seen_at < earliest[key].seen_at:
            earliest[key] = identity
    if not earliest:
        return
    rows = PlatformOccurrence.objects.for_team(team_id).filter(source_kind=source.value)
    # Only a resolved identity changes on a sighting, so the other known ones are left untouched.
    for row in rows.select_for_update().filter(identity_key__in=list(earliest), resolved_at__isnull=False):
        sighting = earliest[row.identity_key].seen_at
        if row.resolved_at is not None and sighting > row.resolved_at:
            row.resolved_at = None
            row.reappeared_at = sighting
            row.save(update_fields=["resolved_at", "reappeared_at"])
    # A conflict is an identity the registry already knows, which is not new.
    PlatformOccurrence.objects.for_team(team_id).bulk_create(
        [
            PlatformOccurrence(
                team_id=team_id,
                source_kind=source.value,
                identity_key=key,
                first_seen_at=identity.seen_at,
                labels=identity.labels,
                detail=identity.detail,
            )
            for key, identity in earliest.items()
        ],
        ignore_conflicts=True,
        batch_size=500,
    )


def resolve(source: SourceKind, *, team_id: int, identity_key: str, at: datetime) -> bool:
    """Marks an identity resolved, so its next sighting announces it again. False when the registry does not know it."""
    return bool(
        PlatformOccurrence.objects.for_team(team_id)
        .filter(source_kind=source.value, identity_key=identity_key)
        .update(resolved_at=at)
    )
