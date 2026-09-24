from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest

from posthog.models.scoping import team_scope

from products.alerts.backend.facade.contracts import PlatformAlertOutcome, SourceKind
from products.alerts.backend.facade.platform_alerts import due_checks, record_outcomes
from products.alerts.backend.models import PlatformAlertConfiguration


class TestPlatformAlertLifecycle(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 16, 10, tzinfo=UTC)
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={},
                threshold_count=10,
                threshold_operator="above",
                window_minutes=5,
                check_interval_minutes=10,
                next_check_at=self.cutoff - timedelta(minutes=1),
            )
        self.slot = (self.cutoff - timedelta(minutes=1)).isoformat()

    def _record(self, **overrides) -> None:
        fields = {
            "configuration_id": self.configuration.id,
            "new_state": "firing",
            "notified": True,
            "consecutive_failures": 0,
        }
        fields.update(overrides)
        record_outcomes(self.team.id, [PlatformAlertOutcome(**fields)], self.cutoff, team_timezone=self.team.timezone)

    def test_a_disabling_outcome_stops_the_configuration_being_discovered(self) -> None:
        self._record(new_state="broken", notified=False, consecutive_failures=5, disable=True)

        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        assert self.configuration.enabled is False
        assert due_checks(self.team.id, SourceKind.LOGS.value, self.slot, self.cutoff + timedelta(hours=1)) == ()

    def test_recording_a_batch_twice_advances_the_schedule_once(self) -> None:
        self._record()
        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        after_first = self.configuration.next_check_at

        self._record()

        # Advancing twice skips a whole cycle for every alert in the batch.
        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        assert self.configuration.next_check_at == after_first
