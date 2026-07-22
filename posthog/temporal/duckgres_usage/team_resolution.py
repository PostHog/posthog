"""Re-attribute duckgres usage rows whose PostHog team is not billable.

duckgres stamps every managed-warehouse usage bucket with the org's default
PostHog team, resolved at record time. It treats that id as opaque, so if the
project is deleted without the org's default being repointed, duckgres keeps
emitting the dead id — and those rows would be dropped by the usage-report
gather (which only visits *billable* teams), silently under-billing the org.

Without this, MDW is *worse* than the platform norm: duckgres re-emits the dead
team every pull, so the loss recurs indefinitely (not the one-time "a deleted
team loses its in-flight usage" every product already tolerates). Re-attributing
and repointing brings it to parity — the only residual is the ~1 day around the
deletion (see the PR description).

At persist time we re-attribute a *deleted* team's rows (a team_id no longer in the
Team table) to a deterministic billable team in the same org (lowest id). Managed
warehouse bills at the org level, so the surrogate is billing-neutral — it only
changes per-team display, never the org total. A team that still exists but is
non-billable by design (a demo project, an internal-metrics org) is left alone: the
gather already excludes it, and remapping it would bill intentionally-free usage. The
elected surrogate MUST come from the gather's definition (`billable_teams_queryset`),
or the repoint would make under-billing permanent. Rows for a deleted team with no
billable team in the org are dropped and surfaced.
"""

import datetime as dt
import dataclasses
from collections.abc import Callable
from decimal import Decimal
from typing import TypeVar

from posthog.temporal.duckgres_usage.client import StorageRow, UsageRow

_Row = TypeVar("_Row", UsageRow, StorageRow)
_ComputeKey = tuple[dt.date, int, str, Decimal, Decimal]
_StorageKey = tuple[dt.date, int]


@dataclasses.dataclass(frozen=True)
class ResolvedTeams:
    compute_rows: list[UsageRow]
    storage_rows: list[StorageRow]
    # Orgs whose usage was dropped because they have no billable team at all. The
    # caller alerts on these; the ack still proceeds (re-pulling can't help — the
    # org has no billable team, so the data is unattributable, not withheld).
    orphaned_org_ids: set[str]
    # Orgs whose rows are *entirely* under a non-billable team — duckgres is stamping
    # a deleted/unbillable default — mapped to the elected billable team. The caller
    # repoints duckgres at the source; an org with any billable row is left alone.
    default_team_repoints: dict[str, int] = dataclasses.field(default_factory=dict)
    # Rows duckgres emitted twice with an IDENTICAL billing row (harmless repeat).
    # We keep one, the caller alerts, and the ack still proceeds.
    duplicate_row_count: int = 0
    # Rows with the same billing key but DIFFERENT measures — we can't trust either,
    # so keep the larger and the caller WITHHOLDS the ack for reconciliation.
    conflicting_row_count: int = 0


def _compute_key(row: UsageRow) -> _ComputeKey:
    return (row.date, row.team_id, row.query_source, row.cpu, row.mem_gib)


def _storage_key(row: StorageRow) -> _StorageKey:
    return (row.date, row.team_id)


def _compute_usage(row: UsageRow) -> tuple:
    return (row.cpu_seconds, row.memory_seconds)


def _storage_usage(row: StorageRow) -> tuple:
    return (row.gib_seconds,)


def _dedup_raw(
    rows: list[_Row], key: Callable[[_Row], tuple], usage: Callable[[_Row], tuple]
) -> tuple[list[_Row], int, int]:
    """Collapse rows duckgres emitted more than once for the same billing key — a
    contract violation (its API serves one row per key per day). Two flavours:

    - **exact duplicate** (same key AND identical row): a harmless repeat — keep one.
    - **value conflict** (same key, different measures — e.g. a partial then a
      corrected total): we can't tell which is right, so keep the row with the larger
      `usage` tuple — a provisional tie-break (lexicographic, not a per-field max) —
      and flag it. The caller withholds the ack so duckgres keeps the source for
      reconciliation instead of deleting it.

    Left in, either flavour would crash the mirror's unique insert or double-bill in
    the fold. Returns (deduped rows, exact-duplicate count, conflict count)."""
    by_key: dict[tuple, _Row] = {}
    exact = 0
    conflicts = 0
    for row in rows:
        k = key(row)
        kept = by_key.get(k)
        if kept is None:
            by_key[k] = row
        elif row == kept:
            exact += 1  # identical repeat — drop
        else:
            conflicts += 1
            if usage(row) > usage(kept):
                by_key[k] = row  # keep the larger; provisional until reconciled
    return list(by_key.values()), exact, conflicts


def resolve_billing_teams(compute_rows: list[UsageRow], storage_rows: list[StorageRow]) -> ResolvedTeams:
    """Remap rows under a *deleted* team to a billable team in the same org.

    Two notions of "not the right team", kept distinct on purpose:

    - **deleted** — the team_id isn't in the Team table at all (the project was
      deleted; duckgres keeps emitting the dead id). The gather would drop these, so
      we remap them to a live billable surrogate and repoint duckgres at the source.
    - **live but non-billable** — the team exists but is a demo project or in an
      internal-metrics org, so the gather excludes it *by design*. We leave these rows
      where they are; remapping would bill intentionally-free usage, and repointing
      would stomp a live default.

    The elected surrogate is always billable (`billable_teams_queryset`, the gather's
    own definition) — electing a demo/internal team would silently under-bill.
    """
    # Lazy imports: the elected surrogate MUST come from the usage-report gather's own
    # "billable team" set, or we could elect a team it refuses to bill (silent, and —
    # once repointed — permanent under-billing). Team gives us liveness (exists at all).
    from posthog.models import Team
    from posthog.tasks.usage_report import billable_teams_queryset

    # Collapse raw duplicates first (a duckgres contract violation), so the fold below
    # only ever sums *re-attribution* collisions — never double-bills a duplicate.
    compute_rows, compute_dupes, compute_conflicts = _dedup_raw(compute_rows, _compute_key, _compute_usage)
    storage_rows, storage_dupes, storage_conflicts = _dedup_raw(storage_rows, _storage_key, _storage_usage)
    duplicate_row_count = compute_dupes + storage_dupes
    conflicting_row_count = compute_conflicts + storage_conflicts

    team_ids = {row.team_id for row in compute_rows} | {row.team_id for row in storage_rows}
    if not team_ids:
        return ResolvedTeams(
            compute_rows,
            storage_rows,
            set(),
            duplicate_row_count=duplicate_row_count,
            conflicting_row_count=conflicting_row_count,
        )

    # "Dead" means *deleted* (absent from the Team table) — NOT merely non-billable. A
    # live demo/internal team is left alone below; only a genuinely deleted team's rows
    # get remapped, so we never start billing intentionally-free usage.
    live_team_ids = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
    deleted_team_ids = team_ids - live_team_ids
    if not deleted_team_ids:
        # Every row is under a live team (billable or intentionally non-billable) —
        # nothing to remap; the gather handles billability from here.
        return ResolvedTeams(
            compute_rows,
            storage_rows,
            set(),
            duplicate_row_count=duplicate_row_count,
            conflicting_row_count=conflicting_row_count,
        )

    billable = billable_teams_queryset()
    orgs_to_reattribute = {row.org_id for row in compute_rows if row.team_id in deleted_team_ids} | {
        row.org_id for row in storage_rows if row.team_id in deleted_team_ids
    }
    # Deterministic: the org's lowest-id billable team. The same dead team maps to the
    # same surrogate across pulls, so the mirror stays stable. None = no billable team.
    elected: dict[str, int | None] = {
        org_id: billable.filter(organization_id=org_id).order_by("id").values_list("id", flat=True).first()
        for org_id in orgs_to_reattribute
    }
    orphaned_org_ids = {org_id for org_id, team_id in elected.items() if team_id is None}

    # Which orgs to repoint at the source: those whose rows are *entirely* under
    # deleted teams (duckgres is stamping a default that no longer exists). If a live
    # team already appears for the org, duckgres has — or is mid-switch to — a live
    # default (billable or not), so leave it; the mirror remap below still fixes the
    # residual. (This can't see a switch to a new default that hasn't produced usage in
    # the window yet, so we may briefly override it — billing-neutral, self-corrects.)
    orgs_with_live_row = {row.org_id for row in compute_rows if row.team_id in live_team_ids} | {
        row.org_id for row in storage_rows if row.team_id in live_team_ids
    }
    default_team_repoints: dict[str, int] = {}
    for org_id in orgs_to_reattribute:
        elected_team = elected[org_id]
        if elected_team is not None and org_id not in orgs_with_live_row:
            default_team_repoints[org_id] = elected_team

    def reattribute(rows: list[_Row]) -> list[_Row]:
        out: list[_Row] = []
        for row in rows:
            if row.team_id in live_team_ids:
                out.append(row)  # live team (billable or intentionally non-billable) — leave it
                continue
            surrogate = elected[row.org_id]
            if surrogate is None:
                continue  # deleted team, no billable surrogate — orphaned, drop (surfaced below)
            out.append(dataclasses.replace(row, team_id=surrogate))
        return out

    return ResolvedTeams(
        _fold_compute(reattribute(compute_rows)),
        _fold_storage(reattribute(storage_rows)),
        orphaned_org_ids,
        default_team_repoints,
        duplicate_row_count,
        conflicting_row_count,
    )


def _fold_compute(rows: list[UsageRow]) -> list[UsageRow]:
    # After _dedup_raw, any remaining collision is a re-attribution merge (two dead
    # teams onto one surrogate) — sum it. A no-op when nothing collides (order preserved).
    by_key: dict[_ComputeKey, UsageRow] = {}
    for row in rows:
        key = _compute_key(row)
        existing = by_key.get(key)
        by_key[key] = (
            row
            if existing is None
            else dataclasses.replace(
                existing,
                cpu_seconds=existing.cpu_seconds + row.cpu_seconds,
                memory_seconds=existing.memory_seconds + row.memory_seconds,
            )
        )
    return list(by_key.values())


def _fold_storage(rows: list[StorageRow]) -> list[StorageRow]:
    by_key: dict[_StorageKey, StorageRow] = {}
    for row in rows:
        key = _storage_key(row)
        existing = by_key.get(key)
        by_key[key] = (
            row
            if existing is None
            else dataclasses.replace(existing, gib_seconds=existing.gib_seconds + row.gib_seconds)
        )
    return list(by_key.values())
