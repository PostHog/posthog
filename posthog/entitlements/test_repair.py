from uuid import UUID

import pytest

from posthog.entitlements import execution, repair
from posthog.entitlements.contracts import EntitlementReactor, Entitlements, FeatureEntry
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
