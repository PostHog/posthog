from django.core.management import call_command
from django.test import TestCase

from products.alerts.backend.models.alert_identity import AlertDestination, AlertIdentity, AlertProduct
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.logs.backend.models import LogsAlertConfiguration


def _hog_function(
    *, team, alert_id: str, event_id: str, template_id: str = "template-slack", name: str = "Destination"
) -> HogFunction:
    return HogFunction.objects.create(
        team=team,
        name=name,
        type="internal_destination",
        template_id=template_id,
        enabled=True,
        inputs_schema=[],
        inputs={},
        hog="return event",
        filters={
            "events": [{"id": event_id, "type": "events"}],
            "properties": [{"key": "alert_id", "value": alert_id, "operator": "exact", "type": "event"}],
        },
    )


class TestBackfillAlertDestinations(TestCase):
    def setUp(self) -> None:
        super().setUp()
        from posthog.models.organization import Organization
        from posthog.models.team import Team

        self.organization = Organization.objects.create(name="backfill-org")
        self.team = Team.objects.create(organization=self.organization, name="backfill-team")

    def test_classifies_and_stamps_logs_alert_destinations(self) -> None:
        alert = LogsAlertConfiguration.objects.create(
            team=self.team,
            name="Spike in errors",
            filters={},
        )
        firing = _hog_function(team=self.team, alert_id=str(alert.id), event_id="$logs_alert_firing")
        resolved = _hog_function(team=self.team, alert_id=str(alert.id), event_id="$logs_alert_resolved")

        call_command("backfill_alert_destinations", verbosity=0)

        identity = AlertIdentity.objects.get(id=alert.id)
        assert identity.product == AlertProduct.LOGS
        assert identity.organization_id == self.organization.id
        assert identity.execution_team_id == self.team.id

        destination = AlertDestination.objects.get(alert=identity)
        assert destination.type == "slack"

        firing.refresh_from_db()
        resolved.refresh_from_db()
        assert firing.alert_destination_id == destination.id
        assert firing.alert_event_kind == "firing"
        assert resolved.alert_destination_id == destination.id
        assert resolved.alert_event_kind == "resolved"

        alert.refresh_from_db()
        assert alert.alert_id == identity.id

    def test_groups_same_target_but_separates_different_targets(self) -> None:
        alert = LogsAlertConfiguration.objects.create(team=self.team, name="Alert", filters={})
        # Same slack channel — one destination, two events
        _hog_function(team=self.team, alert_id=str(alert.id), event_id="$logs_alert_firing")
        _hog_function(team=self.team, alert_id=str(alert.id), event_id="$logs_alert_resolved")
        # Different webhook URL — separate destination, one event per
        _hog_function(
            team=self.team,
            alert_id=str(alert.id),
            event_id="$logs_alert_firing",
            template_id="template-webhook",
        )

        call_command("backfill_alert_destinations", verbosity=0)

        destinations = list(AlertDestination.objects.filter(alert_id=alert.id))
        assert len(destinations) == 2
        types = {d.type for d in destinations}
        assert types == {"slack", "webhook"}

    def test_dry_run_writes_nothing(self) -> None:
        alert = LogsAlertConfiguration.objects.create(team=self.team, name="Alert", filters={})
        _hog_function(team=self.team, alert_id=str(alert.id), event_id="$logs_alert_firing")

        call_command("backfill_alert_destinations", "--dry-run", verbosity=0)

        assert AlertIdentity.objects.count() == 0
        assert AlertDestination.objects.count() == 0
        assert alert.alert_id is None

    def test_idempotent_second_run(self) -> None:
        alert = LogsAlertConfiguration.objects.create(team=self.team, name="Alert", filters={})
        _hog_function(team=self.team, alert_id=str(alert.id), event_id="$logs_alert_firing")

        call_command("backfill_alert_destinations", verbosity=0)
        first_count = AlertDestination.objects.count()

        call_command("backfill_alert_destinations", verbosity=0)
        # Functions already stamped to a destination are skipped — no duplicates.
        assert AlertDestination.objects.count() == first_count

    def test_skips_functions_missing_alert_id_filter(self) -> None:
        alert = LogsAlertConfiguration.objects.create(team=self.team, name="Alert", filters={})
        # This one has the event but no alert_id filter — must NOT be classified.
        HogFunction.objects.create(
            team=self.team,
            name="Unowned",
            type="internal_destination",
            template_id="template-slack",
            enabled=True,
            inputs_schema=[],
            inputs={},
            hog="return event",
            filters={"events": [{"id": "$logs_alert_firing", "type": "events"}]},
        )

        call_command("backfill_alert_destinations", verbosity=0)

        assert AlertIdentity.objects.count() == 0
        assert AlertDestination.objects.count() == 0
