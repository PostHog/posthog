"""Re-attribute duckgres usage rows whose PostHog team no longer exists.

duckgres stamps every managed-warehouse usage bucket with the org's default
PostHog team, resolved at record time. It treats that id as opaque, so if the
project is deleted without the org's default being repointed, duckgres keeps
emitting the dead id — and those rows would be dropped by the usage-report
gather (which only visits live teams), silently under-billing the org.

Every other metered product tolerates a deleted team's usage vanishing, because
for them the team *is* the billing entity. Managed warehouse is different: ALL of
an org's usage funnels through this ONE default team, so the loss is org-scale,
not per-team. That larger blast radius is the reason this step exists (see the
PR description) — without it, MDW would be *worse* than the platform norm, since
duckgres keeps re-emitting the dead team every pull.

At persist time we re-attribute a dead team's rows to a deterministic live team
in the same org (lowest team id). Managed warehouse bills at the org level, so
the surrogate is billing-neutral — it only changes per-team display, never the
org total. Rows for an org with no live team at all are dropped and surfaced (a
warehouse with zero projects is degenerate).
"""

import dataclasses

from posthog.models import Team
from posthog.temporal.duckgres_usage.client import StorageRow, UsageRow


@dataclasses.dataclass(frozen=True)
class ResolvedTeams:
    compute_rows: list[UsageRow]
    storage_rows: list[StorageRow]
    # Orgs whose usage was dropped because they have no live team at all. The
    # caller alerts on these; the ack still proceeds (re-pulling can't help — the
    # org has no billable team, so the data is unattributable, not withheld).
    orphaned_org_ids: set[str]
    # Orgs whose rows are *entirely* under a dead team — duckgres is stamping a
    # deleted default — mapped to the elected live team. The caller repoints
    # duckgres at the source; an org with any live row present is left alone.
    default_team_repoints: dict[str, int] = dataclasses.field(default_factory=dict)


def resolve_billing_teams(compute_rows: list[UsageRow], storage_rows: list[StorageRow]) -> ResolvedTeams:
    """Remap rows under a deleted team to a live team in the same org.

    One `Team` existence query, plus one lowest-live-team lookup per org that
    actually has a dead team. The common case (every team live) does neither
    beyond the first query and returns the rows untouched.
    """
    team_ids = {row.team_id for row in compute_rows} | {row.team_id for row in storage_rows}
    if not team_ids:
        return ResolvedTeams(compute_rows, storage_rows, set())

    live_team_ids = set(Team.objects.filter(id__in=team_ids).values_list("id", flat=True))
    dead_team_ids = team_ids - live_team_ids
    if not dead_team_ids:
        return ResolvedTeams(compute_rows, storage_rows, set())

    orgs_to_reattribute = {row.org_id for row in compute_rows if row.team_id in dead_team_ids} | {
        row.org_id for row in storage_rows if row.team_id in dead_team_ids
    }
    # Deterministic: the org's lowest-id live team. The same dead team maps to the
    # same surrogate across pulls, so the mirror stays stable. None = no live team.
    elected: dict[str, int | None] = {
        org_id: Team.objects.filter(organization_id=org_id).order_by("id").values_list("id", flat=True).first()
        for org_id in orgs_to_reattribute
    }
    orphaned_org_ids = {org_id for org_id, team_id in elected.items() if team_id is None}

    # Which orgs to repoint at the source: those whose rows are *entirely* under
    # dead teams (duckgres is stamping a deleted default). If a live team already
    # appears for the org, duckgres has — or is mid-switch to — a live default, so
    # leave it alone; the mirror remap below still fixes the residual dead rows.
    orgs_with_live_row = {row.org_id for row in compute_rows if row.team_id in live_team_ids} | {
        row.org_id for row in storage_rows if row.team_id in live_team_ids
    }
    default_team_repoints: dict[str, int] = {}
    for org_id in orgs_to_reattribute:
        elected_team = elected[org_id]
        if elected_team is not None and org_id not in orgs_with_live_row:
            default_team_repoints[org_id] = elected_team

    def reattribute(rows: list) -> list:
        out = []
        for row in rows:
            if row.team_id in live_team_ids:
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
    )


def _fold_compute(rows: list[UsageRow]) -> list[UsageRow]:
    # Re-attribution can land two dead teams on one surrogate at the same billing
    # key; sum them, or the mirror's unique key rejects the second on bulk_create.
    # A no-op when nothing collides (order preserved).
    by_key: dict[tuple, UsageRow] = {}
    for row in rows:
        key = (row.date, row.team_id, row.query_source, row.cpu, row.mem_gib)
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
    by_key: dict[tuple, StorageRow] = {}
    for row in rows:
        key = (row.date, row.team_id)
        existing = by_key.get(key)
        by_key[key] = (
            row
            if existing is None
            else dataclasses.replace(existing, gib_seconds=existing.gib_seconds + row.gib_seconds)
        )
    return list(by_key.values())
