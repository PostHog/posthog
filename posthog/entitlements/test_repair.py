from uuid import UUID

import pytest

from posthog.entitlements import execution, repair
from posthog.entitlements.contracts import EntitlementReactor, Entitlements, EntitlementSnapshotEntry, FeatureEntry
from posthog.entitlements.registry import EntitlementReactorRegistry
from posthog.models.organization import Organization
from posthog.models.organization_entitlement_applied_state import OrganizationEntitlementAppliedState


@pytest.mark.django_db
@pytest.mark.parametrize("page_size", [1, 3, 200])
def test_repair_pages_match_canonical_discovery(monkeypatch, page_size: int) -> None:
    registry = EntitlementReactorRegistry(
        reactors=(
            EntitlementReactor(key="fixture", feature_keys=frozenset({"a", "b"}), react=lambda _: None),
            EntitlementReactor(key="other", feature_keys=frozenset({"other"}), react=lambda _: None),
        )
    )
    monkeypatch.setattr(repair, "get_entitlement_reactor_registry", lambda: registry)
    monkeypatch.setattr(repair, "CANDIDATE_PAGE_SIZE", page_size)
    cases: list[tuple[list[FeatureEntry] | None, list[FeatureEntry] | None]] = [
        ([], None),
        (None, None),
        ([], [{"key": "a"}]),
        (None, [{"key": "a"}]),
        ([{"key": "a"}], None),
        ([{"key": "a", "limit": None}], [{"key": "a"}]),
        (
            [{"key": "b", "limit": 2}, {"key": "a", "unit": "month"}],
            [{"key": "a", "unit": "month"}, {"key": "b", "limit": 2}],
        ),
        ([{"key": "a", "limit": 3}], [{"key": "a", "limit": 2}]),
        ([{"key": "unwatched", "limit": 99}], [{"key": "unwatched", "limit": 2}]),
        ([{"key": "a", "unit": None}], [{"key": "a", "unit": "month"}]),
        ([{"key": "b"}], [{"key": "a"}]),
    ]
    expected = []
    for n, (source, previous) in enumerate(cases, start=1):
        org = Organization.objects.create(id=UUID(int=n), name="Fixture", available_product_features=source)
        Organization.objects.filter(id=org.id).update(available_product_features=source)
        if previous is not None:
            for reactor in registry:
                OrganizationEntitlementAppliedState.objects.create(
                    organization=org,
                    reactor_key=reactor.key,
                    applied_at="2026-11-13T00:00:00Z",
                    snapshot=Entitlements.from_features(previous).restricted_to(reactor.feature_keys).to_snapshot(),
                )
        if execution.get_behind_reactor_keys(str(org.id), Entitlements.from_features(source or []), registry=registry):
            expected.append(str(org.id))
    stale = Organization.objects.create(id=UUID(int=99), name="Stale declaration")
    Organization.objects.filter(id=stale.id).update(available_product_features=[{"key": "a"}])
    for reactor in registry:
        OrganizationEntitlementAppliedState.objects.create(
            organization=stale,
            reactor_key=reactor.key,
            applied_at="2026-11-13T00:00:00Z",
            snapshot=[{"key": "a", "limit": None, "unit": None}, {"key": "removed", "limit": None, "unit": None}],
        )
    expected.append(str(stale.id))
    seen = []
    after = None
    while True:
        page = repair.list_behind_organizations_page(after)
        assert page.candidate_count <= page_size
        seen.extend(page.organization_ids)
        if page.cursor is None:
            break
        assert after is None or page.cursor > after
        after = page.cursor
    assert seen == expected


@pytest.mark.django_db
def test_empty_registry_skips_repair_query(monkeypatch, django_assert_num_queries) -> None:
    monkeypatch.setattr(repair, "get_entitlement_reactor_registry", lambda: EntitlementReactorRegistry(reactors=()))
    with django_assert_num_queries(0):
        assert repair.list_behind_organizations_page(None).organization_ids == []


FIXTURE_REACTOR = EntitlementReactor(key="fixture", feature_keys=frozenset({"a"}), react=lambda _: None)
OTHER_REACTOR = EntitlementReactor(key="other", feature_keys=frozenset({"other"}), react=lambda _: None)


def walk_pages(monkeypatch: pytest.MonkeyPatch, page_size: int) -> tuple[list[str], int]:
    registry = EntitlementReactorRegistry(reactors=(FIXTURE_REACTOR, OTHER_REACTOR))
    monkeypatch.setattr(repair, "get_entitlement_reactor_registry", lambda: registry)
    monkeypatch.setattr(repair, "CANDIDATE_PAGE_SIZE", page_size)
    seen: list[str] = []
    candidates = 0
    after = None
    while True:
        page = repair.list_behind_organizations_page(after)
        seen.extend(page.organization_ids)
        candidates += page.candidate_count
        if page.cursor is None:
            return seen, candidates
        assert after is None or page.cursor > after
        after = page.cursor


def create_organization(number: int, features: list[FeatureEntry]) -> str:
    organization = Organization.objects.create(id=UUID(int=number), name="Fixture")
    Organization.objects.filter(id=organization.id).update(available_product_features=features)
    return str(organization.id)


def create_checkpoint(organization_id: str, reactor_key: str, snapshot: list[EntitlementSnapshotEntry]) -> None:
    OrganizationEntitlementAppliedState.objects.create(
        organization_id=organization_id, reactor_key=reactor_key, applied_at="2026-11-13T00:00:00Z", snapshot=snapshot
    )


@pytest.mark.django_db
def test_pages_skip_organizations_without_checkpoints(monkeypatch) -> None:
    behind_on_one_reactor = create_organization(10, [{"key": "a", "limit": 2}])
    create_checkpoint(behind_on_one_reactor, "fixture", [{"key": "a", "limit": 1, "unit": None}])
    create_checkpoint(behind_on_one_reactor, "other", [])
    current = create_organization(30, [{"key": "a", "limit": 2}])
    create_checkpoint(current, "fixture", [{"key": "a", "limit": 2, "unit": None}])
    behind_on_other = create_organization(50, [{"key": "other", "limit": 5}])
    create_checkpoint(behind_on_other, "other", [{"key": "other", "limit": 4, "unit": None}])
    Organization.objects.bulk_create(
        Organization(
            id=UUID(int=number),
            name="No checkpoint",
            slug=f"no-checkpoint-{number}",
            available_product_features=[{"key": "a", "limit": 2}],
        )
        for number in [*range(11, 21), *range(31, 41)]
    )
    assert walk_pages(monkeypatch, page_size=2) == ([behind_on_one_reactor, behind_on_other], 3)


@pytest.mark.django_db
def test_rows_for_unregistered_reactors_are_not_candidates(monkeypatch) -> None:
    organization_id = create_organization(1, [{"key": "a", "limit": 2}])
    create_checkpoint(organization_id, "retired", [{"key": "a", "limit": 1, "unit": None}])
    assert walk_pages(monkeypatch, page_size=2) == ([], 0)


@pytest.mark.django_db
def test_orphan_checkpoint_is_not_returned(monkeypatch) -> None:
    create_checkpoint(str(UUID(int=1)), "fixture", [{"key": "a", "limit": 1, "unit": None}])
    behind = create_organization(2, [{"key": "a", "limit": 2}])
    create_checkpoint(behind, "fixture", [{"key": "a", "limit": 1, "unit": None}])
    seen, _ = walk_pages(monkeypatch, page_size=1)
    assert seen == [behind]
