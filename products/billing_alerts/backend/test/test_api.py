from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team

from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent


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

    def test_list_is_scoped_to_organization(self) -> None:
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other project")
        BillingAlertConfiguration.objects.create(
            organization_id=other_org.id,
            execution_team_id=other_team.id,
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

    def test_non_admin_cannot_create(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, self._payload(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not BillingAlertConfiguration.objects.exists()

    def test_team_filters_must_belong_to_organization(self) -> None:
        other_org = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_org, name="Other project")

        response = self.client.post(self.url, self._payload(team_ids=[other_team.id]), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "team_ids" in response.json()["attr"]

    def test_check_now_uses_shared_organization_object_permissions(self) -> None:
        alert = BillingAlertConfiguration.objects.create(
            organization_id=self.organization.id,
            execution_team_id=self.team.id,
            name="Daily spend spike",
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )
        event = BillingAlertEvent.objects.create(
            alert=alert,
            kind=BillingAlertEvent.Kind.CHECK,
            metric=BillingAlertConfiguration.Metric.SPEND,
            state_before=BillingAlertConfiguration.State.NOT_FIRING,
            state_after=BillingAlertConfiguration.State.NOT_FIRING,
            reason="Manual check",
        )

        with (
            patch(
                "products.billing_alerts.backend.presentation.views.evaluate_and_record_billing_alert",
                return_value=event,
            ),
            patch("products.billing_alerts.backend.presentation.views.event_should_dispatch", return_value=False),
        ):
            response = self.client.post(f"{self.url}{alert.id}/check_now/", format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["event"]["id"] == str(event.id)
