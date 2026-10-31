"""Take a distinct id off a person. `detach` tombstones strays from a scan report; `split_distinct_ids` moves
distinct ids off a live person onto persons of their own."""

from __future__ import annotations

import time
import shlex
import tempfile
from collections.abc import Callable, Sequence
from functools import partial
from typing import TYPE_CHECKING, Any
from uuid import UUID

from posthog.kafka_client.routing import flush_all_producers
from posthog.models.person.util import _batched_get_distinct_ids_for_persons, get_distinct_id_rows, get_persons_by_uuids
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.proto import (
    DISTINCT_ID_WRITE_ACTION_TOMBSTONE,
    DISTINCT_ID_WRITE_OUTCOME_APPLIED,
    DISTINCT_ID_WRITE_OUTCOME_PERSON_NOT_LIVE,
    DISTINCT_ID_WRITE_OUTCOME_UNCHANGED,
    DistinctIdRow,
    DistinctIdWrite,
    WriteDistinctIdsRequest,
)

from . import cleanup_queue, lookups, observe, repairs
from .flavors import PgMapping, classify_mapping

if TYPE_CHECKING:
    from .verbs import VerbContext

# How long the split waits for its own ClickHouse messages to go out before it republishes and checks them.
_SPLIT_FLUSH_SECONDS = 60.0

# A republish command for more distinct ids than this reads them from a file, so the command stays short.
_INLINE_DISTINCT_IDS = 10

# The pause before the resend tries unconfirmed ids again, for a replica that had not caught up with the split.
_RESEND_RETRY_SECONDS = 1.0

_sleep = time.sleep


class SplitError(Exception):
    pass


def detach(rows: list[dict[str, Any]], context: VerbContext) -> None:
    """Tombstone strays in Postgres: distinct ids live there on a tombstoned person.

    It writes nothing to ClickHouse. The cleanup drain hard-deletes a person's Postgres rows once its distinct ids are
    tombstoned, so a ClickHouse tombstone that outlived that delete would hide a later re-use of the distinct id. A
    stray is tombstoned only when the classifier, re-run on fresh ClickHouse reads just before the write, still names
    it `detach`: ClickHouse holds nothing for it, or the deletion sweep will remove its rows together with the owner
    before the drain runs. Any other stray is skipped under the sub-flavor it now has.

    The tombstone lands above every version ClickHouse holds for the distinct id, so if the distinct id is captured
    again, ingestion revives the row one version higher and ClickHouse shows the revival.
    """
    for batch in lookups._chunks(rows, repairs._WRITE_BATCH_SIZE):
        _detach_batch(list(batch), context)


def _detach_batch(rows: list[dict[str, Any]], context: VerbContext) -> None:
    team_id = context.team_id
    by_key = {row["key"]: row for row in rows}
    reported = {row["key"]: PgMapping(**row["evidence"]["pg"]) for row in rows}
    ch = observe.ch_mapping_states(team_id, list(by_key))
    owner_ch = observe.owner_ch_states(team_id, reported, ch)
    writes: list[DistinctIdWrite] = []
    for key, row in by_key.items():
        pg, state = reported[key], ch.get(key)
        verdict = classify_mapping(pg, state, owner_ch=owner_ch.get(key))
        if verdict.verb != "detach":
            context.action(row, f"skipped_{verdict.sub_flavor or verdict.flavor}")
            continue
        writes.append(
            DistinctIdWrite(
                distinct_id=key,
                action=DISTINCT_ID_WRITE_ACTION_TOMBSTONE,
                person_uuid=pg.person_uuid,
                min_version=max(pg.version + 1, (state.max_version + 1) if state else 0),
                expected_version=pg.version,
            )
        )
    if not writes:
        return
    if not context.apply:
        current = {
            r.distinct_id: r for r in get_distinct_id_rows(team_id, [w.distinct_id for w in writes], strong=True)
        }
        for write in writes:
            context.action(
                by_key[write.distinct_id],
                _predicted_outcome(current.get(write.distinct_id), write),
                target_version=write.min_version,
            )
        return

    context.pacer.before_write()
    response = repairs._retry_transient(
        partial(
            personhog_call,
            "person_consistency_detach",
            partial(
                require_personhog_client().write_distinct_ids,
                WriteDistinctIdsRequest(team_id=team_id, writes=writes),
            ),
        ),
        what="detach",
        log=context.log,
    )
    detached_owners: set[int] = set()
    for result in response.results:
        row = by_key[result.distinct_id]
        if result.outcome in (DISTINCT_ID_WRITE_OUTCOME_APPLIED, DISTINCT_ID_WRITE_OUTCOME_UNCHANGED):
            detached_owners.add(reported[result.distinct_id].person_id)
            outcome = "detached" if result.outcome == DISTINCT_ID_WRITE_OUTCOME_APPLIED else "already_detached"
            context.action(row, outcome, version=int(result.row.version) if result.HasField("row") else None)
        elif result.outcome == DISTINCT_ID_WRITE_OUTCOME_PERSON_NOT_LIVE:
            context.action(row, "skipped_person_gone")
        else:
            context.action(row, "skipped_changed")
    _release_drained_owners(team_id, detached_owners, by_key, reported)


def _predicted_outcome(row: DistinctIdRow | None, write: DistinctIdWrite) -> str:
    """What applying `write` would report, from the Postgres primary's row, by the RPC's rules."""
    if row is None or not row.HasField("person_is_deleted"):
        return "skipped_person_gone"
    if row.person_uuid != write.person_uuid or not row.person_is_deleted:
        return "skipped_changed"
    if row.is_deleted:
        return "already_detached" if row.version >= write.min_version else "skipped_changed"
    return "would_detach" if row.version == write.expected_version else "skipped_changed"


def _release_drained_owners(
    team_id: int, owner_ids: set[int], by_key: dict[str, dict[str, Any]], reported: dict[str, PgMapping]
) -> None:
    """Clear `blocked_at` for owners left with no live distinct id, so the next drain run retries them.

    An owner that still has a live distinct id stays blocked: the drain would block it again. The live distinct ids
    come from the replica, so a lagging replica only leaves an owner blocked until the drain's own retry.
    """
    if not owner_ids:
        return
    live = _live_distinct_ids(team_id, sorted(owner_ids), limit=1)
    uuids = {mapping.person_id: mapping.person_uuid for key in by_key if (mapping := reported[key]).person_uuid}
    released = sorted(uuid for owner in owner_ids if not live.get(owner) and (uuid := uuids[owner]) is not None)
    cleanup_queue.set_blocked(team_id, released, blocked=False)


def _live_distinct_ids(team_id: int, person_ids: list[int], *, limit: int) -> dict[int, list[str]]:
    by_person = personhog_call(
        "get_distinct_ids_for_persons",
        lambda: _batched_get_distinct_ids_for_persons(team_id, person_ids, limit_per_person=limit),
    )
    return {person_id: [d.id for d in dids] for person_id, dids in by_person.items()}


def split_distinct_ids(
    team_id: int,
    person_uuid: str,
    distinct_ids: Sequence[str],
    *,
    apply: bool,
    log: Callable[[str], None],
) -> list[str]:
    """Move `distinct_ids` off a live person onto persons of their own, and return the distinct ids split.

    `Person.split_person` does the split through personhog and refuses one that would leave the person without a
    distinct id; the dry run applies the same check. A distinct id that is not live on this person stops the whole
    split, so a mistyped id never splits the rest alone. Every applied split republishes the moved persons from
    Postgres and checks the result, and raises with the command that finishes the job when ClickHouse may still
    show a moved id on this person.
    """
    ids = list(dict.fromkeys(distinct_ids))
    if not ids:
        raise SplitError("name at least one --distinct-id")
    try:
        person_uuid = str(UUID(person_uuid))
    except ValueError as exc:
        raise SplitError(f"{person_uuid!r} is not a uuid") from exc
    persons = get_persons_by_uuids(team_id, [person_uuid], distinct_id_limit=0)
    if not persons:
        raise SplitError(f"person {person_uuid} is not live in team {team_id}")
    person = persons[0]
    rows = {r.distinct_id: r for r in get_distinct_id_rows(team_id, ids, strong=True)}
    elsewhere = sorted(
        d for d in ids if (row := rows.get(d)) is None or row.is_deleted or row.person_uuid != person_uuid
    )
    if elsewhere:
        raise SplitError(f"not live on person {person_uuid}: {', '.join(elsewhere)}")
    # One more than the request names: if every returned id is in the request, none would remain.
    remaining = _live_distinct_ids(team_id, [int(person.pk)], limit=len(ids) + 1).get(int(person.pk), [])
    if all(distinct_id in ids for distinct_id in remaining):
        raise SplitError(f"the split would leave person {person_uuid} with no distinct id")
    if not apply:
        log(f"split: would move {len(ids)} distinct ids off person {person_uuid}")
        return []
    failure: Exception | None = None
    try:
        person.split_person(None, None, distinct_ids_to_split=ids)
    except Exception as exc:
        # A failure after the first batch leaves the earlier batches split in Postgres, so they are resent too.
        failure = exc
    finally:
        # The split publishes to ClickHouse without waiting, and a command that exits first can lose those messages.
        flush_all_producers(_SPLIT_FLUSH_SECONDS)
    moved: list[str] = []
    try:
        moved = _moved_ids(team_id, person_uuid, ids)
        unconfirmed = _resend_split(team_id, moved, log=log)
    except Exception as exc:
        log(f"split: sending the split to ClickHouse again failed: {exc!r}")
        raise SplitError(_unconfirmed_message(team_id, person_uuid, moved or ids, failure)) from (failure or exc)
    if unconfirmed:
        raise SplitError(_unconfirmed_message(team_id, person_uuid, unconfirmed, failure)) from failure
    if failure is not None:
        raise SplitError(
            f"split moved {len(moved)} of {len(ids)} distinct ids off person {person_uuid}, then failed: {failure}"
        ) from failure
    if len(moved) < len(ids):
        raise SplitError(
            f"split moved {len(moved)} of {len(ids)} distinct ids off person {person_uuid}; check the rest with "
            "person_inspect"
        )
    log(f"split: moved {len(moved)} distinct ids off person {person_uuid}")
    return moved


def _moved_ids(team_id: int, person_uuid: str, distinct_ids: list[str]) -> list[str]:
    rows = get_distinct_id_rows(team_id, distinct_ids, strong=True)
    return [r.distinct_id for r in rows if not r.is_deleted and r.person_uuid and r.person_uuid != person_uuid]


def _resend_split(team_id: int, moved: list[str], *, log: Callable[[str], None]) -> list[str]:
    """Republish the persons the split moved distinct ids to, and return the moved ids still unconfirmed.

    Kafka's flush counts only queued messages, not failed deliveries, so every split is resent and checked. Without
    this, ClickHouse can keep the moved ids on the old person, and a scan suggests merging the two persons back.
    """
    if not moved:
        return []
    unconfirmed = list(repairs.republish_named(team_id, distinct_ids=moved, apply=True, log=log).unconfirmed)
    if unconfirmed:
        _sleep(_RESEND_RETRY_SECONDS)
        unconfirmed = list(repairs.republish_named(team_id, distinct_ids=unconfirmed, apply=True, log=log).unconfirmed)
    log(f"split: sent {len(moved)} moved distinct ids and their persons again, {len(unconfirmed)} unconfirmed")
    return unconfirmed


def _unconfirmed_message(team_id: int, person_uuid: str, distinct_ids: Sequence[str], failure: Exception | None) -> str:
    # The command prints only this message, not the exception it chains, so the split's own failure goes in it.
    failed = f" The split also failed: {failure}." if failure is not None else ""
    return (
        f"ClickHouse may still show {len(distinct_ids)} split distinct ids on person {person_uuid}.{failed} Do not "
        f"run a merge a scan suggests for them. Run: {_republish_command(team_id, distinct_ids)}"
    )


def _republish_command(team_id: int, distinct_ids: Sequence[str]) -> str:
    ids_file = _write_ids_file(team_id, distinct_ids) if len(distinct_ids) > _INLINE_DISTINCT_IDS else None
    if ids_file is not None:
        flags = f"--distinct-ids-file {shlex.quote(ids_file)}"
    else:
        flags = " ".join(f"--distinct-id {shlex.quote(d)}" for d in distinct_ids)
    return f"python manage.py person_consistency republish --team-id {team_id} {flags} --apply"


def _write_ids_file(team_id: int, distinct_ids: Sequence[str]) -> str | None:
    """Write one distinct id per line to a local file and return its path, or None when the ids must go inline.

    An id that is empty or holds a newline would not read back whole, and a failed write must not replace the
    error that prints the command.
    """
    if any(not d or "\n" in d for d in distinct_ids):
        return None
    try:
        with tempfile.NamedTemporaryFile("w", prefix=f"split-{team_id}-", suffix=".txt", delete=False) as ids_file:
            ids_file.write("".join(f"{d}\n" for d in distinct_ids))
    except OSError:
        return None
    return ids_file.name
