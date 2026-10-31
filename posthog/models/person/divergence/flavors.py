"""Classify one person or mapping by comparing its Postgres and ClickHouse state.

Pure functions over small state records, so every combination of states is testable without a database.
Each flavor names what is wrong; `PERSON_VERBS` and `MAPPING_VERBS` name the repair that fixes it, or None
when the state is accepted as it is.
"""

from __future__ import annotations

from typing import Literal

from posthog.dataclasses import frozen

PersonFlavor = Literal[
    "ok",
    "ok_deleted",
    "ghost",
    "deleted_visible",
    "hidden",
    "swept",
    "stale",
    "behind",
    "missing_in_ch",
    "tie",
    "blanked",
    "no_live_mappings",
]

MappingFlavor = Literal[
    "ok",
    "ok_deleted",
    "ghost",
    "deleted_visible",
    "diverged",
    "stale",
    "hidden",
    "missing_in_ch",
    "stray",
    "awaiting_sweep",
]

# Where a person tombstoned in Postgres stands in ClickHouse, by the rule the deletion sweep uses to take a person:
# `pending` when its newest visible row is a tombstone, `visible` when a live row is newest or ties it, `absent` when
# it has no visible row (already swept, or never published).
OwnerChState = Literal["pending", "visible", "absent"]

RepairVerb = Literal["republish", "merge_stale", "bury", "restore", "fold", "merge", "detach"]

# Keyed by (flavor, sub_flavor). A ghost's or diverged mapping's sub-flavor decides between restore,
# fold and merge. None means the state is accepted as it is.
PERSON_VERBS: dict[tuple[str, str | None], RepairVerb | None] = {
    # Ghosts of deleted teams are historical stock that no query reads; cleaning them up is out of scope.
    ("ghost", "team_gone"): None,
    ("ghost", "after_purge"): "restore",
    ("ghost", "historical"): None,
    ("deleted_visible", None): "bury",
    ("hidden", None): "republish",
    ("swept", None): "republish",
    ("stale", None): "merge_stale",
    ("behind", None): "republish",
    ("missing_in_ch", None): "republish",
    ("tie", None): "republish",
    ("blanked", None): "republish",
    ("no_live_mappings", None): None,
}

MAPPING_VERBS: dict[tuple[str, str | None], RepairVerb | None] = {
    ("ghost", "owner_ghost"): "restore",
    ("ghost", "owner_live"): "restore",
    ("ghost", "owner_deleted"): None,
    # Like their owners, ghosts of a deleted team are historical stock left as they are.
    ("ghost", "team_gone"): None,
    ("deleted_visible", None): "bury",
    ("diverged", "a_absent"): "fold",
    ("diverged", "a_live"): "merge",
    ("diverged", "a_deleted"): "republish",
    # The owning person holds mappings of more than one old person, so no single repair is safe.
    ("diverged", "ambiguous"): None,
    ("diverged", "a_unknown"): None,
    ("stale", None): "republish",
    ("hidden", None): "republish",
    ("missing_in_ch", None): "republish",
    # Ingestion also repairs a stray on the distinct id's next event, but a distinct id that sees no more events
    # keeps it, and the stray blocks the cleanup drain from hard-deleting its person. `detach` tombstones it in
    # Postgres only, which is safe only while ClickHouse holds nothing for it or the deletion sweep will remove what
    # it holds; the sub-flavors below are strays where neither is true, so they are reported for a person to fix.
    ("stray", None): "detach",
    # Its person row is gone, so there is no owner to name; ingestion re-attaches it on the next event.
    ("stray", "orphan"): None,
    # The owner's ClickHouse tombstone never landed, so no sweep takes it: `bury` the owner, then rescan.
    ("stray", "owner_visible"): None,
    # ClickHouse resolves the distinct id to a different person than Postgres does.
    ("stray", "ch_owner_differs"): None,
    # The owner is gone from ClickHouse but the distinct id still has rows there, which no sweep will remove.
    ("stray", "rows_outlive_owner"): None,
    # The caller did not read the owner's ClickHouse state, so whether a sweep will clean up is unknown.
    ("stray", "owner_unchecked"): None,
    # Rows at ClickHouse's top version name different owners, so the sweep may resolve another one.
    ("stray", "ch_tie"): None,
    # Tombstoned in Postgres; ClickHouse still resolves it to its tombstoned owner, which the next sweep removes
    # together with that owner. A ClickHouse tombstone published now could outlive the drain's hard delete.
    ("awaiting_sweep", None): None,
}


@frozen
class PgPerson:
    # None when the source of the state did not report it (tombstone lookups do not).
    id: int | None
    version: int
    is_deleted: bool
    # None when the source of the state did not report it (lookups by uuid do not).
    has_live_mappings: bool | None = None


@frozen
class ChPerson:
    # Over every row, including lightweight-deleted ones, so a raise lands above all of them.
    max_version: int
    # Over visible rows only.
    visible_rows: int
    live_max_version: int | None
    tombstone_max_version: int | None
    # Visible rows at the visible maximum version, and how many distinct payloads they carry.
    rows_at_max: int
    payloads_at_max: int
    # The visible winner is empty and unidentified while an earlier visible row had properties.
    winner_blanked: bool
    # Unix seconds of the newest visible row; dates a ghost against a known purge.
    newest_written_at: float | None = None


@frozen
class PgMapping:
    person_id: int
    person_uuid: str | None
    version: int
    is_deleted: bool
    person_is_deleted: bool | None


@frozen
class ChMapping:
    max_version: int
    visible_rows: int
    winner_person_uuid: str
    winner_version: int
    winner_deleted: bool
    # Visible rows at the top version disagree on the owner or on is_deleted, so which one ClickHouse and the
    # deletion sweep treat as the winner is not fixed.
    winner_tied: bool = False


@frozen
class Verdict:
    flavor: str
    sub_flavor: str | None
    verb: RepairVerb | None


def _verdict(kind: str, flavor: str, sub_flavor: str | None = None) -> Verdict:
    verbs = PERSON_VERBS if kind == "person" else MAPPING_VERBS
    return Verdict(flavor=flavor, sub_flavor=sub_flavor, verb=verbs.get((flavor, sub_flavor)))


def classify_person(
    pg: PgPerson | None, ch: ChPerson | None, *, team_exists: bool = True, ghost_era: str = "historical"
) -> Verdict:
    """The flavor of one person. `ghost_era` is the caller's dating of a ghost: `after_purge` when its
    newest ClickHouse row predates a known Postgres purge of the team, else `historical`."""
    if pg is None:
        if ch is None or ch.visible_rows == 0 or ch.live_max_version is None:
            return _verdict("person", "ok_deleted")
        if ch.tombstone_max_version is not None and ch.tombstone_max_version >= ch.live_max_version:
            return _verdict("person", "ok_deleted")
        return _verdict("person", "ghost", "team_gone" if not team_exists else ghost_era)

    if pg.is_deleted:
        # A visible live row at or above every visible tombstone keeps the person visible; ties count,
        # because ClickHouse picks either row at an equal version.
        if (
            ch is not None
            and ch.live_max_version is not None
            and (ch.tombstone_max_version is None or ch.live_max_version >= ch.tombstone_max_version)
        ):
            return _verdict("person", "deleted_visible")
        return _verdict("person", "ok_deleted")

    if ch is None:
        return _verdict("person", "missing_in_ch")
    if ch.visible_rows == 0:
        return _verdict("person", "swept")
    visible_max = max(v for v in (ch.live_max_version, ch.tombstone_max_version) if v is not None)
    if ch.tombstone_max_version is not None and ch.tombstone_max_version == visible_max:
        return _verdict("person", "hidden")
    if visible_max > pg.version:
        return _verdict("person", "stale")
    if visible_max < pg.version:
        return _verdict("person", "behind")
    if ch.rows_at_max > 1 and ch.payloads_at_max > 1:
        return _verdict("person", "tie")
    if ch.winner_blanked:
        return _verdict("person", "blanked")
    if pg.has_live_mappings is False:
        return _verdict("person", "no_live_mappings")
    return _verdict("person", "ok")


def owner_ch_state(state: ChPerson | None) -> OwnerChState:
    """Where a person stands in ClickHouse, by the sweep's rule: it takes a person whose newest visible row is a
    tombstone. A tie between a live and a tombstone row at the top version counts as visible, because which one
    ClickHouse treats as newest is not fixed."""
    if state is None or state.visible_rows == 0:
        return "absent"
    if state.tombstone_max_version is not None and (
        state.live_max_version is None or state.tombstone_max_version > state.live_max_version
    ):
        return "pending"
    return "visible"


def needs_owner_ch_state(pg: PgMapping | None, ch: ChMapping | None) -> bool:
    """Whether classifying this mapping depends on its Postgres owner's ClickHouse state."""
    return (
        pg is not None
        and pg.person_is_deleted is True
        and pg.person_uuid is not None
        and ch is not None
        and ch.visible_rows > 0
    )


def classify_mapping(
    pg: PgMapping | None,
    ch: ChMapping | None,
    *,
    ch_owner_pg_state: str | None = None,
    team_exists: bool = True,
    owner_ch: OwnerChState | None = None,
) -> Verdict:
    """The flavor of one mapping. `ch_owner_pg_state` is the Postgres state of ClickHouse's winning owner
    (`live`, `deleted` or `absent`), needed only for ghost and diverged mappings. `owner_ch` is the ClickHouse
    state of the Postgres owner, needed only when `needs_owner_ch_state` holds."""
    ch_live = ch is not None and ch.visible_rows > 0 and not ch.winner_deleted

    if pg is None:
        if not ch_live:
            return _verdict("mapping", "ok_deleted")
        if not team_exists:
            return _verdict("mapping", "ghost", "team_gone")
        sub = {"absent": "owner_ghost", "live": "owner_live", "deleted": "owner_deleted"}.get(
            ch_owner_pg_state or "absent", "owner_ghost"
        )
        return _verdict("mapping", "ghost", sub)

    if pg.is_deleted:
        if (
            ch_live
            and ch is not None
            and pg.person_is_deleted
            and ch.winner_person_uuid == pg.person_uuid
            and not ch.winner_tied
            and owner_ch == "pending"
            # Postgres must hold the tombstone above every ClickHouse version, so a returning distinct id revives
            # above them and ClickHouse shows it before the sweep removes the old rows.
            and pg.version > ch.max_version
        ):
            return _verdict("mapping", "awaiting_sweep")
        # A live winner at any version still resolves the id, so the tombstone has not reached ClickHouse.
        return _verdict("mapping", "deleted_visible" if ch_live else "ok_deleted")

    if pg.person_is_deleted is None:
        return _verdict("mapping", "stray", "orphan")
    if pg.person_is_deleted:
        return _verdict("mapping", "stray", _stray_sub_flavor(pg, ch, owner_ch))
    if ch is None or ch.visible_rows == 0:
        return _verdict("mapping", "missing_in_ch")
    if ch.winner_deleted:
        return _verdict("mapping", "hidden")
    if ch.winner_person_uuid != pg.person_uuid:
        sub = {"absent": "a_absent", "live": "a_live", "deleted": "a_deleted"}.get(ch_owner_pg_state or "", "a_unknown")
        return _verdict("mapping", "diverged", sub)
    if ch.winner_version > pg.version:
        return _verdict("mapping", "stale")
    return _verdict("mapping", "ok")


def _stray_sub_flavor(pg: PgMapping, ch: ChMapping | None, owner_ch: OwnerChState | None) -> str | None:
    """None when tombstoning the stray in Postgres alone is safe: the cleanup drain hard-deletes its Postgres row only
    after the deletion sweep removed the owner, and that sweep removes every ClickHouse row of a key whose newest row
    names the owner, live or tombstone. So it is safe when ClickHouse shows nothing, or when its newest row names the
    owner and the owner still waits for the sweep."""
    if ch is None or ch.visible_rows == 0:
        return None
    if ch.winner_tied:
        return "ch_tie"
    if ch.winner_person_uuid != pg.person_uuid:
        return "ch_owner_differs"
    if owner_ch is None:
        return "owner_unchecked"
    return {"pending": None, "visible": "owner_visible", "absent": "rows_outlive_owner"}[owner_ch]
