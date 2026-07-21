from datetime import date
from decimal import Decimal

import pytest

from posthog.models import Organization, Team

from products.billing_alerts.backend.models import (
    BillingAlertConfiguration,
    BillingAlertEvaluationClaim,
    BillingAlertEvent,
)
from products.billing_alerts.backend.presentation.serializers import BillingAlertEventSerializer


def test_relative_delta_percentage_supports_full_value_range() -> None:
    field = BillingAlertEvent._meta.get_field("relative_delta_percentage")

    assert field.max_digits == 28
    assert field.decimal_places == 6


@pytest.mark.django_db
def test_organization_deletion_cascades_all_billing_alert_rows() -> None:
    organization = Organization.objects.create(name="Acme")
    team = Team.objects.create(organization=organization, name="Default")
    alert = BillingAlertConfiguration.objects.create(
        organization=organization,
        team=team,
        name="Spend increase",
        threshold_percentage=Decimal("10"),
    )
    claim = BillingAlertEvaluationClaim.objects.create(
        alert=alert,
        evaluation_date=date(2026, 7, 20),
        configuration_revision=alert.configuration_revision,
    )
    BillingAlertEvent.objects.create(
        claim=claim,
        team=team,
        source=BillingAlertEvent.Source.SCHEDULED,
        attempt_number=1,
        metric=alert.metric,
    )

    organization.delete()

    assert BillingAlertConfiguration.objects.count() == 0
    assert BillingAlertEvaluationClaim.objects.count() == 0
    assert BillingAlertEvent.objects.count() == 0


def test_relative_delta_percentage_serializer_supports_model_value_range() -> None:
    alert = BillingAlertConfiguration(metric="spend")
    claim = BillingAlertEvaluationClaim(
        alert=alert,
        evaluation_date=date(2026, 7, 20),
        configuration_revision=7,
    )
    event = BillingAlertEvent(
        claim=claim,
        metric="spend",
        relative_delta_percentage=Decimal("9999999999999999999999.999999"),
        reason="Large relative change",
    )

    data = BillingAlertEventSerializer(event).data

    assert data["relative_delta_percentage"] == "9999999999999999999999.999999"
    assert data["configuration_revision"] == claim.configuration_revision
