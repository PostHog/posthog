from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.exceptions import ValidationError

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team

from products.billing_alerts.backend.facade.contracts import BillingAlertDispatchResult
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent
from products.billing_alerts.backend.presentation.serializers import (
    BillingAlertConfigurationSerializer,
    BillingAlertCreateDestinationSerializer,
)
from products.cdp.backend.models.hog_functions.hog_function import HogFunction


class TestBillingAlertAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/organizations/{self.organization.id}/billing/alerts/"

    def _payload(self, **overrides) -> dict:
        payload = {
            "name": "Daily spend spike",
            "metric": "spend",
            "threshold_type": "relative_increase",
            "threshold_percentage": "50.00",
            "minimum_value": "0",
            "baseline_window_days": 7,
            "evaluation_delay_hours": 6,
            "check_interval_hours": 24,
            "cooldown_hours": 24,
        }
        payload.update(overrides)
        return payload

    def _alert(self, **overrides) -> BillingAlertConfiguration:
        defaults = {
            "organization_id": self.organization.id,
            "team_id": self.team.id,
            "name": "Daily spend spike",
            "metric": BillingAlertConfiguration.Metric.SPEND,
            "threshold_type": BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            "threshold_percentage": Decimal("50"),
        }
        defaults.update(overrides)
        return BillingAlertConfiguration.objects.create(**defaults)

    def _destination(self, alert: BillingAlertConfiguration, template_id: str) -> HogFunction:
        return HogFunction.objects.create(
            team_id=alert.execution_team_id,
            name=f"Billing alert destination {template_id}",
            type="internal_destination",
            enabled=True,
            hog="",
            template_id=template_id,
            filters={
                "properties": [
                    {
                        "key": "alert_id",
                        "value": str(alert.id),
                        "operator": "exact",
                        "type": "event",
                    }
                ]
            },
        )

    def test_create_billing_alert(self) -> None:
        response = self.client.post(self.url, self._payload(), format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["name"] == "Daily spend spike"
        assert data["organization_id"] == str(self.organization.id)
        assert data["execution_team_id"] == self.team.id
        assert data["created_by_id"] == self.user.id
        assert data["state"] == BillingAlertConfiguration.State.NOT_FIRING

        alert = BillingAlertConfiguration.objects.get(id=data["id"])
        assert alert.threshold_percentage == Decimal("50.00")

    def test_model_rejects_execution_team_from_different_organization(self) -> None:
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other project")
        alert = BillingAlertConfiguration(
            organization_id=self.organization.id,
            team_id=other_team.id,
            name="Daily spend spike",
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )

        with self.assertRaises(ValidationError):
            alert.full_clean()

    def test_list_is_scoped_to_organization(self) -> None:
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other project")
        BillingAlertConfiguration.objects.create(
            organization_id=other_org.id,
            team_id=other_team.id,
            name="Other alert",
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )
        self.client.post(self.url, self._payload(name="Visible alert"), format="json")

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [row["name"] for row in results] == ["Visible alert"]

    def test_destination_types_are_loaded_once_for_alert_list_serializer(self) -> None:
        slack_alert = self._alert(name="Slack alert")
        webhook_alert = self._alert(name="Webhook alert")
        empty_alert = self._alert(name="Empty alert")
        self._destination(slack_alert, "template-slack")
        self._destination(slack_alert, "template-slack")
        self._destination(webhook_alert, "template-webhook")

        serializer = BillingAlertConfigurationSerializer(
            [slack_alert, webhook_alert, empty_alert],
            many=True,
        )

        with self.assertNumQueries(1):
            data = list(serializer.data)

        assert data[0]["destination_types"] == ["slack"]
        assert data[1]["destination_types"] == ["webhook"]
        assert data[2]["destination_types"] == []

    def test_non_admin_cannot_create(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, self._payload(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not BillingAlertConfiguration.objects.exists()

    def test_webhook_destinations_require_https(self) -> None:
        alert = self._alert()

        serializer = BillingAlertCreateDestinationSerializer(
            data={"type": "webhook", "webhook_url": "http://example.com/billing-alert"},
            context={"alert": alert},
        )

        assert serializer.is_valid() is False
        assert "webhook_url" in serializer.errors

        serializer = BillingAlertCreateDestinationSerializer(
            data={"type": "webhook", "webhook_url": "https://"},
            context={"alert": alert},
        )

        assert serializer.is_valid() is False
        assert "webhook_url" in serializer.errors

        serializer = BillingAlertCreateDestinationSerializer(
            data={"type": "webhook", "webhook_url": "https://example.com/billing-alert"},
            context={"alert": alert},
        )

        assert serializer.is_valid(), serializer.errors

    def test_check_now_uses_shared_organization_object_permissions(self) -> None:
        alert = BillingAlertConfiguration.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            name="Daily spend spike",
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )
        event = BillingAlertEvent.objects.create(
            alert=alert,
            team_id=alert.team_id,
            kind=BillingAlertEvent.Kind.CHECK,
            metric=BillingAlertConfiguration.Metric.SPEND,
            state_before=BillingAlertConfiguration.State.NOT_FIRING,
            state_after=BillingAlertConfiguration.State.NOT_FIRING,
            reason="Manual check",
        )

        with patch(
            "products.billing_alerts.backend.presentation.views.billing_alerts_api.evaluate_and_dispatch_alert",
            return_value=BillingAlertDispatchResult(event=event, dispatched_destinations=0),
        ):
            response = self.client.post(f"{self.url}{alert.id}/check_now/", format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["event"]["id"] == str(event.id)
