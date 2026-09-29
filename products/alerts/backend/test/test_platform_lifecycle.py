from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import time_machine
from posthog.test.base import APIBaseTest

from posthog.models.scoping import team_scope

from products.alerts.backend.facade.conditions import AlertConditionValidationError
from products.alerts.backend.facade.contracts import (
    PlatformAlertOutcome,
    PlatformAlertUpsert,
    SourceKind,
    grouping_key_for,
)
from products.alerts.backend.facade.platform_alerts import due_checks, record_outcomes, slot_of, upsert_configuration
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
        record_outcomes(self.team.id, [PlatformAlertOutcome(**fields)], self.cutoff)

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


class TestGroupedPlatformAlerts(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 29, 10, tzinfo=UTC)
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="p95 per service",
                source_kind=PlatformAlertConfiguration.SourceKind.METRICS,
                source_config={},
                threshold_count=10,
                threshold_operator="above",
                window_minutes=5,
                check_interval_minutes=5,
                next_check_at=self.cutoff - timedelta(minutes=1),
            )
        self.slot = (self.cutoff - timedelta(minutes=1)).isoformat()

    def _group_outcome(self, grouping_key: str, **overrides) -> PlatformAlertOutcome:
        fields = {
            "configuration_id": self.configuration.id,
            "new_state": "firing",
            "notified": True,
            "consecutive_failures": 0,
            "grouping_key": grouping_key,
        }
        fields.update(overrides)
        return PlatformAlertOutcome(**fields)

    def _states(self) -> dict[str, str]:
        with team_scope(self.team.id):
            return {a.grouping_key: a.state for a in PlatformAlert.objects.filter(configuration=self.configuration)}

    def test_outcomes_for_two_groups_create_two_alert_rows(self) -> None:
        api, web = grouping_key_for({"service_name": "api"}), grouping_key_for({"service_name": "web"})

        record_outcomes(
            self.team.id,
            [self._group_outcome(api), self._group_outcome(web, new_state="not_firing", notified=False)],
            self.cutoff,
        )

        assert self._states() == {api: "firing", web: "not_firing"}

    def test_a_group_outcome_does_not_touch_another_groups_state(self) -> None:
        api, web = grouping_key_for({"service_name": "api"}), grouping_key_for({"service_name": "web"})
        record_outcomes(self.team.id, [self._group_outcome(api), self._group_outcome(web)], self.cutoff)

        record_outcomes(
            self.team.id,
            [self._group_outcome(web, new_state="not_firing", notified=True)],
            self.cutoff + timedelta(minutes=5),
        )

        assert self._states() == {api: "firing", web: "not_firing"}

    def test_due_checks_carries_every_group_state(self) -> None:
        api, web = grouping_key_for({"service_name": "api"}), grouping_key_for({"service_name": "web"})
        record_outcomes(
            self.team.id,
            [self._group_outcome(api), self._group_outcome(web, new_state="not_firing", notified=False)],
            self.cutoff,
        )

        later = self.cutoff + timedelta(minutes=10)
        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        (check,) = due_checks(
            self.team.id, SourceKind.METRICS.value, slot_of(self.configuration.next_check_at, later), later
        )

        assert {g.grouping_key: g.state for g in check.groups} == {api: "firing", web: "not_firing"}
        assert check.state == "not_firing"

    def test_a_replayed_grouped_batch_is_idempotent(self) -> None:
        api, web = grouping_key_for({"service_name": "api"}), grouping_key_for({"service_name": "web"})
        batch = [self._group_outcome(api), self._group_outcome(web)]
        record_outcomes(self.team.id, batch, self.cutoff)
        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        after_first = self.configuration.next_check_at

        record_outcomes(self.team.id, batch, self.cutoff)

        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        assert self.configuration.next_check_at == after_first
        assert self._states() == {api: "firing", web: "firing"}

    def test_the_configuration_takes_the_worst_failure_count_and_any_disable(self) -> None:
        api, web = grouping_key_for({"service_name": "api"}), grouping_key_for({"service_name": "web"})

        record_outcomes(
            self.team.id,
            [
                self._group_outcome(api, consecutive_failures=2),
                self._group_outcome("", new_state="broken", notified=False, consecutive_failures=5, disable=True),
                self._group_outcome(web),
            ],
            self.cutoff,
        )

        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        assert self.configuration.consecutive_failures == 5
        assert self.configuration.enabled is False

    def test_grouping_keys_are_stable_across_label_order(self) -> None:
        assert grouping_key_for({"b": "2", "a": "1"}) == grouping_key_for({"a": "1", "b": "2"})
        assert grouping_key_for({}) == ""

    def test_a_long_label_set_gets_a_key_that_fits_the_column(self) -> None:
        long_labels = {"url": "x" * 400, "service_name": "api"}
        key = grouping_key_for(long_labels)

        assert len(key) <= 255
        assert key == grouping_key_for(dict(reversed(list(long_labels.items()))))
        assert key != grouping_key_for({"url": "y" * 400, "service_name": "api"})
        record_outcomes(self.team.id, [self._group_outcome(key)], self.cutoff)
        assert self._states() == {key: "firing"}


class TestHogConditionConfigurations(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cutoff = datetime(2026, 9, 29, 10, tzinfo=UTC)
        self.slot = (self.cutoff - timedelta(minutes=1)).isoformat()

    def _copy(self, source: str | None, condition_type: str = "hog") -> None:
        upsert_configuration(
            PlatformAlertUpsert(
                legacy_configuration_id=uuid4(),
                team_id=self.team.id,
                name="custom",
                enabled=True,
                source_kind=SourceKind.METRICS,
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
                snooze_until=None,
                condition_type=condition_type,
                condition_source=source,
            )
        )

    def test_upsert_compiles_a_hog_condition_and_the_check_carries_the_bytecode(self) -> None:
        self._copy("return value > threshold.count * 2")

        (check,) = due_checks(self.team.id, SourceKind.METRICS.value, self.slot, self.cutoff)

        assert check.condition_type == "hog"
        assert isinstance(check.condition_bytecode, list) and check.condition_bytecode

    def test_upsert_rejects_a_hog_condition_that_cannot_run(self) -> None:
        with pytest.raises(AlertConditionValidationError):
            self._copy("return (")

        assert due_checks(self.team.id, SourceKind.METRICS.value, self.slot, self.cutoff) == ()

    def test_upsert_rejects_an_unknown_condition_type(self) -> None:
        with pytest.raises(AlertConditionValidationError):
            self._copy("return true", condition_type="python")

        assert due_checks(self.team.id, SourceKind.METRICS.value, self.slot, self.cutoff) == ()

    def test_a_threshold_configuration_carries_no_bytecode(self) -> None:
        self._copy(None, condition_type="threshold")

        (check,) = due_checks(self.team.id, SourceKind.METRICS.value, self.slot, self.cutoff)

        assert check.condition_type == "threshold"
        assert check.condition_bytecode is None
