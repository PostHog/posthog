"""Tests for re-attributing usage rows whose team has been deleted.

Managed-warehouse usage is stamped with the org's default team; if that project
is deleted, duckgres keeps emitting the dead id, and the rows would be dropped
by the (live-teams-only) usage-report gather. resolve_billing_teams remaps them
to a live team in the same org so the org still bills — org-level attribution
makes the surrogate choice billing-neutral.
"""

import datetime as dt
from decimal import Decimal

import pytest

from posthog.models import Organization, Team
from posthog.temporal.duckgres_usage.client import StorageRow, UsageRow
from posthog.temporal.duckgres_usage.team_resolution import resolve_billing_teams

pytestmark = pytest.mark.django_db

DEAD = 88_888_888  # an id no Team has
DEAD_2 = 88_888_889


def _org_with_teams(n: int = 2) -> tuple[Organization, list[Team]]:
    org = Organization.objects.create(name="mdw org")
    teams = [Team.objects.create(organization=org, name=f"team-{i}") for i in range(n)]
    return org, teams


def _compute(
    team_id: int,
    org_id: str,
    *,
    date: dt.date = dt.date(2026, 7, 6),
    cpu_seconds: int = 100,
    memory_seconds: int = 800,
    query_source: str = "standard",
) -> UsageRow:
    return UsageRow(
        date=date,
        org_id=org_id,
        team_id=team_id,
        query_source=query_source,
        cpu=Decimal("8"),
        mem_gib=Decimal("16"),
        cpu_seconds=cpu_seconds,
        memory_seconds=memory_seconds,
    )


def _storage(team_id: int, org_id: str, *, date: dt.date = dt.date(2026, 7, 6), gib: str = "360000") -> StorageRow:
    return StorageRow(date=date, org_id=org_id, team_id=team_id, gib_seconds=Decimal(gib))


def test_live_team_rows_pass_through_untouched() -> None:
    org, (t0, t1) = _org_with_teams()
    compute = [_compute(t0.id, str(org.id))]
    storage = [_storage(t1.id, str(org.id))]

    result = resolve_billing_teams(compute, storage)

    assert result.compute_rows == compute
    assert result.storage_rows == storage
    assert result.orphaned_org_ids == set()


def test_deleted_team_remapped_to_lowest_live_team_in_org() -> None:
    org, (t0, t1) = _org_with_teams()
    lowest = min(t0.id, t1.id)

    result = resolve_billing_teams(
        [_compute(DEAD, str(org.id), cpu_seconds=100)],
        [_storage(DEAD, str(org.id), gib="500")],
    )

    assert [r.team_id for r in result.compute_rows] == [lowest]
    assert [r.team_id for r in result.storage_rows] == [lowest]
    assert result.compute_rows[0].cpu_seconds == 100  # the value rides along unchanged
    assert result.storage_rows[0].gib_seconds == Decimal("500")
    assert result.orphaned_org_ids == set()


def test_org_with_no_live_team_is_dropped_and_reported() -> None:
    org = Organization.objects.create(name="no projects")  # warehouse but zero teams

    result = resolve_billing_teams([_compute(DEAD, str(org.id))], [_storage(DEAD, str(org.id))])

    assert result.compute_rows == []
    assert result.storage_rows == []
    assert result.orphaned_org_ids == {str(org.id)}


def test_two_dead_teams_in_one_org_fold_onto_the_surrogate() -> None:
    org, (t0, t1) = _org_with_teams()
    lowest = min(t0.id, t1.id)
    # Two distinct dead teams at the same billing key — must sum, not collide.
    compute = [
        _compute(DEAD, str(org.id), cpu_seconds=100, memory_seconds=80),
        _compute(DEAD_2, str(org.id), cpu_seconds=50, memory_seconds=40),
    ]

    result = resolve_billing_teams(compute, [])

    assert len(result.compute_rows) == 1
    assert result.compute_rows[0].team_id == lowest
    assert result.compute_rows[0].cpu_seconds == 150
    assert result.compute_rows[0].memory_seconds == 120


def test_only_the_dead_org_is_reattributed_not_its_live_sibling() -> None:
    org_a, (a0, a1) = _org_with_teams()
    org_b, (b0,) = _org_with_teams(n=1)
    compute = [
        _compute(a0.id, str(org_a.id)),  # live in A -> untouched
        _compute(DEAD, str(org_a.id), date=dt.date(2026, 7, 7)),  # dead in A -> A's lowest
        _compute(DEAD, str(org_b.id)),  # dead in B -> B's only team
    ]

    result = resolve_billing_teams(compute, [])

    by_org = {(r.org_id, r.date): r.team_id for r in result.compute_rows}
    assert by_org[(str(org_a.id), dt.date(2026, 7, 6))] == a0.id
    assert by_org[(str(org_a.id), dt.date(2026, 7, 7))] == min(a0.id, a1.id)
    assert by_org[(str(org_b.id), dt.date(2026, 7, 6))] == b0.id
    assert result.orphaned_org_ids == set()


def test_empty_input_is_a_noop() -> None:
    result = resolve_billing_teams([], [])
    assert result.compute_rows == []
    assert result.storage_rows == []
    assert result.orphaned_org_ids == set()


# --- default_team_repoints: which orgs to tell duckgres to switch -------------
# duckgres stamps usage with the org's default team and keeps emitting it after
# the project is deleted. When an org's rows are *entirely* under a dead team,
# duckgres's default is dead, so we surface the org → elected-live-team mapping;
# the workflow uses it to repoint duckgres at the source.


def test_deleted_default_team_is_repointed_to_the_elected_team() -> None:
    org, (t0, t1) = _org_with_teams()
    lowest = min(t0.id, t1.id)
    # Every row is under the dead team → duckgres is stamping a deleted default.
    result = resolve_billing_teams([_compute(DEAD, str(org.id))], [_storage(DEAD, str(org.id))])

    assert result.default_team_repoints == {str(org.id): lowest}


def test_org_with_a_live_team_present_is_not_repointed() -> None:
    org, (t0, t1) = _org_with_teams()
    # A live team already appears for the org → duckgres already has (or is
    # mid-switch to) a live default. Leave it: the dead row is still remapped in
    # the mirror, but we don't stomp duckgres's default.
    result = resolve_billing_teams(
        [_compute(t0.id, str(org.id)), _compute(DEAD, str(org.id), date=dt.date(2026, 7, 7))],
        [],
    )

    assert result.default_team_repoints == {}


def test_orphaned_org_is_not_repointed() -> None:
    org = Organization.objects.create(name="no projects")  # no live team to elect
    result = resolve_billing_teams([_compute(DEAD, str(org.id))], [])

    assert result.default_team_repoints == {}
    assert result.orphaned_org_ids == {str(org.id)}


def test_live_only_rows_have_no_repoints() -> None:
    org, (t0, t1) = _org_with_teams()
    result = resolve_billing_teams([_compute(t0.id, str(org.id))], [_storage(t1.id, str(org.id))])

    assert result.default_team_repoints == {}


def test_only_the_fully_dead_org_is_repointed() -> None:
    dead_org, (d0, d1) = _org_with_teams()  # entirely dead → repoint
    mixed_org, (m0,) = _org_with_teams(n=1)  # has a live row → leave alone
    compute = [
        _compute(DEAD, str(dead_org.id)),
        _compute(m0.id, str(mixed_org.id)),
        _compute(DEAD, str(mixed_org.id), date=dt.date(2026, 7, 7)),
    ]

    result = resolve_billing_teams(compute, [])

    assert result.default_team_repoints == {str(dead_org.id): min(d0.id, d1.id)}
