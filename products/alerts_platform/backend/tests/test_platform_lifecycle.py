from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.api import (
    disable_configurations,
    due_checks,
    record_outcomes,
    upsert_configuration,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    FiringEpisode,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
    SourceKind,
)
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration
from products.alerts_platform.backend.models.platform_alert_events_sql import SHARDED_PLATFORM_ALERT_EVENTS_TABLE


class TestPlatformAlertLifecycle(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # History rows outlive the run that wrote them, while Postgres reissues the same team ids,
        # so a test reads another run's checks unless the table starts empty. The sharded table,
        # because a truncate of the distributed one in front of it reports success and clears
        # nothing.
        sync_execute(f"TRUNCATE TABLE IF EXISTS {SHARDED_PLATFORM_ALERT_EVENTS_TABLE}")
        self.cutoff = datetime(2026, 9, 16, 10, tzinfo=UTC)
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={
                    "condition": {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}
                },
                check_interval_minutes=10,
                next_check_at=self.cutoff - timedelta(minutes=1),
            )
        self.slot = (self.cutoff - timedelta(minutes=1)).isoformat()

    def _record(self, *, at: datetime | None = None, **overrides) -> None:
        at = at or self.cutoff
        fields = {
            "configuration_id": self.configuration.id,
            "evaluation_key": f"window:{at.isoformat()}",
            "kind": AlertEventKind.FIRING,
            "new_state": "firing",
            "notified": True,
            "consecutive_failures": 0,
        }
        fields.update(overrides)
        # History rides `transaction.on_commit`, which a `TestCase` transaction never reaches.
        with self.captureOnCommitCallbacks(execute=True):
            record_outcomes(self.team.id, [PlatformAlertOutcome(**fields)], at)

    def _alert(self) -> PlatformAlert:
        with team_scope(self.team.id):
            return PlatformAlert.objects.get(configuration=self.configuration)

    def test_the_row_holds_the_firing_the_alert_is_in_and_drops_the_one_that_ended(self) -> None:
        # A field missing from the `bulk_update` list is never persisted and nothing else notices.
        self._record(firing_episode=FiringEpisode(started_at=self.cutoff, ended=False))
        assert self._alert().firing_started_at == self.cutoff

        self._record(
            new_state="not_firing",
            firing_episode=FiringEpisode(started_at=self.cutoff, ended=True),
            at=self.cutoff + timedelta(hours=1),
        )
        assert self._alert().firing_started_at is None

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
            firing_episode=FiringEpisode(started_at=self.cutoff, ended=False),
        )

        rows = sync_execute(
            """
            SELECT kind, previous_state, state, value, alert_name, muted_notification,
                   JSONExtractInt(condition_snapshot, 'threshold_count'), episode_started_at
            FROM platform_alert_events
            WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s
            """,
            {"team_id": self.team.id, "configuration_id": str(self.configuration.id)},
        )

        # `insert_events` never raises, so without reading a row back a broken write is invisible.
        assert rows == [("firing", "not_firing", "firing", 47.0, "API errors", "fire", 10, self.cutoff)]

    def test_a_resolve_row_keeps_the_firing_it_ended(self) -> None:
        # The alert row clears the firing on a resolve, so history is the only place left holding
        # the start a delivery needs to reply under the message that fired.
        self._record(
            new_state="not_firing",
            kind=AlertEventKind.RESOLVED,
            firing_episode=FiringEpisode(started_at=self.cutoff, ended=True),
        )

        rows = sync_execute(
            # Scoped to this configuration, not the team: ClickHouse is not rolled back between
            # runs while Postgres team ids restart, so a team id arrives carrying older rows.
            "SELECT state, episode_started_at FROM platform_alert_events "
            "WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s",
            {"team_id": self.team.id, "configuration_id": self.configuration.id},
        )

        assert rows == [("not_firing", self.cutoff)]
        assert self._alert().firing_started_at is None

    def _copy(self, legacy_id: UUID, **overrides: Any) -> None:
        fields: dict[str, Any] = {
            "legacy_configuration_id": legacy_id,
            "team_id": self.team.id,
            "name": "Copied alert",
            "enabled": True,
            "source_kind": SourceKind.LOGS,
            "source_config": {"condition": {"threshold_count": 1, "threshold_operator": "above", "window_minutes": 5}},
            "check_interval_minutes": 5,
            "evaluation_periods": 1,
            "datapoints_to_alarm": 1,
            "cooldown_minutes": 0,
            "schedule_restriction": None,
            "next_check_at": self.cutoff - timedelta(minutes=1),
            "snooze_until": None,
        }
        fields.update(overrides)
        upsert_configuration(PlatformAlertUpsert(**fields))

    @parameterized.expand(
        [
            # The source parks its own next check at the end of quiet hours. The platform still
            # checks through them and only mutes, so taking that time would skip the muted checks.
            ("an_enabled_copy_keeps_its_own_schedule", False, 5, timedelta(minutes=-1), timedelta(minutes=-1)),
            # A copy that has never had a schedule takes the first one the source offers.
            ("an_unscheduled_copy_takes_the_source_schedule", False, 5, None, timedelta(minutes=34)),
            # A copy switched off with --disable comes back at the source's next due time.
            ("a_disabled_copy_takes_the_source_schedule", True, 5, timedelta(minutes=-1), timedelta(minutes=34)),
            # A new cadence makes the old due time wrong, so the source's own one is the better guess.
            ("a_new_cadence_takes_the_source_schedule", False, 60, timedelta(minutes=-1), timedelta(minutes=34)),
        ]
    )
    def test_a_second_copy_keeps_the_schedule_the_platform_owns(
        self,
        _name: str,
        disabled_between: bool,
        interval_on_rerun: int,
        first_offset: timedelta | None,
        expected_offset: timedelta,
    ) -> None:
        legacy_id = uuid4()
        quiet_hours = {"blocked_windows": [{"start": "15:00", "end": "15:34"}]}

        self._copy(
            legacy_id,
            schedule_restriction=quiet_hours,
            next_check_at=None if first_offset is None else self.cutoff + first_offset,
        )
        if disabled_between:
            disable_configurations(SourceKind.LOGS, team_id=self.team.id)
        self._copy(
            legacy_id,
            schedule_restriction=quiet_hours,
            next_check_at=self.cutoff + timedelta(minutes=34),
            check_interval_minutes=interval_on_rerun,
        )

        with team_scope(self.team.id):
            copied = PlatformAlertConfiguration.objects.get(legacy_configuration_id=legacy_id)
        assert copied.next_check_at == self.cutoff + expected_offset

    def test_a_copied_snooze_mutes_without_holding_back_the_check(self) -> None:
        legacy_id = uuid4()
        snoozed_until = self.cutoff + timedelta(hours=2)

        def copy(snooze_until: datetime | None) -> None:
            self._copy(legacy_id, snooze_until=snooze_until)

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
