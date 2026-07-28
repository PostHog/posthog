from datetime import UTC, datetime, timedelta
from decimal import Decimal

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team

from products.billing_alerts.backend.models import (
    BillingAlertConfiguration,
    BillingAlertEvaluationClaim,
    BillingAlertEvent,
)
from products.billing_alerts.backend.temporal.activities import (
    _due_billing_alerts_for_sweep,
    _evaluate_billing_alerts,
    _group_key,
    due_billing_alerts_q,
)
from products.billing_alerts.backend.temporal.types import EvaluateBillingAlertBatchActivityInputs


def _billing_response(values: list[int]) -> dict:
    return {
        "status": "ok",
        "results": [
            {
                "id": 1,
                "label": "Total",
                "dates": ["2026-06-20", "2026-06-21", "2026-06-22"],
                "data": values,
            }
        ],
    }


class TestBillingAlertActivities(BaseTest):
    def _alert(self, **overrides) -> BillingAlertConfiguration:
        defaults = {
            "organization_id": self.organization.id,
            "team_id": self.team.id,
            "created_by_id": self.user.id,
            "name": "Daily spend spike",
            "metric": BillingAlertConfiguration.Metric.SPEND,
            "threshold_type": BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            "threshold_percentage": Decimal("50"),
            "minimum_value": Decimal("0"),
            "baseline_window_days": 2,
            "evaluation_delay_hours": 6,
        }
        defaults.update(overrides)
        return BillingAlertConfiguration.objects.create(**defaults)

    @freeze_time("2026-06-23T12:00:00Z")
    @patch("products.billing_alerts.backend.temporal.activities.fetch_billing_data")
    def test_fetch_failure_records_alert_failures_and_continues_batch(self, mock_fetch_billing_data) -> None:
        failed_alert = self._alert(name="Spend alert")
        successful_alert = self._alert(
            name="Second spend alert",
            evaluation_delay_hours=7,
        )

        def fetch_for_alert(alert, _organization, *, now):
            if alert.id == failed_alert.id:
                raise RuntimeError("billing unavailable")
            return _billing_response([60, 60, 100]), 12

        mock_fetch_billing_data.side_effect = fetch_for_alert

        with (
            patch(
                "products.billing_alerts.backend.logic.notifications.produce_alert_internal_event",
                return_value=MagicMock(),
            ),
            patch(
                "products.billing_alerts.backend.logic.notifications.flush_alert_internal_events"
            ) as flush_alert_internal_events,
            patch(
                "products.billing_alerts.backend.logic.notifications.alert_internal_event_delivered",
                return_value=True,
            ) as alert_internal_event_delivered,
        ):
            _evaluate_billing_alerts(
                EvaluateBillingAlertBatchActivityInputs(alert_ids=[str(failed_alert.id), str(successful_alert.id)])
            )

        failed_alert.refresh_from_db()
        successful_alert.refresh_from_db()
        failed_event = BillingAlertEvent.objects.get(claim__alert=failed_alert)
        successful_event = BillingAlertEvent.objects.get(claim__alert=successful_alert)

        assert mock_fetch_billing_data.call_count == 2
        assert failed_event.kind == BillingAlertEvent.Kind.ERRORED
        assert failed_event.is_transient_error is True
        assert failed_event.error_message == "Billing alert data fetch failed."
        assert failed_alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert successful_event.kind == BillingAlertEvent.Kind.FIRING
        assert successful_alert.state == BillingAlertConfiguration.State.FIRING
        flush_alert_internal_events.assert_called_once()
        assert alert_internal_event_delivered.call_count == 2

    def test_due_query_applies_billing_eligibility_boundaries(self) -> None:
        now = datetime(2026, 6, 23, 12, tzinfo=UTC)
        due = self._alert(name="Due", next_check_at=now)
        never_checked = self._alert(name="Never checked", next_check_at=None)
        self._alert(name="Future", next_check_at=now + timedelta(hours=1))
        self._alert(name="Disabled", enabled=False, next_check_at=now)
        self._alert(name="Broken", state=BillingAlertConfiguration.State.BROKEN, next_check_at=now)
        self._alert(name="Snoozed", snoozed_until=now + timedelta(hours=1), next_check_at=now)

        alert_ids = set(due_billing_alerts_q(now).values_list("id", flat=True))

        assert alert_ids == {due.id, never_checked.id}

    def test_due_sweep_interleaves_organizations_inside_global_cap(self) -> None:
        now = datetime(2026, 6, 23, 12, tzinfo=UTC)
        first = self._alert(name="First organization A", next_check_at=None)
        self._alert(name="First organization B", next_check_at=None)
        other_organization = Organization.objects.create(name="Other")
        other_team = Team.objects.create(organization=other_organization, name="Other project")
        other = self._alert(
            organization_id=other_organization.id,
            team_id=other_team.id,
            name="Other organization",
            next_check_at=None,
        )

        with patch("products.billing_alerts.backend.temporal.activities.MAX_DUE_BILLING_ALERTS_PER_TICK", 2):
            selected = list(_due_billing_alerts_for_sweep(now).values_list("id", flat=True))

        assert len(selected) == 2
        assert other.id in selected
        selected_organization_ids = set(
            BillingAlertConfiguration.objects.filter(id__in=selected).values_list("organization_id", flat=True)
        )
        assert selected_organization_ids == {first.organization_id, other.organization_id}

    def test_group_key_separates_pending_evaluation_dates(self) -> None:
        now = datetime(2026, 6, 23, 12, tzinfo=UTC)
        first = self._alert(pending_evaluation_date=datetime(2026, 6, 21, tzinfo=UTC).date())
        second = self._alert(pending_evaluation_date=datetime(2026, 6, 22, tzinfo=UTC).date())

        assert _group_key(first, now) != _group_key(second, now)

    @freeze_time("2026-06-23T12:00:00Z")
    @patch("products.billing_alerts.backend.temporal.activities.fetch_billing_data")
    def test_retry_skips_alert_already_rescheduled_by_prior_attempt(self, mock_fetch_billing_data) -> None:
        alert = self._alert(next_check_at=datetime(2026, 6, 24, 12, tzinfo=UTC))

        _evaluate_billing_alerts(EvaluateBillingAlertBatchActivityInputs(alert_ids=[str(alert.id)]))

        mock_fetch_billing_data.assert_not_called()

    @freeze_time("2026-06-23T12:00:00Z")
    @patch("products.billing_alerts.backend.temporal.activities.fetch_billing_data")
    def test_completed_claim_advances_a_still_due_alert(self, mock_fetch_billing_data) -> None:
        now = datetime(2026, 6, 23, 12, tzinfo=UTC)
        alert = self._alert(next_check_at=now)
        BillingAlertEvaluationClaim.objects.create(
            alert=alert,
            evaluation_date=datetime(2026, 6, 22, tzinfo=UTC).date(),
            configuration_revision=alert.configuration_revision,
            status=BillingAlertEvaluationClaim.Status.COMPLETED,
        )

        _evaluate_billing_alerts(EvaluateBillingAlertBatchActivityInputs(alert_ids=[str(alert.id)]))

        alert.refresh_from_db()
        assert alert.next_check_at is not None
        assert alert.next_check_at > now
        assert alert.pending_evaluation_date is None
        mock_fetch_billing_data.assert_called_once()

    @freeze_time("2026-06-23T12:00:00Z")
    @patch("products.billing_alerts.backend.temporal.activities.fetch_billing_data")
    @patch("products.billing_alerts.backend.temporal.activities.commit_pending_billing_alert_dispatches")
    @patch("products.billing_alerts.backend.temporal.activities.prepare_billing_alert_dispatch")
    def test_alert_preparation_failure_retries_the_activity(
        self,
        mock_prepare_dispatch,
        mock_commit_dispatch,
        mock_fetch_billing_data,
    ) -> None:
        first = self._alert(name="First")
        second = self._alert(name="Second")
        mock_fetch_billing_data.return_value = (_billing_response([60, 60, 100]), 12)
        mock_prepare_dispatch.side_effect = RuntimeError("database unavailable")

        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            _evaluate_billing_alerts(EvaluateBillingAlertBatchActivityInputs(alert_ids=[str(first.id), str(second.id)]))

        assert mock_prepare_dispatch.call_count == 1
        mock_commit_dispatch.assert_not_called()

    @freeze_time("2026-06-23T12:00:00Z")
    @patch("products.billing_alerts.backend.temporal.activities.fetch_billing_data")
    def test_transient_fetch_failure_retries_before_recording_an_event(self, mock_fetch_billing_data) -> None:
        alert = self._alert()
        mock_fetch_billing_data.side_effect = RuntimeError("billing unavailable")

        with self.assertRaisesRegex(RuntimeError, "billing unavailable"):
            _evaluate_billing_alerts(
                EvaluateBillingAlertBatchActivityInputs(alert_ids=[str(alert.id)]),
                activity_attempt=1,
            )

        assert BillingAlertEvent.objects.filter(claim__alert=alert).exists() is False
