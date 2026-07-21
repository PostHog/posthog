from datetime import timedelta
from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team

from products.billing_alerts.backend.alert_destinations import EVENT_KIND_CONFIG
from products.billing_alerts.backend.facade.api import BillingAlertDispatchResult
from products.billing_alerts.backend.models import (
    BillingAlertConfiguration,
    BillingAlertEvaluationClaim,
    BillingAlertEvent,
)
from products.billing_alerts.backend.presentation.serializers import (
    BillingAlertConfigurationSerializer,
    BillingAlertDestinationCreateDataSerializer,
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
        destinations = [
            HogFunction.objects.create(
                team_id=alert.execution_team_id,
                name=f"Billing alert destination {template_id}",
                type="internal_destination",
                enabled=True,
                hog="",
                template_id=template_id,
                filters={
                    "events": [{"id": config.event_id, "type": "events"}],
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
            for config in EVENT_KIND_CONFIG.values()
        ]
        return destinations[0]

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

    def test_create_snoozed_alert_applies_snooze_transition(self) -> None:
        snoozed_until = timezone.now() + timedelta(hours=2)

        response = self.client.post(
            self.url,
            self._payload(snoozed_until=snoozed_until.isoformat()),
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        alert = BillingAlertConfiguration.objects.get(id=response.json()["id"])
        assert alert.state == BillingAlertConfiguration.State.SNOOZED
        assert alert.snoozed_until == snoozed_until

    def test_enable_resets_lifecycle_state_and_failures(self) -> None:
        alert = self._alert(
            enabled=False,
            state=BillingAlertConfiguration.State.BROKEN,
            consecutive_failures=5,
        )

        response = self.client.patch(f"{self.url}{alert.id}/", {"enabled": True}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        alert.refresh_from_db()
        assert alert.enabled is True
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.consecutive_failures == 0

    def test_disable_preserves_failure_count_and_resets_state(self) -> None:
        alert = self._alert(
            enabled=True,
            state=BillingAlertConfiguration.State.FIRING,
            consecutive_failures=3,
        )

        response = self.client.patch(f"{self.url}{alert.id}/", {"enabled": False}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        alert.refresh_from_db()
        assert alert.enabled is False
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.consecutive_failures == 3

    def test_snooze_preserves_failure_count_and_sets_snoozed_state(self) -> None:
        snoozed_until = timezone.now() + timedelta(hours=2)
        alert = self._alert(
            state=BillingAlertConfiguration.State.FIRING,
            consecutive_failures=2,
        )

        response = self.client.patch(
            f"{self.url}{alert.id}/",
            {"snoozed_until": snoozed_until.isoformat()},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        alert.refresh_from_db()
        assert alert.state == BillingAlertConfiguration.State.SNOOZED
        assert alert.snoozed_until == snoozed_until
        assert alert.consecutive_failures == 2

    def test_unsnooze_resets_state_and_failures(self) -> None:
        alert = self._alert(
            state=BillingAlertConfiguration.State.SNOOZED,
            snoozed_until=timezone.now() + timedelta(hours=2),
            consecutive_failures=4,
        )

        response = self.client.patch(f"{self.url}{alert.id}/", {"snoozed_until": None}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        alert.refresh_from_db()
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.snoozed_until is None
        assert alert.consecutive_failures == 0

    def test_threshold_edit_resets_firing_state_and_failures(self) -> None:
        alert = self._alert(
            state=BillingAlertConfiguration.State.FIRING,
            consecutive_failures=3,
        )

        response = self.client.patch(
            f"{self.url}{alert.id}/",
            {"threshold_percentage": "75.00"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        alert.refresh_from_db()
        assert alert.threshold_percentage == Decimal("75.00")
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.consecutive_failures == 0
        assert alert.configuration_revision == 2
        assert response.json()["configuration_revision"] == 2

    def test_copy_only_edit_does_not_bump_configuration_revision(self) -> None:
        alert = self._alert()

        response = self.client.patch(
            f"{self.url}{alert.id}/",
            {"name": "Renamed alert", "description": "Updated copy"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        alert.refresh_from_db()
        assert alert.configuration_revision == 1

    def test_evaluation_rule_edits_reset_firing_state_and_failures(self) -> None:
        updates = [
            ("baseline_window_days", 14),
            ("evaluation_delay_hours", 12),
        ]

        for field, value in updates:
            with self.subTest(field=field):
                alert = self._alert(
                    state=BillingAlertConfiguration.State.FIRING,
                    consecutive_failures=3,
                )

                response = self.client.patch(f"{self.url}{alert.id}/", {field: value}, format="json")

                assert response.status_code == status.HTTP_200_OK, response.json()
                alert.refresh_from_db()
                assert getattr(alert, field) == value
                assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
                assert alert.consecutive_failures == 0

    def test_threshold_edit_preserves_snoozed_state(self) -> None:
        snoozed_until = timezone.now() + timedelta(hours=2)
        alert = self._alert(
            state=BillingAlertConfiguration.State.SNOOZED,
            snoozed_until=snoozed_until,
            consecutive_failures=3,
        )

        response = self.client.patch(
            f"{self.url}{alert.id}/",
            {"minimum_value": "10.00"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        alert.refresh_from_db()
        assert alert.minimum_value == Decimal("10.00")
        assert alert.state == BillingAlertConfiguration.State.SNOOZED
        assert alert.snoozed_until == snoozed_until
        assert alert.consecutive_failures == 3

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

    def test_complete_destinations_are_loaded_once_for_alert_list_serializer(self) -> None:
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

        assert len(data[0]["destinations"][0]["hog_function_ids"]) == len(EVENT_KIND_CONFIG)
        assert len(data[1]["destinations"][0]["hog_function_ids"]) == len(EVENT_KIND_CONFIG)
        assert data[2]["destinations"] == []

    def test_non_admin_cannot_create(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, self._payload(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not BillingAlertConfiguration.objects.exists()

    def test_organization_write_key_can_create_and_update(self) -> None:
        api_key = self.create_personal_api_key_with_scopes(["organization:write"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        created = self.client.post(self.url, self._payload(), format="json")

        assert created.status_code == status.HTTP_201_CREATED, created.json()
        alert_id = created.json()["id"]

        updated = self.client.patch(
            f"{self.url}{alert_id}/",
            {"threshold_percentage": "75.00"},
            format="json",
        )

        assert updated.status_code == status.HTTP_200_OK, updated.json()
        assert updated.json()["threshold_percentage"] == "75.00"
        assert updated.json()["configuration_revision"] == 2

    def test_organization_read_key_cannot_create(self) -> None:
        api_key = self.create_personal_api_key_with_scopes(["organization:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")

        response = self.client.post(self.url, self._payload(), format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not BillingAlertConfiguration.objects.exists()

    def test_webhook_destinations_require_https(self) -> None:
        serializer = BillingAlertDestinationCreateDataSerializer(
            data={"type": "webhook", "webhook_url": "http://example.com/billing-alert"},
        )

        assert serializer.is_valid() is False
        assert "webhook_url" in serializer.errors

        serializer = BillingAlertDestinationCreateDataSerializer(
            data={"type": "webhook", "webhook_url": "https://"},
        )

        assert serializer.is_valid() is False
        assert "webhook_url" in serializer.errors

        serializer = BillingAlertDestinationCreateDataSerializer(
            data={"type": "webhook", "webhook_url": "https://example.com/billing-alert"},
        )

        assert serializer.is_valid(), serializer.errors

    def test_teams_destinations_require_a_microsoft_workflow_webhook(self) -> None:
        invalid = BillingAlertDestinationCreateDataSerializer(
            data={"type": "teams", "webhook_url": "https://example.com/teams"},
        )
        valid = BillingAlertDestinationCreateDataSerializer(
            data={
                "type": "teams",
                "webhook_url": "https://example.powerautomate.com/workflows/abc",
            },
        )

        assert invalid.is_valid() is False
        assert "webhook_url" in invalid.errors
        assert valid.is_valid(), valid.errors

    def test_rejects_negative_minimum(self) -> None:
        negative_minimum = self.client.post(self.url, self._payload(minimum_value="-1"), format="json")

        assert negative_minimum.status_code == status.HTTP_400_BAD_REQUEST
        assert negative_minimum.json()["attr"] == "minimum_value"

    def test_check_now_uses_shared_organization_object_permissions(self) -> None:
        alert = BillingAlertConfiguration.objects.create(
            organization_id=self.organization.id,
            team_id=self.team.id,
            name="Daily spend spike",
            metric=BillingAlertConfiguration.Metric.SPEND,
            threshold_type=BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            threshold_percentage=Decimal("50"),
        )
        claim = BillingAlertEvaluationClaim.objects.create(
            alert=alert,
            evaluation_date=timezone.now().date(),
            configuration_revision=alert.configuration_revision,
            attempt_count=1,
        )
        event = BillingAlertEvent.objects.create(
            claim=claim,
            team_id=alert.execution_team_id,
            kind=BillingAlertEvent.Kind.CHECK,
            source=BillingAlertEvent.Source.MANUAL,
            attempt_number=1,
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

    @patch(
        "products.billing_alerts.backend.presentation.throttles.BillingAlertCheckNowThrottle.rate",
        new="2/minute",
    )
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_check_now_is_throttled_per_organization_across_revisions_and_alerts(
        self, _rate_limit_enabled_mock
    ) -> None:
        first = self._alert(name="First")
        second = self._alert(name="Second")
        claim = BillingAlertEvaluationClaim.objects.create(
            alert=first,
            evaluation_date=timezone.now().date(),
            configuration_revision=first.configuration_revision,
            attempt_count=1,
        )
        event = BillingAlertEvent.objects.create(
            claim=claim,
            team_id=first.execution_team_id,
            kind=BillingAlertEvent.Kind.CHECK,
            source=BillingAlertEvent.Source.MANUAL,
            attempt_number=1,
            metric=BillingAlertConfiguration.Metric.SPEND,
            state_before=BillingAlertConfiguration.State.NOT_FIRING,
            state_after=BillingAlertConfiguration.State.NOT_FIRING,
            reason="Manual check",
        )
        throttle_key = f"throttle_billing_alert_check_now_organization_{self.organization.id}"
        cache.delete(throttle_key)
        self.addCleanup(cache.delete, throttle_key)

        with patch(
            "products.billing_alerts.backend.presentation.views.billing_alerts_api.evaluate_and_dispatch_alert",
            return_value=BillingAlertDispatchResult(event=event, dispatched_destinations=0),
        ) as evaluate_and_dispatch:
            first_check = self.client.post(f"{self.url}{first.id}/check_now/", format="json")
            edit = self.client.patch(
                f"{self.url}{first.id}/",
                {"threshold_percentage": "75.00"},
                format="json",
            )
            second_check = self.client.post(f"{self.url}{first.id}/check_now/", format="json")
            throttled = self.client.post(f"{self.url}{second.id}/check_now/", format="json")

        assert first_check.status_code == status.HTTP_200_OK
        assert edit.status_code == status.HTTP_200_OK
        assert edit.json()["configuration_revision"] == 2
        assert second_check.status_code == status.HTTP_200_OK
        assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert evaluate_and_dispatch.call_count == 2
