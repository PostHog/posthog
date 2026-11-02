from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Literal

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from posthog.cache_utils import cache_for
from posthog.models.team.team import Team

from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)

# Matches the Rust range-span cap in rust/common/types/src/cohort.rs.
_MAX_RANGE_SPAN = 100_000

GrantLevel = Literal[RealtimeCohortLevel.PROCESSING, RealtimeCohortLevel.SERVING]

_backfill_triggers_suppressed: ContextVar[bool] = ContextVar("cohort_backfill_triggers_suppressed", default=False)


def _matches_every_team(raw_allowlist: str) -> bool:
    raw_allowlist = raw_allowlist.strip()
    return raw_allowlist == "" or raw_allowlist.lower() == "all" or raw_allowlist == "*"


def _team_in_allowlist(raw_allowlist: str, team_id: int) -> bool:
    """Whether ``team_id`` matches a team-allowlist setting.

    Mirrors the Rust ``TeamAllowlist`` grammar (``rust/common/types/src/cohort.rs``) that parses
    ``REALTIME_COHORT_TEAM_ALLOWLIST`` — keep the two in sync so Django's edit-time readiness
    invalidation covers exactly the teams Rust maintains realtime membership for.

    Grammar: empty / ``all`` / ``*`` match every team; ``none`` matches none; otherwise a comma list
    of signed integer ids and inclusive ``start:end`` ranges (each capped at ``_MAX_RANGE_SPAN``).
    Malformed tokens are ignored — the Rust side rejects the whole value at startup.
    """
    raw_allowlist = raw_allowlist.strip()
    if _matches_every_team(raw_allowlist):
        return True
    if raw_allowlist.lower() == "none":
        return False

    for part in (segment.strip() for segment in raw_allowlist.split(",")):
        if not part:
            continue
        start_raw, is_range, end_raw = part.partition(":")
        try:
            if is_range:
                start, end = int(start_raw.strip()), int(end_raw.strip())
            else:
                start = end = int(part)
        except ValueError:
            continue
        if start <= end <= start + _MAX_RANGE_SPAN - 1 and start <= team_id <= end:
            return True
    return False


def realtime_allowlist_matches_every_team() -> bool:
    """Whether the realtime allowlist is one of the match-everything values.

    Lets a caller skip enumerating every team to rediscover that the allowlist covers all of them.
    """
    return _matches_every_team(settings.REALTIME_COHORT_TEAM_ALLOWLIST)


def realtime_allowlist_matches(team_id: int) -> bool:
    """Whether ``REALTIME_COHORT_TEAM_ALLOWLIST`` names ``team_id``, whatever its access row says."""
    return _team_in_allowlist(settings.REALTIME_COHORT_TEAM_ALLOWLIST, team_id)


# Cohort saves and every row of the cohort list read this, so it is cached per process rather than
# queried per call. `cache_for` is off under tests, so a test reads the rows it wrote. It keeps `off`
# rows, because `team_honors_readiness_stamps` must tell a revoked team from one that never had a row.
@cache_for(timedelta(seconds=30))
def _access_rows() -> dict[int, RealtimeCohortTeamAccess]:
    return {row.team_id: row for row in RealtimeCohortTeamAccess.objects.all()}


def _access_row(team_id: int, *, fresh: bool) -> RealtimeCohortTeamAccess | None:
    if fresh:
        return RealtimeCohortTeamAccess.objects.filter(team_id=team_id).first()
    return _access_rows().get(team_id)


def realtime_level(team_id: int, *, fresh: bool = False) -> RealtimeCohortLevel:
    """The team's effective level: the union of the env allowlist and the team's access row.

    The env allowlist grants `serving`, because before the levels existed it gated the screens users
    see as well as the pipeline. The row comes from a per-process snapshot up to 30 seconds old,
    unless ``fresh`` reads it as it is now.
    """
    if realtime_allowlist_matches(team_id):
        return RealtimeCohortLevel.SERVING
    row = _access_row(team_id, fresh=fresh)
    return RealtimeCohortLevel(row.level) if row is not None else RealtimeCohortLevel.OFF


def is_processing_team(team_id: int, *, fresh: bool = False) -> bool:
    """Whether the realtime-cohort pipeline maintains membership for ``team_id``.

    The run creators and the cohort save path pass ``fresh``. A creator reading the snapshot could
    create a run after a revoke, and an edit reading it right after a grant could skip the supersede
    of the team's runs, or the trigger of a new one.
    """
    return realtime_level(team_id, fresh=fresh) != RealtimeCohortLevel.OFF


def is_serving_team(team_id: int) -> bool:
    """Whether ``team_id``'s users see realtime cohort state: readiness, and audiences that wait on it."""
    return realtime_level(team_id) == RealtimeCohortLevel.SERVING


def team_honors_readiness_stamps(team_id: int) -> bool:
    """Whether ``team_id``'s backfill stamps can make its cohorts usable in flags and workflows.

    Not while the team's row is below `serving`. At `processing` its users must not see realtime
    cohorts, and after a revoke no edit clears the stamps. A team with no row keeps the stamps it had
    before the levels existed.
    """
    if realtime_allowlist_matches(team_id):
        return True
    row = _access_rows().get(team_id)
    return row is None or row.level == RealtimeCohortLevel.SERVING


def is_cohort_backfill_trigger_team(team_id: int) -> bool:
    """Whether saving a cohort in ``team_id`` should enqueue backfill runs for it.

    Reads the row as it is now, like the edit-time supersede. Right after a grant, an edit supersedes
    the cohort's runs and clears its stamps, and a stale snapshot would then enqueue no new run. The
    edit has already stored the new shape hashes, so no later save enqueues one either.
    """
    if _backfill_triggers_suppressed.get():
        return False
    # No Rust service parses this setting, so it can fail closed on empty where the realtime
    # allowlist cannot: a set-but-empty value means no teams, not every team.
    trigger_allowlist = settings.COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST
    if trigger_allowlist.strip() and _team_in_allowlist(trigger_allowlist, team_id):
        return True
    return (
        RealtimeCohortTeamAccess.objects.filter(team_id=team_id, save_triggers_backfill=True)
        .exclude(level=RealtimeCohortLevel.OFF)
        .exists()
    )


@contextmanager
def backfill_triggers_suppressed() -> Iterator[None]:
    """Cohort saves inside enqueue no backfill run on any team.

    Setting `COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST=none` does not do this, because a granted team's
    `save_triggers_backfill` still enqueues.
    """
    token = _backfill_triggers_suppressed.set(True)
    try:
        yield
    finally:
        _backfill_triggers_suppressed.reset(token)


def grant_realtime_cohort_access(
    team_ids: Iterable[int],
    *,
    level: GrantLevel,
    purpose: RealtimeCohortAccessPurpose,
    save_triggers_backfill: bool,
) -> list[int]:
    """Write a row at ``level`` for every team, or for none of them. Returns the team ids.

    A revoked team is refused, because nothing purges the pipeline state a revoke leaves behind,
    and a re-grant would build on that stale state.
    """
    requested = sorted(set(team_ids))
    with transaction.atomic():
        parent_by_team = dict(Team.objects.filter(id__in=requested).values_list("id", "parent_team_id"))
        _refuse("No team with id", [team_id for team_id in requested if team_id not in parent_by_team])
        # Cohorts live on the root team (`RootTeamMixin`), so a row on a child environment covers nothing.
        _refuse("Not a root team", [team_id for team_id, parent_id in parent_by_team.items() if parent_id is not None])
        # The env list makes a team `serving` whatever its row says, and `revoke` refuses a listed
        # team. So a row here would change nothing, and would block `revoke --purpose` for every team.
        _refuse(
            "On REALTIME_COHORT_TEAM_ALLOWLIST",
            [team_id for team_id in requested if realtime_allowlist_matches(team_id)],
        )
        rows = {
            row.team_id: row
            for row in RealtimeCohortTeamAccess.objects.select_for_update().filter(team_id__in=requested)
        }
        _refuse(
            "Revoked, and its pipeline state was never purged",
            [team_id for team_id, row in rows.items() if row.level == RealtimeCohortLevel.OFF],
        )
        # `revoke --purpose` selects by it, so a re-grant that relabels a pilot as a load test would
        # put the pilot under the load test's stop command.
        _refuse(
            f"Granted for another purpose than {purpose.value}",
            [team_id for team_id, row in rows.items() if row.purpose != purpose],
        )

        now = timezone.now()
        for team_id in requested:
            row = rows.get(team_id) or RealtimeCohortTeamAccess(team_id=team_id, processing_since=now)
            row.level = level
            row.purpose = purpose
            row.save_triggers_backfill = save_triggers_backfill
            # `select_for_update` cannot lock a row that does not exist yet. A plain insert makes a
            # concurrent first grant of the team fail on the primary key, instead of overwriting the
            # purpose the other grant wrote.
            row.save(force_insert=team_id not in rows)
    return requested


def revoke_realtime_cohort_access(rows: QuerySet[RealtimeCohortTeamAccess]) -> list[int]:
    """Set every granted row in ``rows`` to `off`, or none of them. Returns the revoked team ids.

    A team on `REALTIME_COHORT_TEAM_ALLOWLIST` is refused. The env list keeps it processing whatever
    the row says, so an `off` row would tell every reader of the table the opposite of the truth.
    """
    with transaction.atomic():
        revoked = sorted(
            rows.exclude(level=RealtimeCohortLevel.OFF).select_for_update().values_list("team_id", flat=True)
        )
        _refuse(
            "On REALTIME_COHORT_TEAM_ALLOWLIST", [team_id for team_id in revoked if realtime_allowlist_matches(team_id)]
        )
        now = timezone.now()
        RealtimeCohortTeamAccess.objects.filter(team_id__in=revoked).update(
            level=RealtimeCohortLevel.OFF, off_since=now, changed_at=now
        )
    return revoked


def _refuse(reason: str, team_ids: list[int]) -> None:
    if team_ids:
        raise ValueError(f"{reason}: {', '.join(str(team_id) for team_id in sorted(team_ids))}")
