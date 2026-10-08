"""The shared person tombstone log: one immutable entry per deletion generation.

An entry retires only after every consumer acks it, so one consumer's outage never loses another
consumer's work, and Postgres cleanup of the person rows never removes it.
"""

from collections.abc import Sequence
from dataclasses import field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.proto import (
    AckPersonTombstoneLogRequest,
    ListPendingPersonTombstonesRequest,
    ListPersonTombstoneDistinctIdsRequest,
    PersonTombstoneConsumer,
    RetirePersonTombstoneLogRequest,
)

# The replica's caps; keep in sync with personhog-replica's service limits.
MAX_PAGE_SIZE = 1000
MAX_ACK_SIZE = 1000
MAX_RETIRE_ROWS = 10_000


class TombstoneConsumer(StrEnum):
    PUBLICATION = "publication"
    CUSTOMER_ANALYTICS_MEMBERSHIP = "customer_analytics_membership"


_PROTO_CONSUMERS: dict[TombstoneConsumer, PersonTombstoneConsumer] = {
    TombstoneConsumer.PUBLICATION: PersonTombstoneConsumer.PERSON_TOMBSTONE_CONSUMER_PUBLICATION,
    TombstoneConsumer.CUSTOMER_ANALYTICS_MEMBERSHIP: PersonTombstoneConsumer.PERSON_TOMBSTONE_CONSUMER_CUSTOMER_ANALYTICS_MEMBERSHIP,
}


@frozen
class PendingPersonTombstone:
    log_id: int
    team_id: int
    person_uuid: UUID
    person_version: int
    tombstoned_at: datetime


@frozen
class PendingTombstonePage:
    entries: tuple[PendingPersonTombstone, ...]
    next_cursor: int | None


@frozen
class TombstonedIdentity:
    id: int
    distinct_id: str = field(repr=False)
    version: int


@frozen
class TombstoneRetirement:
    retired: int
    distinct_ids_deleted: int
    has_more: bool


@frozen
class TombstoneIdentityPage:
    identities: tuple[TombstonedIdentity, ...]
    next_cursor: int | None


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")


def list_pending_person_tombstones(
    consumer: TombstoneConsumer,
    *,
    after: int | None = None,
    limit: int = 100,
    min_age: timedelta = timedelta(0),
    team_id: int | None = None,
) -> PendingTombstonePage:
    _validate_limit(limit)
    if min_age < timedelta(0):
        raise ValueError("min_age must not be negative")
    request = ListPendingPersonTombstonesRequest(
        consumer=_PROTO_CONSUMERS[TombstoneConsumer(consumer)],
        after_log_id=after or 0,
        limit=limit,
        min_age_ms=int(min_age.total_seconds() * 1000),
    )
    if team_id is not None:
        request.team_id = team_id

    def personhog_fn() -> PendingTombstonePage:
        response = require_personhog_client().list_pending_person_tombstones(request)
        entries = tuple(
            PendingPersonTombstone(
                log_id=int(entry.log_id),
                team_id=int(entry.team_id),
                person_uuid=UUID(entry.person_uuid),
                person_version=int(entry.person_version),
                tombstoned_at=datetime.fromtimestamp(entry.tombstoned_at / 1000, tz=UTC),
            )
            for entry in response.entries
        )
        return PendingTombstonePage(
            entries=entries,
            next_cursor=entries[-1].log_id if response.has_more and entries else None,
        )

    return personhog_call("list_pending_person_tombstones", personhog_fn)


def list_person_tombstone_distinct_ids(
    team_id: int, log_id: int, *, after_id: int = 0, limit: int = 250
) -> TombstoneIdentityPage:
    _validate_limit(limit)
    if after_id < 0:
        raise ValueError("after_id must not be negative")
    request = ListPersonTombstoneDistinctIdsRequest(team_id=team_id, log_id=log_id, after_id=after_id, limit=limit)

    def personhog_fn() -> TombstoneIdentityPage:
        response = require_personhog_client().list_person_tombstone_distinct_ids(request)
        identities = tuple(
            TombstonedIdentity(id=int(row.id), distinct_id=row.distinct_id, version=int(row.version))
            for row in response.distinct_ids
        )
        return TombstoneIdentityPage(
            identities=identities,
            next_cursor=identities[-1].id if response.has_more and identities else None,
        )

    return personhog_call("list_person_tombstone_distinct_ids", personhog_fn)


def ack_person_tombstones_for_consumer(consumer: TombstoneConsumer, team_id: int, log_ids: Sequence[int]) -> int:
    """Ack an entry only after every one of its distinct ids is handled. Another team's log ids are ignored."""
    proto_consumer = _PROTO_CONSUMERS[TombstoneConsumer(consumer)]
    unique = sorted(set(log_ids))

    def personhog_fn() -> int:
        acked = 0
        client = require_personhog_client()
        for start in range(0, len(unique), MAX_ACK_SIZE):
            response = client.ack_person_tombstone_log(
                AckPersonTombstoneLogRequest(
                    team_id=team_id, consumer=proto_consumer, log_ids=unique[start : start + MAX_ACK_SIZE]
                )
            )
            acked += int(response.acked_count)
        return acked

    if not unique:
        return 0
    return personhog_call("ack_person_tombstones_for_consumer", personhog_fn)


def retire_acked_person_tombstones(*, max_rows: int = 5000) -> TombstoneRetirement:
    """An entry goes only after all of its distinct ids, so call again while ``has_more`` is true."""
    if not 1 <= max_rows <= MAX_RETIRE_ROWS:
        raise ValueError(f"max_rows must be between 1 and {MAX_RETIRE_ROWS}")

    def personhog_fn() -> TombstoneRetirement:
        response = require_personhog_client().retire_person_tombstone_log(
            RetirePersonTombstoneLogRequest(max_rows=max_rows)
        )
        return TombstoneRetirement(
            retired=int(response.retired_count),
            distinct_ids_deleted=int(response.distinct_ids_deleted),
            has_more=response.has_more,
        )

    return personhog_call("retire_acked_person_tombstones", personhog_fn)
