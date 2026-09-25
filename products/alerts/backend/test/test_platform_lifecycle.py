from datetime import UTC, datetime, timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.models.scoping import team_scope

from products.alerts.backend.facade.contracts import (
    AlertEventKind,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
    SourceKind,
)
from products.alerts.backend.facade.platform_alerts import due_checks, record_outcomes, upsert_configuration
from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration


class TestPlatformAlertLifecycle(ClickhouseTestMixin, APIBaseTest):
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
            "evaluation_key": f"window:{self.cutoff.isoformat()}",
            "kind": AlertEventKind.FIRING,
            "new_state": "firing",
            "notified": True,
            "consecutive_failures": 0,
        }
        at = overrides.pop("at", self.cutoff)
        fields["evaluation_key"] = f"window:{at.isoformat()}"
        fields.update(overrides)
        record_outcomes(self.team.id, [PlatformAlertOutcome(**fields)], at)

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

    def test_a_recorded_check_lands_in_history_with_what_it_measured(self) -> None:
        self._record(
            new_state="firing",
            value=47.0,
            query_duration_ms=12,
            muted_notification="fire",
        )

        rows = sync_execute(
            """
            SELECT kind, previous_state, state, value, alert_name, muted_notification,
                   JSONExtractInt(condition_snapshot, 'threshold_count')
            FROM platform_alert_events
            WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s
            """,
            {"team_id": self.team.id, "configuration_id": str(self.configuration.id)},
        )

        # `insert_events` never raises, so without reading a row back a broken write is invisible.
        assert rows == [("firing", "not_firing", "firing", 47.0, "API errors", "fire", 10)]

    def test_a_held_fire_clears_when_the_condition_ends(self) -> None:
        def held() -> bool:
            with team_scope(self.team.id):
                return PlatformAlert.objects.get(configuration=self.configuration, grouping_key="").firing_unannounced

        self._record(new_state="firing", notified=False, muted_notification="fire")
        assert held() is True

        # The incident ended inside the mute, so there is nothing left to announce when it lifts.
        # Leaving the flag set here made every later check re-fire.
        self._record(
            new_state="not_firing", notified=False, muted_notification="resolve", at=self.cutoff + timedelta(hours=1)
        )
        assert held() is False

    def test_a_muted_announcement_is_held_until_one_is_sent(self) -> None:
        def held() -> bool:
            with team_scope(self.team.id):
                return PlatformAlert.objects.get(configuration=self.configuration, grouping_key="").firing_unannounced

        self._record(new_state="firing", notified=False, muted_notification="fire")
        # Without this the alert reaches the end of its mute already FIRING and never says so.
        assert held() is True

        # A later tick: `record_outcomes` skips a configuration an earlier attempt advanced past.
        self._record(new_state="firing", notified=True, muted_notification="", at=self.cutoff + timedelta(hours=1))
        assert held() is False

    def test_a_copied_snooze_mutes_without_holding_back_the_check(self) -> None:
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
        assert snooze_seen_by_check() == ("not_firing", snoozed_until)

        with team_scope(self.team.id):
            PlatformAlert.objects.filter(configuration__legacy_configuration_id=legacy_id).update(state="firing")
        with time_machine.travel(self.cutoff, tick=False):
            copy(snoozed_until)
        assert snooze_seen_by_check() == ("firing", snoozed_until)

        copy(None)
        assert snooze_seen_by_check() == ("firing", None)
