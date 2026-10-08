from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import (
    disable_configurations,
    due_checks,
    record_outcomes,
    slot_of,
    upsert_configuration,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    CheckFailure,
    FiringEpisode,
    GroupAdmission,
    Grouping,
    GroupingMode,
    GroupOutcome,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
    SourceKind,
)
from products.alerts_platform.backend.logic.platform_lifecycle import CONFIGURATION_ROW_ALERT_ID
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration
from products.alerts_platform.backend.models.platform_alert_events_sql import SHARDED_PLATFORM_ALERT_EVENTS_TABLE

_GROUP_FIELDS = ("kind", "new_state", "notified", "firing_episode", "value", "labels", "muted_notification")


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

    def _record(
        self, *, at: datetime | None = None, groups: tuple[GroupOutcome, ...] | None = None, **overrides
    ) -> None:
        at = at or self.cutoff
        group_fields: dict[str, Any] = {
            "grouping_key": "",
            "kind": AlertEventKind.FIRING,
            "new_state": "firing",
            "notified": True,
        }
        group_fields.update({name: overrides.pop(name) for name in _GROUP_FIELDS if name in overrides})
        fields: dict[str, Any] = {
            "configuration_id": self.configuration.id,
            "evaluation_key": f"window:{at.isoformat()}",
            "consecutive_failures": 0,
            "groups": (GroupOutcome(**group_fields),) if groups is None else groups,
        }
        fields.update(overrides)
        # History rides `transaction.on_commit`, which a `TestCase` transaction never reaches.
        with self.captureOnCommitCallbacks(execute=True):
            record_outcomes(self.team.id, [PlatformAlertOutcome(**fields)], at)

    def _alert(self, grouping_key: str = "") -> PlatformAlert:
        with team_scope(self.team.id):
            return PlatformAlert.objects.get(configuration=self.configuration, grouping_key=grouping_key)

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
        assert (self.configuration.enabled, self.configuration.check_status) == (False, "broken")
        assert due_checks(self.team.id, SourceKind.LOGS.value, self.slot, self.cutoff + timedelta(hours=1)) == ()

    def _next_due(self) -> datetime:
        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        assert self.configuration.next_check_at is not None
        return self.configuration.next_check_at

    def test_a_failed_check_marks_the_configuration_and_the_instance_keeps_its_firing(self) -> None:
        self._record(firing_episode=FiringEpisode(started_at=self.cutoff, ended=False))
        failed_at = self._next_due()
        self._record(
            at=failed_at,
            groups=(),
            failure=CheckFailure(
                kind=AlertEventKind.ERRORED,
                new_state="errored",
                notified=True,
                firing_episode=FiringEpisode(started_at=self.cutoff, ended=True),
            ),
            consecutive_failures=1,
        )

        failure_rows = sync_execute(
            "SELECT alert_id, grouping_key, previous_state, state FROM platform_alert_events "
            "WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s AND occurred_at = %(at)s",
            {"team_id": self.team.id, "configuration_id": self.configuration.id, "at": failed_at},
        )
        assert failure_rows == [(CONFIGURATION_ROW_ALERT_ID, "", "firing", "errored")]
        due = self._next_due()
        stored = self._alert()
        with team_scope(self.team.id):
            shown = platform_testing.alert_for(self.configuration.id)
        assert self.configuration.check_status == "errored"
        assert (stored.state, stored.firing_started_at) == ("firing", self.cutoff)
        assert shown is not None and shown.state == "errored"
        (check,) = due_checks(self.team.id, SourceKind.LOGS.value, slot_of(due, due), due)
        assert check.instance().state == "errored"

        self._record(at=due, groups=(), skipped=True)
        due = self._next_due()
        assert self.configuration.check_status == "errored"

        self._record(at=due, kind=AlertEventKind.CHECK, new_state="not_firing", notified=False)

        self._next_due()
        assert (self.configuration.check_status, self._alert().state) == ("ok", "not_firing")

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

    def test_each_group_of_a_check_keeps_its_own_instance_and_history_row(self) -> None:
        self._record(
            groups=(
                GroupOutcome(
                    grouping_key="api",
                    kind=AlertEventKind.FIRING,
                    new_state="firing",
                    notified=True,
                    firing_episode=FiringEpisode(started_at=self.cutoff, ended=False),
                    value=40.0,
                ),
                GroupOutcome(grouping_key="web", kind=AlertEventKind.CHECK, new_state="not_firing", notified=False),
            )
        )

        api, web = self._alert("api"), self._alert("web")
        assert (api.state, api.firing_started_at, api.last_notified_at) == ("firing", self.cutoff, self.cutoff)
        assert (web.state, web.firing_started_at, web.last_notified_at) == ("not_firing", None, None)
        rows = sync_execute(
            "SELECT grouping_key, alert_id, state, value FROM platform_alert_events "
            "WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s ORDER BY grouping_key",
            {"team_id": self.team.id, "configuration_id": self.configuration.id},
        )
        assert rows == [("api", api.id, "firing", 40.0), ("web", web.id, "not_firing", None)]

    def test_a_check_reads_each_group_composed_with_the_configuration(self) -> None:
        self._record(
            groups=(
                GroupOutcome(
                    grouping_key="api",
                    kind=AlertEventKind.FIRING,
                    new_state="firing",
                    notified=True,
                    firing_episode=FiringEpisode(started_at=self.cutoff, ended=False),
                ),
                GroupOutcome(grouping_key="web", kind=AlertEventKind.CHECK, new_state="not_firing", notified=False),
            )
        )
        due = self._next_due()
        muted_until = due + timedelta(hours=1)
        with team_scope(self.team.id):
            PlatformAlert.objects.filter(configuration=self.configuration, grouping_key="web").update(
                snooze_until=due + timedelta(hours=2)
            )
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(snooze_until=muted_until)

        (check,) = due_checks(self.team.id, SourceKind.LOGS.value, slot_of(due, due), due)

        assert {
            key: (check.instance(key).state, check.instance(key).snooze_until) for key in ("api", "web", "new")
        } == {
            "api": ("firing", muted_until),
            "web": ("not_firing", due + timedelta(hours=2)),
            "new": ("not_firing", muted_until),
        }
        assert check.instance("api").firing_started_at == self.cutoff

    def _group(self, key: str, *, state: str = "not_firing") -> GroupOutcome:
        return GroupOutcome(grouping_key=key, kind=AlertEventKind.CHECK, new_state=state, notified=False)

    def test_a_group_past_the_cap_gets_no_instance_and_no_history(self) -> None:
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=1).to_stored()
            )

        self._record(groups=(self._group("api"), self._group("web")))

        with team_scope(self.team.id):
            keys = list(
                PlatformAlert.objects.filter(configuration=self.configuration).values_list("grouping_key", flat=True)
            )
        rows = sync_execute(
            "SELECT grouping_key FROM platform_alert_events WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s",
            {"team_id": self.team.id, "configuration_id": self.configuration.id},
        )
        assert (keys, rows) == (["api"], [("api",)])

    @parameterized.expand(
        [
            ("idle_past_the_window", {}, False),
            ("firing", {"state": "firing"}, True),
            ("seen_recently", {"last_seen_hours_ago": 2}, True),
            ("still_snoozed", {"snoozed": True}, True),
            ("check_failed", {"failed": True}, True),
            ("cooldown_outlasts_the_window", {"cooldown_minutes": 48 * 60}, True),
        ]
    )
    def test_an_idle_group_is_reaped_so_its_slot_frees(self, _name: str, case: dict[str, Any], kept: bool) -> None:
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                cooldown_minutes=case.get("cooldown_minutes", 0),
                grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=1).to_stored(),
            )
            PlatformAlert.objects.create(
                team=self.team,
                configuration=self.configuration,
                grouping_key="old",
                state=case.get("state", "not_firing"),
                last_seen_at=self.cutoff - timedelta(hours=case.get("last_seen_hours_ago", 25)),
                snooze_until=self.cutoff + timedelta(hours=1) if case.get("snoozed") else None,
            )

        if case.get("failed"):
            self._record(
                groups=(), failure=CheckFailure(kind=AlertEventKind.ERRORED, new_state="errored", notified=False)
            )
        else:
            self._record(groups=(self._group("api"),))

        with team_scope(self.team.id):
            assert PlatformAlert.objects.filter(configuration=self.configuration, grouping_key="old").exists() is kept
            assert (
                PlatformAlert.objects.filter(configuration=self.configuration, grouping_key="api").exists() is not kept
            )

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
            instance = check.instance()
            return instance.state, instance.snooze_until

        with time_machine.travel(self.cutoff, tick=False):
            copy(snoozed_until)
        assert snooze_seen_by_check() == ("not_firing", snoozed_until)

        with team_scope(self.team.id):
            copied = PlatformAlertConfiguration.objects.get(legacy_configuration_id=legacy_id)
            PlatformAlert.objects.create(team=self.team, configuration=copied, state="firing")
        with time_machine.travel(self.cutoff, tick=False):
            copy(snoozed_until)
        assert snooze_seen_by_check() == ("firing", snoozed_until)

        copy(None)
        assert snooze_seen_by_check() == ("firing", None)


def _group(grouping_key: str) -> GroupOutcome:
    return GroupOutcome(grouping_key=grouping_key, kind=AlertEventKind.CHECK, new_state="not_firing", notified=False)


@pytest.mark.parametrize(
    "existing, returned, expected",
    [
        ((), ("a", "b", "c", "d"), GroupAdmission(admitted=frozenset({"a", "b", "c"}), overflowed=1)),
        (("x", "y", "z"), ("q", "x"), GroupAdmission(admitted=frozenset({"x"}), overflowed=1)),
        (("x",), ("x", "a", "a", "b"), GroupAdmission(admitted=frozenset({"x", "a", "b"}), overflowed=0)),
    ],
)
def test_a_check_admits_existing_groups_and_new_ones_up_to_the_cap(
    existing: tuple[str, ...], returned: tuple[str, ...], expected: GroupAdmission
) -> None:
    check = PlatformAlertCheckInput(
        id=uuid4(),
        team_id=1,
        name="API errors",
        source_config={},
        check_interval_minutes=5,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        cooldown_minutes=0,
        schedule_restriction=None,
        next_check_at=None,
        consecutive_failures=0,
        legacy_configuration_id=None,
        check_status="ok",
        snooze_until=None,
        instances=tuple(InstanceCheckState(grouping_key=key, state="not_firing") for key in existing),
        grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=3),
    )

    assert check.admit(returned) == expected


@pytest.mark.parametrize(
    "fields",
    [
        {"mode": GroupingMode.SINGLE, "keys": ("service",)},
        {"mode": GroupingMode.BY_RESULT_LABELS, "keys": ()},
        {"mode": GroupingMode.BY_RESULT_LABELS, "keys": ("service", "service")},
        {"mode": GroupingMode.BY_RESULT_LABELS, "keys": ("service",), "max_instances": 0},
    ],
)
def test_a_grouping_rejects_keys_its_mode_cannot_use(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Grouping(**fields)


@pytest.mark.parametrize(
    "overrides",
    [
        {"failure": CheckFailure(kind=AlertEventKind.ERRORED, new_state="errored", notified=True)},
        {"groups": (_group("api"), _group("api"))},
    ],
)
def test_an_outcome_rejects_an_invalid_shape(overrides: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "configuration_id": uuid4(),
        "evaluation_key": "slot:2026-09-16T10:00:00+00:00",
        "consecutive_failures": 0,
        "groups": (_group(""),),
    }
    fields.update(overrides)
    with pytest.raises(ValueError):
        PlatformAlertOutcome(**fields)
