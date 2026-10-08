"""A committed tombstone justifies erasing only that person's distinct IDs. Erasing a whole team waits
for positive team deletion evidence."""

from collections import defaultdict
from collections.abc import Callable, Collection, Sequence

import structlog

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dataclasses import frozen
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person.tombstone_log import (
    PendingPersonTombstone,
    TombstoneConsumer,
    ack_person_tombstones_for_consumer,
    list_pending_person_tombstones,
    list_person_tombstone_distinct_ids,
)
from posthog.models.team import Team

from products.customer_analytics.backend.logic.membership_deletion import (
    DISTINCT_ID_CHUNK_SIZE,
    actively_owned,
    delete_distinct_ids,
    delete_teams,
    stored_team_ids,
    team_has_membership,
)

logger = structlog.get_logger(__name__)

CONSUMER = TombstoneConsumer.CUSTOMER_ANALYTICS_MEMBERSHIP
LOG_PAGE_SIZE = 100
IDENTITY_PAGE_SIZE = 250
ACK_BATCH_SIZE = 1000
TEAM_PAGE_SIZE = 250


@frozen
class TombstoneResume:
    """Where an interrupted generation continues. Every distinct ID up to ``after_id`` is erased and verified."""

    team_id: int
    log_id: int
    after_id: int


@frozen
class TombstonePageOutcome:
    acknowledged: int
    failed_team_ids: tuple[int, ...]
    next_cursor: int | None
    # Set when the budget ran out inside a generation.
    resume: TombstoneResume | None = None


@frozen
class TeamScanOutcome:
    deleted_teams: int
    unconfirmed_teams: int
    failed_teams: int
    next_cursor: int | None


class MembershipDeletionInterrupted(Exception):
    def __init__(self, resume: TombstoneResume | None, acknowledged: int = 0) -> None:
        super().__init__("Membership deletion stopped at its budget")
        self.resume = resume
        self.acknowledged = acknowledged


def confirmed_deleted_teams(team_ids: Sequence[int]) -> set[int]:
    """A team absent without an AsyncDeletion(Team) entry stays unconfirmed, because absence alone is not evidence."""
    absent = set(team_ids) - set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
    if not absent:
        return set()
    return set(
        AsyncDeletion.objects.filter(deletion_type=DeletionType.Team, team_id__in=absent).values_list(
            "team_id", flat=True
        )
    )


class _TeamErasure:
    """A generation is acknowledged only after the chunk that holds its last distinct ID is verified.
    An interrupted generation resumes after its last verified distinct ID, so a long generation
    completes across several budgets. At most one chunk of work repeats after an interruption.
    """

    def __init__(
        self,
        cluster: ClickhouseCluster,
        team_id: int,
        should_stop: Callable[[], bool],
        on_progress: Callable[[TombstoneResume], None],
    ) -> None:
        self.cluster = cluster
        self.team_id = team_id
        self.should_stop = should_stop
        self.on_progress = on_progress
        self.acknowledged = 0
        self._distinct_ids: set[str] = set()
        self._complete: list[int] = []
        self._current: TombstoneResume | None = None

    def acknowledge(self, log_ids: Sequence[int]) -> None:
        for start in range(0, len(log_ids), ACK_BATCH_SIZE):
            self.acknowledged += ack_person_tombstones_for_consumer(
                CONSUMER, self.team_id, list(log_ids[start : start + ACK_BATCH_SIZE])
            )

    def add(self, entry: PendingPersonTombstone, *, after_id: int = 0) -> None:
        self._current = TombstoneResume(team_id=self.team_id, log_id=entry.log_id, after_id=after_id)
        while True:
            if self.should_stop():
                raise MembershipDeletionInterrupted(self._current)
            page = list_person_tombstone_distinct_ids(
                self.team_id, entry.log_id, after_id=after_id, limit=IDENTITY_PAGE_SIZE
            )
            for identity in page.identities:
                self._distinct_ids.add(identity.distinct_id)
                if len(self._distinct_ids) >= DISTINCT_ID_CHUNK_SIZE:
                    self.flush()
                    self._current = TombstoneResume(team_id=self.team_id, log_id=entry.log_id, after_id=identity.id)
                    self.on_progress(self._current)
            if page.next_cursor is None:
                break
            after_id = page.next_cursor
        self._current = None
        self._complete.append(entry.log_id)

    def flush(self) -> None:
        if self._distinct_ids:
            distinct_ids = sorted(self._distinct_ids)
            owned = actively_owned(self.team_id, distinct_ids)
            # A live owner holds the distinct ID again, so its membership rows are no longer the deleted person's.
            delete_distinct_ids(
                self.cluster, self.team_id, [distinct_id for distinct_id in distinct_ids if distinct_id not in owned]
            )
            self._distinct_ids.clear()
        complete, self._complete = self._complete, []
        self.acknowledge(complete)


def _erase_team(
    cluster: ClickhouseCluster,
    team_id: int,
    entries: Sequence[PendingPersonTombstone],
    *,
    deleted: bool,
    should_stop: Callable[[], bool],
    on_progress: Callable[[TombstoneResume], None],
    resume_after_id: int = 0,
) -> int:
    erasure = _TeamErasure(cluster, team_id, should_stop, on_progress)
    try:
        if deleted:
            delete_teams(cluster, [team_id])
            erasure.acknowledge([entry.log_id for entry in entries])
        elif not team_has_membership(cluster, team_id):
            erasure.acknowledge([entry.log_id for entry in entries])
        else:
            for index, entry in enumerate(entries):
                erasure.add(entry, after_id=resume_after_id if index == 0 else 0)
            erasure.flush()
    except MembershipDeletionInterrupted as error:
        raise MembershipDeletionInterrupted(error.resume, acknowledged=erasure.acknowledged) from None
    return erasure.acknowledged


def _pending_entry(resume: TombstoneResume) -> PendingPersonTombstone | None:
    page = list_pending_person_tombstones(CONSUMER, after=resume.log_id - 1, limit=1, team_id=resume.team_id)
    if page.entries and page.entries[0].log_id == resume.log_id:
        return page.entries[0]
    return None


def process_tombstone_page(
    cluster: ClickhouseCluster,
    *,
    after: int | None,
    resume: TombstoneResume | None = None,
    skip_team_ids: Collection[int] = (),
    should_stop: Callable[[], bool] = lambda: False,
    on_progress: Callable[[TombstoneResume], None] = lambda _resume: None,
) -> TombstonePageOutcome:
    """On a budget stop, ``next_cursor`` repeats ``after``, or 0 for the first page, because acknowledged
    entries leave the pending list. None only ever means the end of the log."""
    acknowledged = 0
    failed_team_ids: list[int] = []

    def interrupted(error: MembershipDeletionInterrupted) -> TombstonePageOutcome:
        return TombstonePageOutcome(
            acknowledged=acknowledged + error.acknowledged,
            failed_team_ids=tuple(failed_team_ids),
            next_cursor=after if after is not None else 0,
            resume=error.resume,
        )

    if resume is not None and (entry := _pending_entry(resume)) is not None:
        try:
            acknowledged += _erase_team(
                cluster,
                resume.team_id,
                [entry],
                deleted=resume.team_id in confirmed_deleted_teams([resume.team_id]),
                should_stop=should_stop,
                on_progress=on_progress,
                resume_after_id=resume.after_id,
            )
        except MembershipDeletionInterrupted as error:
            return interrupted(error)
        except Exception as error:
            failed_team_ids.append(resume.team_id)
            logger.warning("membership_deletion_team_failed", team_id=resume.team_id, error_type=type(error).__name__)

    page = list_pending_person_tombstones(CONSUMER, after=after, limit=LOG_PAGE_SIZE)
    by_team: dict[int, list[PendingPersonTombstone]] = defaultdict(list)
    for entry in page.entries:
        if entry.team_id not in skip_team_ids:
            by_team[entry.team_id].append(entry)
    deleted_teams = confirmed_deleted_teams(list(by_team))

    for team_id, entries in by_team.items():
        try:
            if should_stop():
                raise MembershipDeletionInterrupted(None)
            acknowledged += _erase_team(
                cluster,
                team_id,
                entries,
                deleted=team_id in deleted_teams,
                should_stop=should_stop,
                on_progress=on_progress,
            )
        except MembershipDeletionInterrupted as error:
            return interrupted(error)
        except Exception as error:
            if team_id not in failed_team_ids:
                failed_team_ids.append(team_id)
            # Error messages can echo distinct IDs, so only the type leaves this function.
            logger.warning("membership_deletion_team_failed", team_id=team_id, error_type=type(error).__name__)
    return TombstonePageOutcome(
        acknowledged=acknowledged, failed_team_ids=tuple(failed_team_ids), next_cursor=page.next_cursor
    )


def reconcile_deleted_teams(
    cluster: ClickhouseCluster, *, after: int, should_stop: Callable[[], bool] = lambda: False
) -> TeamScanOutcome:
    team_ids, next_cursor = stored_team_ids(cluster, after=after, limit=TEAM_PAGE_SIZE)
    confirmed = confirmed_deleted_teams(team_ids)
    live = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
    unconfirmed = [team_id for team_id in team_ids if team_id not in live and team_id not in confirmed]
    for team_id in unconfirmed:
        logger.warning("membership_team_deletion_unconfirmed", team_id=team_id)

    deleted_teams = failed_teams = 0
    stopped = False
    for team_id in sorted(confirmed):
        if should_stop():
            stopped = True
            break
        try:
            delete_teams(cluster, [team_id])
            deleted_teams += 1
        except Exception as error:
            failed_teams += 1
            logger.warning("membership_team_deletion_failed", team_id=team_id, error_type=type(error).__name__)
    return TeamScanOutcome(
        deleted_teams=deleted_teams,
        unconfirmed_teams=len(unconfirmed),
        failed_teams=failed_teams,
        # A stopped scan reads the same page again, because its remaining teams were not reached.
        next_cursor=after if stopped else next_cursor,
    )
