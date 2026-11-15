from datetime import UTC, datetime

from django.db import IntegrityError, transaction
from django.test import TestCase

from posthog.models.organization import Organization
from posthog.models.organization_entitlement_applied_state import OrganizationEntitlementAppliedState


class TestEntitlementAppliedState(TestCase):
    def test_uniqueness_is_per_organization_and_reactor(self) -> None:
        organizations = [Organization.objects.create(name=name) for name in ("First", "Second")]
        for organization in organizations:
            for reactor_key in ("exports", "other"):
                OrganizationEntitlementAppliedState.objects.create(
                    organization=organization,
                    reactor_key=reactor_key,
                    snapshot=[],
                    applied_at=datetime(2026, 11, 12, tzinfo=UTC),
                )
        with transaction.atomic(), self.assertRaises(IntegrityError):
            OrganizationEntitlementAppliedState.objects.create(
                organization=organizations[0],
                reactor_key="exports",
                snapshot=[],
                applied_at=datetime(2026, 11, 12, tzinfo=UTC),
            )
        for organization in organizations:
            assert OrganizationEntitlementAppliedState.objects.filter(organization=organization).count() == 2
