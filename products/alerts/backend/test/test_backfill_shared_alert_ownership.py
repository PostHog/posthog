"""Tests for the backfill_shared_alert_ownership management command."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from django.core.management import call_command

from posthog.test.base import APIBaseTest

from products.product_analytics.backend.facade.models import Insight
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.models.shared_alert import AlertDestination, AlertProduct, AlertSharedIdentity
from products.cdp.backend.models.hog_functions.hog_function import HogFunction


class TestBackfillSharedAlertOwnership(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")

    def _make_insight_alert(self) -> AlertConfiguration:
        return AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="Signups",
        )

    def _make_executor(self, *, alert_id: str, template_id: str, event_id: str, team=None) -> HogFunction:
        return HogFunction.objects.create(
            team=team or self.team,
            name="Test destination",
            # Alert destinations are created as internal_destination; anything else
            # wouldn't pass the hogfunction_alert_ownership_shape constraint once
            # ownership is stamped.
            type="internal_destination",
            template_id=template_id,
            enabled=True,
            inputs_schema=[],
            inputs={"url": {"value": "https://example.com/hook"}},
            hog="return event",
            filters={
                "events": [{"id": event_id, "type": "events"}],
                "properties": [{"key": "alert_id", "value": alert_id, "type": "event"}],
            },
        )

    def test_links_insight_alert_and_stamps_ownership(self) -> None:
        alert = self._make_insight_alert()
        function = self._make_executor(
            alert_id=str(alert.id), template_id="template-webhook", event_id="$insight_alert_firing"
        )

        call_command("backfill_shared_alert_ownership", product="insight")

        alert.refresh_from_db()
        assert alert.shared_alert is not None
        assert alert.shared_alert.id == alert.id
        assert alert.shared_alert.product == AlertProduct.INSIGHT

        destination = AlertDestination.objects.get(shared_alert=alert.shared_alert)
        function.refresh_from_db()
        assert function.alert_destination_id == destination.id
        assert function.alert_event_kind == "firing"

    def test_creates_one_destination_per_template_per_inputs_digest(self) -> None:
        # `HogFunction.save()` strips inputs that aren't in inputs_schema, so
        # each fixture keeps its own schema to let its inputs survive.
        slack_schema = [
            {"key": "slack_workspace", "type": "integration", "required": True},
            {"key": "channel", "type": "string", "required": True},
        ]
        alert = self._make_insight_alert()
        first_slack = self._make_executor(
            alert_id=str(alert.id), template_id="template-slack", event_id="$insight_alert_firing"
        )
        first_slack.inputs_schema = slack_schema
        first_slack.inputs = {"slack_workspace": {"value": 1}, "channel": {"value": "C-1"}}
        first_slack.save()
        second_slack = self._make_executor(
            alert_id=str(alert.id), template_id="template-slack", event_id="$insight_alert_firing"
        )
        second_slack.inputs_schema = slack_schema
        second_slack.inputs = {"slack_workspace": {"value": 1}, "channel": {"value": "C-2"}}
        second_slack.save()

        call_command("backfill_shared_alert_ownership", product="insight")

        destinations = AlertDestination.objects.filter(shared_alert_id=alert.id)
        assert destinations.count() == 2, f"expected two destinations, got {destinations.count()}"

    def test_leaves_ambiguous_executors_on_filter_path(self) -> None:
        alert = self._make_insight_alert()
        unclear = self._make_executor(
            alert_id=str(alert.id), template_id="template-webhook", event_id="$unknown_alert_firing"
        )

        call_command("backfill_shared_alert_ownership", product="insight")

        unclear.refresh_from_db()
        alert.refresh_from_db()
        # Unknown event kinds can't be safely stamped; the alert is linked but
        # the executor keeps filter-based routing for review.
        assert unclear.alert_destination_id is None
        assert alert.shared_alert is not None

    def test_dry_run_writes_nothing(self) -> None:
        alert = self._make_insight_alert()
        function = self._make_executor(
            alert_id=str(alert.id), template_id="template-webhook", event_id="$insight_alert_firing"
        )

        call_command("backfill_shared_alert_ownership", dry_run=True)

        function.refresh_from_db()
        assert function.alert_destination_id is None
        assert AlertDestination.objects.count() == 0
        assert AlertSharedIdentity.objects.count() == 0

    def test_idempotent_on_second_run(self) -> None:
        alert = self._make_insight_alert()
        self._make_executor(
            alert_id=str(alert.id), template_id="template-webhook", event_id="$insight_alert_firing"
        )

        call_command("backfill_shared_alert_ownership", product="insight")
        alert.refresh_from_db()
        first_shared_alert_id = alert.shared_alert_id
        first_destination_id = AlertDestination.objects.get(shared_alert_id=alert.id).id

        call_command("backfill_shared_alert_ownership", product="insight")

        alert.refresh_from_db()
        assert alert.shared_alert_id == first_shared_alert_id
        assert AlertDestination.objects.filter(shared_alert_id=alert.id).count() == 1
        assert AlertDestination.objects.get(shared_alert_id=alert.id).id == first_destination_id