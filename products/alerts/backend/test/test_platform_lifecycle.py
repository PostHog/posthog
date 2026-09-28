from datetime import UTC, datetime, timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest

from posthog.models.scoping import team_scope

from products.alerts.backend.facade.contracts import PlatformAlertOutcome, PlatformAlertUpsert, SourceKind
from products.alerts.backend.facade.platform_alerts import due_checks, record_outcomes, upsert_configuration
from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration


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

    def test_a_copied_snooze_reaches_the_check_and_a_later_unsnooze_clears_it(self) -> None:
        legacy_id = uuid4()
        snoozed_until = self.cutoff + timedelta(hours=2)

        def copy(snooze_until: datetime | None) -> None:
            upsert_configuration(
                PlatformAlertUpsert(
                    legacy_configuration_id=legacy_id,
                    team_id=self.team.id,
                    name="Snoozed alert",
                    enabled=True,
                    source_kind=SourceKind.LOGS,
                    source_config={},
                    threshold_count=1,
                    threshold_operator="above",
                    window_minutes=5,
                    check_interval_minutes=5,
                    evaluation_periods=1,
                    datapoints_to_alarm=1,
                    cooldown_minutes=0,
                    schedule_restriction=None,
                    next_check_at=self.cutoff - timedelta(minutes=1),
                    snooze_until=snooze_until,
                )
            )

        def snooze_seen_by_check() -> tuple[str, datetime | None]:
            (check,) = [
                c
                for c in due_checks(self.team.id, SourceKind.LOGS.value, self.slot, self.cutoff)
                if c.legacy_configuration_id == legacy_id
            ]
            return check.state, check.snooze_until

        with time_machine.travel(self.cutoff, tick=False):
            copy(snoozed_until)
        assert snooze_seen_by_check() == ("snoozed", snoozed_until)

        copy(None)
        assert snooze_seen_by_check() == ("not_firing", None)

        with team_scope(self.team.id):
            PlatformAlert.objects.filter(configuration__legacy_configuration_id=legacy_id).update(state="firing")
        expired = self.cutoff - timedelta(hours=1)
        copy(expired)
        assert snooze_seen_by_check() == ("firing", expired)
