from typing import Any, cast

from unittest.mock import patch

from django.db.models.query import QuerySet
from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.entitlements.contracts import EntitlementChange, EntitlementReactor, Entitlements, FeatureEntry
from posthog.entitlements.execution import execute_entitlement_reactor, get_behind_reactor_keys, load_entitlements
from posthog.entitlements.registry import EntitlementReactorRegistry
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig
from posthog.models.organization import Organization
from posthog.models.organization_entitlement_applied_state import OrganizationEntitlementAppliedState

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import BillingStatus


class TestEntitlementExecution(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Fixture organization")
        self.effect = OrganizationEventsRetentionConfig.objects.create(
            organization=self.organization, default_events_retention_months=1
        )
        self.changes: list[EntitlementChange] = []

        def react(change: EntitlementChange) -> None:
            self.changes.append(change)
            OrganizationEventsRetentionConfig.objects.using("default").filter(
                organization_id=change.organization_id
            ).update(default_events_retention_months=change.current.limit("fixture"))

        self.registry = EntitlementReactorRegistry(
            reactors=(EntitlementReactor(key="fixture", feature_keys=frozenset({"fixture"}), react=react),)
        )
        for target in (
            "posthog.entitlements.execution.get_entitlement_reactor_registry",
            "posthog.entitlements.dispatch.get_entitlement_reactor_registry",
            "ee.billing.billing_manager.get_entitlement_reactor_registry",
        ):
            registry_patch = patch(target, return_value=self.registry)
            registry_patch.start()
            self.addCleanup(registry_patch.stop)

    def checkpoint(self, features: list[FeatureEntry]) -> OrganizationEntitlementAppliedState:
        return OrganizationEntitlementAppliedState.objects.create(
            organization=self.organization,
            reactor_key="fixture",
            snapshot=Entitlements.from_features(features).to_snapshot(),
            applied_at=timezone.now(),
        )

    def set_source(self, features: list[FeatureEntry]) -> Entitlements:
        Organization.objects.filter(id=self.organization.id).update(available_product_features=features)
        return load_entitlements(str(self.organization.id))

    def test_existing_checkpoint_execution_duplicate_and_changed_source(self) -> None:
        organization_id = str(self.organization.id)
        self.checkpoint([{"key": "fixture", "limit": 1}])
        current = self.set_source([{"key": "fixture", "limit": 2}, {"key": "unwatched"}])
        assert get_behind_reactor_keys(organization_id, current) == ["fixture"]
        assert execute_entitlement_reactor(organization_id, "fixture").applied
        first = OrganizationEntitlementAppliedState.objects.get(organization_id=organization_id)
        assert first.snapshot == [{"key": "fixture", "limit": 2, "unit": None}]
        assert self.changes[0] == EntitlementChange(
            organization_id=organization_id,
            previous=Entitlements.from_features([{"key": "fixture", "limit": 1}]),
            current=Entitlements.from_features([{"key": "fixture", "limit": 2}]),
        )
        assert not execute_entitlement_reactor(organization_id, "fixture").applied
        assert OrganizationEntitlementAppliedState.objects.get(pk=first.pk).applied_at == first.applied_at
        self.set_source([{"key": "fixture", "limit": 3}])
        assert execute_entitlement_reactor(organization_id, "fixture").applied
        self.effect.refresh_from_db()
        assert self.effect.default_events_retention_months == 3
        assert self.changes[-1].previous == self.changes[0].current
        assert len(self.changes) == 2

    def test_checkpoint_noop_ignores_unwatched_changes_but_not_removal(self) -> None:
        current = self.set_source([{"key": "fixture", "limit": 1}, {"key": "unwatched", "limit": 2}])
        self.checkpoint([{"key": "fixture", "limit": 1}])
        organization_id = str(self.organization.id)
        with self.assertNumQueries(1):
            assert get_behind_reactor_keys(organization_id, current) == []
        assert not execute_entitlement_reactor(organization_id, "fixture").applied
        current = self.set_source([{"key": "unwatched", "limit": 9}])
        assert get_behind_reactor_keys(organization_id, current) == ["fixture"]
        assert execute_entitlement_reactor(organization_id, "fixture").applied
        self.effect.refresh_from_db()
        assert self.effect.default_events_retention_months is None
        assert OrganizationEntitlementAppliedState.objects.get(organization_id=organization_id).snapshot == []

    def test_empty_source_is_ignored_even_with_a_nonempty_checkpoint(self) -> None:
        self.set_source([{"key": "fixture", "limit": 1}])
        self.checkpoint([{"key": "fixture", "limit": 1}])
        current = self.set_source([])
        with self.assertNumQueries(0):
            assert get_behind_reactor_keys(str(self.organization.id), current) == []
        assert not execute_entitlement_reactor(str(self.organization.id), "fixture").applied
        assert self.changes == []
        assert OrganizationEntitlementAppliedState.objects.get(organization=self.organization).snapshot == [
            {"key": "fixture", "limit": 1, "unit": None}
        ]

    @parameterized.expand(
        [
            ("enabled", True, [{"key": "fixture", "limit": 2}], True),
            ("disabled", False, [{"key": "fixture", "limit": 2}], False),
            ("presentation", True, [{"key": "fixture", "limit": 1, "name": "Renamed"}], False),
            ("unwatched", True, [{"key": "fixture", "limit": 1}, {"key": "other"}], False),
            ("empty", True, [], False),
        ]
    )
    def test_writer_initializes_only_changed_reactors_on_enabled_path(
        self, _name: str, enabled: bool, features: list[dict[str, Any]], creates_checkpoint: bool
    ) -> None:
        self.set_source([{"key": "fixture", "limit": 1}])
        self.organization.refresh_from_db()
        with patch("posthog.entitlements.dispatch.feature_enabled_or_false", return_value=enabled):
            BillingManager(None).update_org_details(
                self.organization, cast(BillingStatus, {"customer": {"available_product_features": features}})
            )
        snapshots = list(
            OrganizationEntitlementAppliedState.objects.filter(organization=self.organization).values_list(
                "snapshot", flat=True
            )
        )
        assert snapshots == ([[{"key": "fixture", "limit": 1, "unit": None}]] if creates_checkpoint else [])
        self.organization.refresh_from_db()
        assert self.organization.available_product_features == (features or [{"key": "fixture", "limit": 1}])

    def test_writer_does_not_replace_checkpoint_advanced_by_reactor(self) -> None:
        self.set_source([{"key": "fixture", "limit": 1}])
        self.organization.refresh_from_db()
        self.checkpoint([{"key": "fixture", "limit": 1}])
        self.set_source([{"key": "fixture", "limit": 2}])
        assert execute_entitlement_reactor(str(self.organization.id), "fixture").applied
        applied = OrganizationEntitlementAppliedState.objects.get(organization=self.organization)
        with patch("posthog.entitlements.dispatch.feature_enabled_or_false", return_value=True):
            BillingManager(None).update_org_details(
                self.organization,
                cast(BillingStatus, {"customer": {"available_product_features": [{"key": "fixture", "limit": 3}]}}),
            )
        preserved = OrganizationEntitlementAppliedState.objects.get(organization=self.organization)
        assert preserved.snapshot == [{"key": "fixture", "limit": 2, "unit": None}]
        assert preserved.applied_at == applied.applied_at
        assert get_behind_reactor_keys(str(self.organization.id), load_entitlements(str(self.organization.id))) == [
            "fixture"
        ]

    def test_writer_rolls_back_source_when_checkpoint_insert_fails(self) -> None:
        previous_features: list[FeatureEntry] = [{"key": "fixture", "limit": 1}]
        self.set_source(previous_features)
        self.organization.refresh_from_db()
        bulk_create = QuerySet.bulk_create

        def fail_after_insert(queryset: QuerySet, *args: Any, **kwargs: Any) -> Any:
            result = bulk_create(queryset, *args, **kwargs)
            if queryset.model is OrganizationEntitlementAppliedState:
                raise RuntimeError("Checkpoint insert failed")
            return result

        with (
            patch("posthog.entitlements.dispatch.feature_enabled_or_false", return_value=True),
            patch.object(QuerySet, "bulk_create", fail_after_insert),
            self.assertRaisesMessage(RuntimeError, "Checkpoint insert failed"),
        ):
            BillingManager(None).update_org_details(
                self.organization,
                cast(BillingStatus, {"customer": {"available_product_features": [{"key": "fixture", "limit": 2}]}}),
            )
        self.organization.refresh_from_db()
        assert self.organization.available_product_features == previous_features
        assert not OrganizationEntitlementAppliedState.objects.filter(organization=self.organization).exists()
