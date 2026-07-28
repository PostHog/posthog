from decimal import Decimal

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.organization import OrganizationMembership

from products.billing_alerts.backend.alert_destinations import BILLING_ALERT_EVENT_IDS
from products.billing_alerts.backend.models import BillingAlertConfiguration
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction


class TestBillingAlertDestinations(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/organizations/{self.organization.id}/billing/alerts/"
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _alert(self, name: str = "Daily spend spike") -> BillingAlertConfiguration:
        return BillingAlertConfiguration.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            name=name,
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )

    def _destination(self, alert: BillingAlertConfiguration, event_id: str) -> HogFunction:
        return HogFunction.objects.create(
            team_id=alert.execution_team_id,
            name="Billing alert destination",
            type="internal_destination",
            enabled=True,
            hog="",
            template_id="template-webhook",
            filters={
                "events": [{"id": event_id, "type": "events"}],
                "properties": [
                    {
                        "key": "alert_id",
                        "value": str(alert.id),
                        "operator": "exact",
                        "type": "event",
                    }
                ],
            },
        )

    def _sync_webhook_template(self) -> None:
        HogFunctionTemplate.objects.get_or_create(
            template_id="template-webhook",
            defaults={
                "sha": "1.0.0",
                "name": "Webhook",
                "description": "Generic webhook template",
                "code": "return event",
                "code_language": "hog",
                "inputs_schema": [{"key": "url", "type": "string"}, {"key": "body", "type": "json"}],
                "type": "destination",
                "status": "stable",
                "category": ["Integrations"],
                "free": True,
            },
        )

    def test_create_destination_builds_one_hog_function_per_billing_event(self) -> None:
        self._sync_webhook_template()
        alert = self._alert()

        response = self.client.post(
            f"{self.url}{alert.id}/destinations/",
            {"type": "webhook", "webhook_url": "https://example.com/billing-alert"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        hog_function_ids = response.json()["hog_function_ids"]
        hog_functions = list(HogFunction.objects.filter(id__in=hog_function_ids))
        assert len(hog_functions) == len(BILLING_ALERT_EVENT_IDS)
        assert {(hog_function.filters or {})["events"][0]["id"] for hog_function in hog_functions} == set(
            BILLING_ALERT_EVENT_IDS
        )
        for hog_function in hog_functions:
            assert hog_function.template_id == "template-webhook"
            assert (hog_function.filters or {})["properties"] == [
                {
                    "key": "alert_id",
                    "value": str(alert.id),
                    "operator": "exact",
                    "type": "event",
                }
            ]

        alert_response = self.client.get(f"{self.url}{alert.id}/")
        assert alert_response.status_code == status.HTTP_200_OK
        assert alert_response.json()["destinations"] == [
            {"type": "webhook", "hog_function_ids": sorted(hog_function_ids)}
        ]

    def test_create_destination_rejects_duplicate_type(self) -> None:
        self._sync_webhook_template()
        alert = self._alert()
        payload = {"type": "webhook", "webhook_url": "https://example.com/billing-alert"}

        first = self.client.post(f"{self.url}{alert.id}/destinations/", payload, format="json")
        second = self.client.post(f"{self.url}{alert.id}/destinations/", payload, format="json")

        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert HogFunction.objects.filter(deleted=False, id__in=first.json()["hog_function_ids"]).count() == len(
            BILLING_ALERT_EVENT_IDS
        )

    def test_delete_destination_removes_complete_group(self) -> None:
        alert = self._alert()
        destinations = [self._destination(alert, event_id) for event_id in BILLING_ALERT_EVENT_IDS]

        response = self.client.post(
            f"{self.url}{alert.id}/destinations/delete/",
            {"hog_function_ids": [str(destination.id) for destination in destinations]},
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert HogFunction.objects.filter(
            id__in=[destination.id for destination in destinations], deleted=True
        ).count() == len(destinations)

    def test_delete_destination_rejects_another_alerts_hog_function(self) -> None:
        alert = self._alert()
        other_alert = self._alert("Other alert")
        destination = self._destination(alert, BILLING_ALERT_EVENT_IDS[0])

        response = self.client.post(
            f"{self.url}{other_alert.id}/destinations/delete/",
            {"hog_function_ids": [str(destination.id)]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        destination.refresh_from_db()
        assert destination.deleted is False
        assert destination.enabled is True

    def test_delete_alert_only_removes_billing_destinations(self) -> None:
        alert = self._alert()
        billing_destination = self._destination(alert, BILLING_ALERT_EVENT_IDS[0])
        unrelated_destination = self._destination(alert, "$unrelated_internal_event")

        response = self.client.delete(f"{self.url}{alert.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        billing_destination.refresh_from_db()
        unrelated_destination.refresh_from_db()
        assert billing_destination.deleted is True
        assert billing_destination.enabled is False
        assert unrelated_destination.deleted is False
        assert unrelated_destination.enabled is True
