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

At persist time we re-attribute a non-billable team's rows to a deterministic
billable team in the same org (lowest id). Managed warehouse bills at the org
level, so the surrogate is billing-neutral — it only changes per-team display,
never the org total. "Billable" MUST match the usage gather's definition
(`billable_teams_queryset`): a demo/internal team the gather won't bill must not
be elected, or the repoint makes the under-billing permanent. Rows for an org
with no billable team at all are dropped and surfaced.
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
      corrected total): we can't tell which is right, so keep the larger (by `usage`,
      erring high) and flag it. The caller withholds the ack so duckgres keeps the
      source for reconciliation instead of deleting it.

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
    """Remap rows under a non-billable team to a billable team in the same org.

    "Billable" is the usage gather's definition (`billable_teams_queryset`) — a team
    it will actually bill. A deleted team, and also a demo/internal team the gather
    excludes, count as non-billable here; electing one would silently under-bill.
    """
    # Lazy import: the resolver's "billable team" set MUST match the usage-report
    # gather's, or we can elect a team the gather refuses to bill (silent, and — once
    # repointed — permanent under-billing).
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

    billable = billable_teams_queryset()
    billable_team_ids = set(billable.filter(id__in=team_ids).values_list("id", flat=True))
    dead_team_ids = team_ids - billable_team_ids
    if not dead_team_ids:
        return ResolvedTeams(
            compute_rows,
            storage_rows,
            set(),
            duplicate_row_count=duplicate_row_count,
            conflicting_row_count=conflicting_row_count,
        )

    orgs_to_reattribute = {row.org_id for row in compute_rows if row.team_id in dead_team_ids} | {
        row.org_id for row in storage_rows if row.team_id in dead_team_ids
    }
    # Deterministic: the org's lowest-id billable team. The same dead team maps to the
    # same surrogate across pulls, so the mirror stays stable. None = no billable team.
    elected: dict[str, int | None] = {
        org_id: billable.filter(organization_id=org_id).order_by("id").values_list("id", flat=True).first()
        for org_id in orgs_to_reattribute
    }
    orphaned_org_ids = {org_id for org_id, team_id in elected.items() if team_id is None}

    # Which orgs to repoint at the source: those whose rows are *entirely* under
    # non-billable teams (duckgres is stamping a deleted/unbillable default). If a
    # billable team already appears for the org, duckgres has — or is mid-switch to — a
    # billable default, so leave it; the mirror remap below still fixes the residual.
    # (This can't see a switch to a new default that hasn't produced usage in the
    # window yet, so we may briefly override it — billing-neutral, self-corrects.)
    orgs_with_billable_row = {row.org_id for row in compute_rows if row.team_id in billable_team_ids} | {
        row.org_id for row in storage_rows if row.team_id in billable_team_ids
    }
    default_team_repoints: dict[str, int] = {}
    for org_id in orgs_to_reattribute:
        elected_team = elected[org_id]
        if elected_team is not None and org_id not in orgs_with_billable_row:
            default_team_repoints[org_id] = elected_team

    def reattribute(rows: list[_Row]) -> list[_Row]:
        out: list[_Row] = []
        for row in rows:
            if row.team_id in billable_team_ids:
                out.append(row)
                continue
            surrogate = elected[row.org_id]
            if surrogate is None:
                continue  # orphaned org — drop (surfaced via orphaned_org_ids)
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
