from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from django.core.exceptions import ValidationError

from posthog.models import Organization, Team

from products.billing_alerts.backend.models import (
    BillingAlertConfiguration,
    BillingAlertEvaluationClaim,
    BillingAlertEvent,
)


def test_relative_delta_percentage_supports_full_value_range() -> None:
    field = BillingAlertEvent._meta.get_field("relative_delta_percentage")

    assert field.max_digits == 28
    assert field.decimal_places == 6


def test_scheduler_index_matches_nulls_first_due_ordering() -> None:
    index = next(
        index for index in BillingAlertConfiguration._meta.indexes if index.name == "billing_alert_scheduler_idx"
    )

    assert index.expressions[0].name == "enabled"
    assert index.expressions[1].expression.name == "next_check_at"
    assert index.expressions[1].nulls_first is True


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


@pytest.mark.django_db
def test_team_deletion_leaves_alert_disabled_and_detached() -> None:
    organization = Organization.objects.create(name="Acme")
    team = Team.objects.create(organization=organization, name="Default")
    alert = BillingAlertConfiguration.objects.create(
        organization=organization,
        team=team,
        name="Spend increase",
        threshold_percentage=Decimal("10"),
        state=BillingAlertConfiguration.State.FIRING,
        next_check_at=datetime(2026, 7, 21, 12, tzinfo=UTC),
        pending_evaluation_date=date(2026, 7, 20),
    )

    team.delete()

    alert.refresh_from_db()
    assert alert.team_id is None
    assert alert.enabled is False
    assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
    assert alert.configuration_revision == 2
    assert alert.next_check_at is None
    assert alert.pending_evaluation_date is None


@pytest.mark.django_db
def test_execution_team_must_belong_to_alert_organization() -> None:
    alert_organization = Organization.objects.create(name="Acme")
    other_organization = Organization.objects.create(name="Other")
    other_team = Team.objects.create(organization=other_organization, name="Other team")
    alert = BillingAlertConfiguration(
        organization=alert_organization,
        team=other_team,
        name="Spend increase",
        threshold_percentage=Decimal("10"),
    )

    with pytest.raises(ValidationError) as error:
        alert.clean()

    assert error.value.message_dict == {"team": ["Execution team must belong to the billing alert organization."]}


@pytest.mark.django_db
def test_event_lineage_is_derived_from_its_claim() -> None:
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
    event = BillingAlertEvent.objects.create(
        claim=claim,
        team=team,
        source=BillingAlertEvent.Source.SCHEDULED,
        attempt_number=1,
        metric=alert.metric,
    )

    assert event.alert_id == alert.id
    assert event.organization_id == organization.id
    assert event.evaluation_date == claim.evaluation_date
    assert {"alert", "organization_id", "evaluation_date"}.isdisjoint(
        field.name for field in BillingAlertEvent._meta.fields
    )
