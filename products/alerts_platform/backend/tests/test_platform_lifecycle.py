import dataclasses
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
    get_configuration,
    give_back_ownership,
    record_outcomes,
    slot_of,
    take_ownership,
    upsert_configuration,
    upsert_if_running,
)
from products.alerts_platform.backend.facade.contracts import (
    MAX_INSTANCES_CEILING,
    AlertEventKind,
    CheckFailure,
    FiringEpisode,
    GroupAdmission,
    Grouping,
    GroupingMode,
    GroupOutcome,
    HandbackRefusal,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
    PlatformOwnershipHandover,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.alerts_platform.backend.facade.grouping import (
    MAX_TRANSITIONS_PER_DELIVERY,
    GroupObservation,
    bounded_labels,
    decide_groups,
    delivery_parts,
)
from products.alerts_platform.backend.facade.lifecycle import LOGS_ALERT_POLICY, AlertSnapshot, AlertState
from products.alerts_platform.backend.facade.payload import MAX_BATCH_PAYLOAD_BYTES, payload_bytes
from products.alerts_platform.backend.logic.platform_alert_events import announcement
from products.alerts_platform.backend.logic.platform_lifecycle import CONFIGURATION_ROW_ALERT_ID
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration
from products.alerts_platform.backend.models.platform_alert_events_sql import SHARDED_PLATFORM_ALERT_EVENTS_TABLE

_GROUP_FIELDS = (
    "kind",
    "new_state",
    "notified",
    "firing_episode",
    "value",
    "labels",
    "muted_notification",
    "source_detail",
)


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

    def test_a_check_that_started_before_a_handover_records_nothing(self) -> None:
        legacy_id = uuid4()
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                legacy_configuration_id=legacy_id
            )
        take_ownership(
            PlatformOwnershipHandover(
                legacy_configuration_id=legacy_id,
                team_id=self.team.id,
                state=PlatformAlertState.NOT_FIRING,
                last_notified_at=None,
                consecutive_failures=0,
                next_check_at=self.cutoff + timedelta(minutes=2),
                at=self.cutoff + timedelta(seconds=30),
            )
        )

        self._record()

        assert self._alert().state == "not_firing"

    @parameterized.expand(
        [
            ("a_delivered_firing_stays_with_its_source", "ok", True, 60, False, ("source", "firing", True)),
            # A copy checking beside its source fires without sending, so nothing it opened is orphaned.
            ("an_undelivered_firing_is_taken_over", "ok", False, 60, True, ("platform", "not_firing", False)),
            ("a_firing_whose_delivery_may_be_queued_stays", "ok", False, 1, False, ("source", "firing", True)),
            # The machine ended the firing when the check broke, so the row's firing is stale.
            ("a_broken_copy_is_taken_over", "broken", True, 60, True, ("platform", "not_firing", False)),
            ("an_errored_copy_is_taken_over", "errored", True, 60, True, ("platform", "not_firing", False)),
        ]
    )
    def test_a_copy_inside_its_own_firing_is_taken_over_unless_that_firing_was_delivered_and_runs(
        self,
        _name: str,
        check_status: str,
        delivered: bool,
        started_minutes_ago: int,
        expected_taken: bool,
        expected: tuple[str, str, bool],
    ) -> None:
        legacy_id = uuid4()
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                legacy_configuration_id=legacy_id, check_status=check_status
            )
            platform_testing.start_firing(
                self.configuration.id,
                team_id=self.team.id,
                at=self.cutoff - timedelta(minutes=started_minutes_ago),
                sent_natively=delivered,
            )

        taken = take_ownership(
            PlatformOwnershipHandover(
                legacy_configuration_id=legacy_id,
                team_id=self.team.id,
                state=PlatformAlertState.NOT_FIRING,
                last_notified_at=None,
                consecutive_failures=0,
                next_check_at=self.cutoff + timedelta(minutes=2),
                at=self.cutoff,
            )
        )

        alert = self._alert()
        self.configuration.refresh_from_db()
        assert taken is expected_taken
        assert (self.configuration.owner, alert.state, alert.firing_started_at is not None) == expected

    def test_a_firing_is_taken_over_with_its_start_unknown(self) -> None:
        legacy_id = uuid4()
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                legacy_configuration_id=legacy_id
            )

        taken = take_ownership(
            PlatformOwnershipHandover(
                legacy_configuration_id=legacy_id,
                team_id=self.team.id,
                state=PlatformAlertState.FIRING,
                last_notified_at=self.cutoff,
                consecutive_failures=0,
                next_check_at=self.cutoff + timedelta(minutes=2),
                at=self.cutoff,
            )
        )

        alert = self._alert()
        self.configuration.refresh_from_db()
        assert (taken, self.configuration.owner, alert.state, alert.firing_started_at) == (
            True,
            "platform",
            "firing",
            None,
        )

    def test_a_grouped_copy_taken_over_leaves_its_one_slot_to_the_first_group(self) -> None:
        legacy_id = uuid4()
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                legacy_configuration_id=legacy_id,
                grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=1).to_stored(),
            )
        take_ownership(
            PlatformOwnershipHandover(
                legacy_configuration_id=legacy_id,
                team_id=self.team.id,
                state=PlatformAlertState.NOT_FIRING,
                last_notified_at=None,
                consecutive_failures=0,
                next_check_at=self.cutoff - timedelta(minutes=1),
                at=self.cutoff - timedelta(minutes=5),
            )
        )

        self._record(
            groups=(GroupOutcome(grouping_key="api", kind=AlertEventKind.FIRING, new_state="firing", notified=True),)
        )

        with team_scope(self.team.id):
            instances = list(
                PlatformAlert.objects.filter(configuration=self.configuration).values_list("grouping_key", "state")
            )
        assert instances == [("api", "firing")]

    @parameterized.expand(
        [
            ("firing", {}, {"state": "firing"}, HandbackRefusal.FIRING),
            (
                "snoozed_inside_a_firing",
                {},
                {"state": "snoozed", "firing_started_at": datetime(2026, 9, 16, 9, tzinfo=UTC)},
                HandbackRefusal.FIRING,
            ),
            (
                "broken_is_never_due",
                {"next_check_at": datetime(2026, 9, 16, 9, tzinfo=UTC), "check_status": "broken"},
                {},
                None,
            ),
            (
                "disabled_while_a_check_runs",
                {"enabled": False, "next_check_at": datetime(2026, 9, 16, 9, tzinfo=UTC)},
                {},
                None,
            ),
            ("check_due", {"next_check_at": datetime(2026, 9, 16, 9, tzinfo=UTC)}, {}, HandbackRefusal.CHECK_DUE),
            (
                "calendar_schedule",
                {"recurrence_unit": "daily", "anchor_time": "09:00"},
                {},
                HandbackRefusal.NOT_PORTABLE,
            ),
            ("grouped", {}, {"grouping_key": "service=api"}, HandbackRefusal.NOT_PORTABLE),
            (
                "grouped_with_no_group_open",
                {"grouping": {"mode": "by_result_labels", "keys": ["service_name"]}},
                {},
                HandbackRefusal.NOT_PORTABLE,
            ),
        ]
    )
    def test_the_platform_keeps_an_alert_its_source_cannot_take_back(
        self,
        _name: str,
        configuration_fields: dict[str, Any],
        alert_fields: dict[str, Any],
        refusal: HandbackRefusal | None,
    ) -> None:
        legacy_id = uuid4()
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                **{
                    "legacy_configuration_id": legacy_id,
                    "owner": "platform",
                    "next_check_at": self.cutoff + timedelta(minutes=5),
                    **configuration_fields,
                }
            )
            PlatformAlert.objects.create(team=self.team, configuration=self.configuration, **alert_fields)

        handback = give_back_ownership(team_id=self.team.id, legacy_configuration_id=legacy_id, at=self.cutoff)

        assert (handback if isinstance(handback, HandbackRefusal) else None) == refusal
        self.configuration.refresh_from_db()
        assert self.configuration.owner == ("platform" if refusal else "source")
        if refusal is None:
            # A check that started before the handback finds the row no longer due and records nothing.
            assert self.configuration.next_check_at is not None and self.configuration.next_check_at > self.cutoff

    def test_a_disabling_outcome_stops_the_configuration_being_discovered(self) -> None:
        self._record(new_state="broken", notified=False, consecutive_failures=5, disable=True)

        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
        assert (self.configuration.enabled, self.configuration.check_status) == (False, "broken")
        assert due_checks(self.team.id, SourceKind.LOGS.value, self.slot, self.cutoff + timedelta(hours=1)) == ()

    def test_switching_a_source_off_leaves_the_alerts_the_platform_owns(self) -> None:
        with team_scope(self.team.id):
            owned = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="Cut over",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config=self.configuration.source_config,
                check_interval_minutes=10,
                owner=PlatformAlertOwner.PLATFORM,
            )

        assert disable_configurations(SourceKind.LOGS, team_id=self.team.id) == 1

        with team_scope(self.team.id):
            self.configuration.refresh_from_db()
            owned.refresh_from_db()
        assert (self.configuration.enabled, owned.enabled) == (False, True)

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
            source_detail={"breaches": ["above 10"]},
        )

        rows = sync_execute(
            """
            SELECT kind, previous_state, state, value, alert_name, muted_notification,
                   JSONExtractInt(condition_snapshot, 'threshold_count'), episode_started_at, source_kind,
                   JSONExtractArrayRaw(source_detail, 'breaches')
            FROM platform_alert_events
            WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s
            """,
            {"team_id": self.team.id, "configuration_id": str(self.configuration.id)},
        )

        # `insert_events` never raises, so without reading a row back a broken write is invisible.
        assert rows == [
            ("firing", "not_firing", "firing", 47.0, "API errors", "fire", 10, self.cutoff, "logs", ['"above 10"'])
        ]

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
        assert (check.instance("api").firing_started_at, check.instance("web").last_seen_at) == (
            self.cutoff,
            self.cutoff,
        )

    @parameterized.expand([("group_snooze", True), ("alert_snooze", False)])
    def test_a_snooze_set_while_a_check_runs_holds_what_the_check_announces(
        self, _name: str, group_snooze: bool
    ) -> None:
        self._record(
            groups=(
                GroupOutcome(
                    grouping_key="api",
                    kind=AlertEventKind.FIRING,
                    new_state="firing",
                    notified=True,
                    firing_episode=FiringEpisode(started_at=self.cutoff, ended=False),
                ),
                self._group("web"),
            )
        )
        due = self._next_due()
        # Straight to the rows, as the snooze lands after the check read them. An alert snooze set
        # this way stands for a source's copied snooze, which leaves the schedule where it was.
        with team_scope(self.team.id):
            if group_snooze:
                PlatformAlert.objects.filter(configuration=self.configuration).update(
                    snooze_until=due + timedelta(hours=1)
                )
            else:
                PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                    snooze_until=due + timedelta(hours=1)
                )

        self._record(
            at=due,
            groups=(
                GroupOutcome(
                    grouping_key="api",
                    kind=AlertEventKind.RESOLVED,
                    new_state="not_firing",
                    notified=True,
                    firing_episode=FiringEpisode(started_at=self.cutoff, ended=True),
                ),
                GroupOutcome(
                    grouping_key="web",
                    kind=AlertEventKind.FIRING,
                    new_state="firing",
                    notified=True,
                    firing_episode=FiringEpisode(started_at=due, ended=False),
                ),
            ),
        )

        evaluation_key = f"window:{due.isoformat()}"
        recorded = sync_execute(
            "SELECT grouping_key, kind, state, muted_notification FROM platform_alert_events "
            "WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s "
            "AND evaluation_key = %(evaluation_key)s ORDER BY grouping_key",
            {"team_id": self.team.id, "configuration_id": self.configuration.id, "evaluation_key": evaluation_key},
        )
        assert recorded == [("api", "check", "not_firing", "resolve"), ("web", "check", "firing", "fire")]
        assert announcement(self.team.id, str(self.configuration.id), evaluation_key, source=SourceKind.LOGS) is None
        api, web = self._alert("api"), self._alert("web")
        assert (api.state, api.firing_started_at, api.last_notified_at) == ("not_firing", None, self.cutoff)
        # A notification behind the firing's start is what makes the next unmuted check announce it.
        assert (web.state, web.firing_started_at, web.last_notified_at) == ("firing", due, None)

    def _group(self, key: str, *, state: str = "not_firing") -> GroupOutcome:
        return GroupOutcome(grouping_key=key, kind=AlertEventKind.CHECK, new_state=state, notified=False)

    def test_a_group_past_the_cap_gets_no_instance_and_no_history(self) -> None:
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=1).to_stored()
            )

        self._record(groups=(self._group("api"), self._group("web")), overflowed=2)

        with team_scope(self.team.id):
            keys = list(
                PlatformAlert.objects.filter(configuration=self.configuration).values_list("grouping_key", flat=True)
            )
            self.configuration.refresh_from_db()
        rows = sync_execute(
            "SELECT grouping_key FROM platform_alert_events WHERE team_id = %(team_id)s AND configuration_id = %(configuration_id)s",
            {"team_id": self.team.id, "configuration_id": self.configuration.id},
        )
        # The source turned away 2 groups, and the write turned away `web`.
        assert (keys, rows, self.configuration.overflowed_groups) == (["api"], [("api",)], 3)

    @parameterized.expand(
        [
            ("cleared_by_a_check_that_fits", {}, (0, False)),
            (
                "kept_by_a_failed_check",
                {
                    "groups": (),
                    "failure": CheckFailure(kind=AlertEventKind.ERRORED, new_state="errored", notified=False),
                    "consecutive_failures": 1,
                },
                (3, True),
            ),
            ("kept_by_a_skipped_check", {"groups": (), "skipped": True}, (3, True)),
        ]
    )
    def test_the_configuration_shows_the_overflow_of_the_last_check_that_ran(
        self, _name: str, next_check: dict[str, Any], expected: tuple[int, bool]
    ) -> None:
        def shown() -> tuple[int, bool]:
            with team_scope(self.team.id):
                view = get_configuration(
                    team_id=self.team.id, source_kinds=[SourceKind.LOGS.value], configuration_id=self.configuration.id
                )
            assert view is not None
            return view.overflowed_groups, view.overflow_is_lower_bound

        self._record(overflowed=3, overflow_is_lower_bound=True)
        assert shown() == (3, True)

        self._record(at=self._next_due(), **next_check)

        assert shown() == expected

    def test_an_instance_keeps_its_labels_when_a_check_returns_its_group_without_them(self) -> None:
        labelled = GroupOutcome(
            grouping_key="api",
            kind=AlertEventKind.CHECK,
            new_state="not_firing",
            notified=False,
            labels={"service_name": "api"},
        )
        self._record(groups=(labelled,))
        assert self._alert("api").labels == {"service_name": "api"}

        self._record(at=self._next_due(), groups=(self._group("api"),))

        assert self._alert("api").labels == {"service_name": "api"}

    @parameterized.expand([("nul", "\x00"), ("lone_surrogate", "\ud800")])
    def test_an_instance_stores_labels_the_database_cannot_hold_as_replacement_characters(
        self, _name: str, unstorable: str
    ) -> None:
        labels = bounded_labels({f"service{unstorable}name": f"api{unstorable}"})

        self._record(groups=(dataclasses.replace(self._group("api"), labels=labels),))

        assert self._alert("api").labels == {"service\ufffdname": "api\ufffd"}

    @parameterized.expand([("stale", ("severity_text",), []), ("current", ("service_name",), ["api", "web"])])
    def test_a_check_that_ran_under_another_grouping_records_no_groups(
        self, _name: str, stored_keys: tuple[str, ...], expected_keys: list[str]
    ) -> None:
        checked_under = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service_name",))
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(
                grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=stored_keys).to_stored()
            )

        self._record(groups=(self._group("api", state="firing"), self._group("web")), grouping=checked_under)

        with team_scope(self.team.id):
            keys = sorted(
                PlatformAlert.objects.filter(configuration=self.configuration).values_list("grouping_key", flat=True)
            )
            due = PlatformAlertConfiguration.objects.get(id=self.configuration.id).next_check_at
        assert keys == expected_keys
        assert due is not None and due > self.cutoff

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

    @parameterized.expand(
        [
            ("at_rest", {}, False),
            ("fired_since_the_check_read_it", {"state": "firing"}, True),
            ("snoozed_since_the_check_read_it", {"snoozed": True}, True),
            ("ungrouped", {"grouping": Grouping(max_instances=1)}, True),
        ]
    )
    def test_an_evicted_group_gives_up_its_slot_only_while_it_is_at_rest(
        self, _name: str, case: dict[str, Any], kept: bool
    ) -> None:
        grouping = case.get(
            "grouping", Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=1)
        )
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(id=self.configuration.id).update(grouping=grouping.to_stored())
            PlatformAlert.objects.create(
                team=self.team,
                configuration=self.configuration,
                grouping_key="old",
                state=case.get("state", "not_firing"),
                last_seen_at=self.cutoff - timedelta(hours=1),
                snooze_until=self.cutoff + timedelta(hours=1) if case.get("snoozed") else None,
            )

        self._record(groups=(self._group("new", state="firing"),), evicted=("old",))

        with team_scope(self.team.id):
            keys = set(
                PlatformAlert.objects.filter(configuration=self.configuration).values_list("grouping_key", flat=True)
            )
        assert keys == ({"old"} if kept else {"new"})

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

    @parameterized.expand([("one_schedule_group", "5:1:True", 1), ("no_schedule_group", None, 2)])
    def test_a_team_checks_share_a_slot_only_when_the_source_groups_them(
        self, _name: str, schedule_group: str | None, expected_slots: int
    ) -> None:
        # Ids 1 and 2 fall in different slots of a 5-minute cadence when the offset is per configuration.
        with team_scope(self.team.id):
            configurations = [
                PlatformAlertConfiguration.objects.create(
                    id=UUID(int=n),
                    team=self.team,
                    name=f"Alert {n}",
                    source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                    source_config={},
                    check_interval_minutes=5,
                    next_check_at=self.cutoff - timedelta(minutes=1),
                )
                for n in (1, 2)
            ]
        outcomes = [
            PlatformAlertOutcome(
                configuration_id=c.id,
                evaluation_key=f"window:{self.cutoff.isoformat()}",
                consecutive_failures=0,
                groups=(_group(""),),
                schedule_group=schedule_group,
            )
            for c in configurations
        ]
        record_outcomes(self.team.id, outcomes, self.cutoff)

        with team_scope(self.team.id):
            due = {
                c.next_check_at
                for c in PlatformAlertConfiguration.objects.filter(id__in=[c.id for c in configurations])
            }
        assert len(due) == expected_slots

    def _copy(self, legacy_id: UUID, *, revive: bool = False, **overrides: Any) -> None:
        upsert_configuration(dataclasses.replace(self._upsert(legacy_id), **overrides), revive=revive)

    def _upsert(self, legacy_id: UUID) -> PlatformAlertUpsert:
        return PlatformAlertUpsert(
            legacy_configuration_id=legacy_id,
            team_id=self.team.id,
            name="Copied alert",
            enabled=True,
            source_kind=SourceKind.LOGS,
            source_config={"condition": {"threshold_count": 1, "threshold_operator": "above", "window_minutes": 5}},
            check_interval_minutes=5,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            cooldown_minutes=0,
            schedule_restriction=None,
            next_check_at=self.cutoff - timedelta(minutes=1),
            snooze_until=None,
        )

    def _own(self, legacy_id: UUID) -> None:
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(legacy_configuration_id=legacy_id).update(
                owner=PlatformAlertOwner.PLATFORM
            )

    def _copies(self, *legacy_ids: UUID) -> dict[UUID, bool]:
        with team_scope(self.team.id):
            rows = PlatformAlertConfiguration.objects.filter(legacy_configuration_id__in=legacy_ids)
            return {row.legacy_configuration_id: row.enabled for row in rows if row.legacy_configuration_id}

    def test_a_cut_over_alert_comes_back_on_with_its_source(self) -> None:
        cut_over = uuid4()
        self._copy(cut_over)
        self._own(cut_over)
        # The parallel run is over, and the person then turned the alert off.
        disable_configurations(SourceKind.LOGS, team_id=self.team.id)
        self._copy(cut_over, enabled=False)

        upsert_if_running(self._upsert(cut_over), revive=True)

        assert self._copies(cut_over) == {cut_over: True}

    def test_a_cut_over_alert_does_not_reopen_a_switched_off_parallel_run(self) -> None:
        cut_over, parallel, created = uuid4(), uuid4(), uuid4()
        self._copy(cut_over)
        self._own(cut_over)
        self._copy(parallel)
        disable_configurations(SourceKind.LOGS, team_id=self.team.id)

        upsert_if_running(self._upsert(created), revive=True)

        assert self._copies(cut_over, parallel, created) == {cut_over: True, parallel: False}

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
    def test_a_second_copy_keeps_what_the_platform_owns_until_the_copy_comes_back_on(
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
        with team_scope(self.team.id):
            PlatformAlertConfiguration.objects.filter(legacy_configuration_id=legacy_id).update(consecutive_failures=3)
            copied = PlatformAlertConfiguration.objects.get(legacy_configuration_id=legacy_id)
            platform_testing.start_firing(copied.id, team_id=self.team.id, at=self.cutoff)
        if disabled_between:
            disable_configurations(SourceKind.LOGS, team_id=self.team.id)
        with time_machine.travel(self.cutoff, tick=False):
            self._copy(
                legacy_id,
                schedule_restriction=quiet_hours,
                next_check_at=self.cutoff + timedelta(minutes=34),
                check_interval_minutes=interval_on_rerun,
            )

        with team_scope(self.team.id):
            copied = PlatformAlertConfiguration.objects.get(legacy_configuration_id=legacy_id)
            alert = PlatformAlert.objects.get(configuration=copied)
        assert copied.next_check_at == self.cutoff + expected_offset
        # A copy that comes back on starts clean, as the source's own enable does.
        assert (alert.state, alert.firing_started_at, copied.consecutive_failures) == (
            ("not_firing", None, 0) if disabled_between else ("firing", self.cutoff, 3)
        )

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

    def test_a_source_turned_back_on_restarts_a_broken_copy_past_any_check_in_flight(self) -> None:
        legacy_id = uuid4()
        self._copy(legacy_id)
        with team_scope(self.team.id):
            copied = PlatformAlertConfiguration.objects.get(legacy_configuration_id=legacy_id)
            PlatformAlertConfiguration.objects.filter(id=copied.id).update(
                consecutive_failures=5, check_status="broken"
            )
            platform_testing.start_firing(copied.id, team_id=self.team.id, at=self.cutoff)

        with time_machine.travel(self.cutoff, tick=False):
            self._copy(legacy_id, revive=True)
        # A check that read the source as off before it came back on reports a stop.
        with self.captureOnCommitCallbacks(execute=True):
            recorded = record_outcomes(
                self.team.id,
                [
                    PlatformAlertOutcome(
                        configuration_id=copied.id,
                        evaluation_key="window:stale",
                        consecutive_failures=5,
                        disable=True,
                        groups=(
                            GroupOutcome(
                                grouping_key="", kind=AlertEventKind.CHECK, new_state="broken", notified=False
                            ),
                        ),
                    )
                ],
                self.cutoff,
            )

        assert recorded == 0
        with team_scope(self.team.id):
            copied = PlatformAlertConfiguration.objects.get(id=copied.id)
            alert = PlatformAlert.objects.get(configuration=copied)
        assert (copied.enabled, copied.consecutive_failures, copied.check_status, alert.state) == (
            True,
            0,
            "ok",
            "not_firing",
        )


def _group(grouping_key: str) -> GroupOutcome:
    return GroupOutcome(grouping_key=grouping_key, kind=AlertEventKind.CHECK, new_state="not_firing", notified=False)


_ADMITTED_AT = datetime(2026, 9, 16, 10, tzinfo=UTC)
_GROUPED = Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=3)


def _resting(key: str, *, seen_hours_ago: int = 1) -> InstanceCheckState:
    return InstanceCheckState(
        grouping_key=key, state="not_firing", last_seen_at=_ADMITTED_AT - timedelta(hours=seen_hours_ago)
    )


@pytest.mark.parametrize(
    "existing, returned, expected, grouping",
    [
        ((), ("a", "b", "c", "d"), GroupAdmission(admitted=frozenset({"a", "b", "c"}), overflowed=1), _GROUPED),
        (
            (_resting("x"),),
            ("x", "a", "a", "b"),
            GroupAdmission(admitted=frozenset({"x", "a", "b"}), overflowed=0),
            _GROUPED,
        ),
        # The least recently seen resting instance gives up its slot. "x" is older still, but this
        # check reports it, so it keeps its row.
        (
            (_resting("x", seen_hours_ago=3), _resting("y", seen_hours_ago=1), _resting("z", seen_hours_ago=2)),
            ("q", "x"),
            GroupAdmission(admitted=frozenset({"x", "q"}), overflowed=0, evicted=frozenset({"z"})),
            _GROUPED,
        ),
        (
            tuple(InstanceCheckState(grouping_key=key, state="firing") for key in ("x", "y", "z")),
            ("q", "x"),
            GroupAdmission(admitted=frozenset({"x"}), overflowed=1),
            _GROUPED,
        ),
        (
            (
                InstanceCheckState(grouping_key="x", state="firing"),
                InstanceCheckState(
                    grouping_key="y", state="not_firing", snooze_until=_ADMITTED_AT + timedelta(minutes=1)
                ),
                _resting("z"),
            ),
            ("q", "r"),
            GroupAdmission(admitted=frozenset({"q"}), overflowed=1, evicted=frozenset({"z"})),
            _GROUPED,
        ),
        (
            (InstanceCheckState(grouping_key="x", state="firing"), _resting("y"), _resting("z")),
            ("q",),
            GroupAdmission(admitted=frozenset({"q"}), overflowed=0, evicted=frozenset({"y", "z"})),
            Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=2),
        ),
        (
            (
                InstanceCheckState(grouping_key="x", state="firing"),
                InstanceCheckState(grouping_key="y", state="firing"),
                _resting("z"),
            ),
            ("q",),
            GroupAdmission(admitted=frozenset(), overflowed=1),
            Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=2),
        ),
        (
            (_resting(""),),
            ("other",),
            GroupAdmission(admitted=frozenset(), overflowed=1),
            Grouping(max_instances=1),
        ),
    ],
)
def test_a_check_admits_existing_groups_and_new_ones_up_to_the_cap(
    existing: tuple[InstanceCheckState, ...],
    returned: tuple[str, ...],
    expected: GroupAdmission,
    grouping: Grouping,
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
        instances=existing,
        grouping=grouping,
    )

    assert check.admit(returned, now=_ADMITTED_AT) == expected


@pytest.mark.parametrize(
    "fields",
    [
        {"mode": GroupingMode.SINGLE, "keys": ("service",)},
        {"mode": GroupingMode.BY_RESULT_LABELS, "keys": ()},
        {"mode": GroupingMode.BY_RESULT_LABELS, "keys": ("service", "service")},
        {"mode": GroupingMode.BY_RESULT_LABELS, "keys": ("service",), "max_instances": 0},
        {"mode": GroupingMode.BY_RESULT_LABELS, "keys": ("service",), "max_instances": MAX_INSTANCES_CEILING + 1},
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
        {"groups": (_group("api"),), "evicted": ("api",)},
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


def test_a_full_grouped_check_with_hostile_labels_fits_one_payload() -> None:
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
        grouping=Grouping(mode=GroupingMode.BY_RESULT_LABELS, keys=("service",), max_instances=MAX_INSTANCES_CEILING),
    )
    # Astral characters escape to 12 bytes each in a payload, the most a character can cost.
    hostile = "\U0001f600" * 32 * 1024
    observations = [
        GroupObservation(
            grouping_key=f"{index:03d}" + "\U0001f600" * 252,
            current_breached=True,
            value=1.0,
            labels={f"{name}{hostile}": hostile for name in range(10)},
        )
        for index in range(MAX_INSTANCES_CEILING)
    ]

    decision = decide_groups(
        check,
        observations,
        snapshot_of=lambda instance, prior: AlertSnapshot(
            state=AlertState(instance.state),
            cooldown=timedelta(0),
            last_notified_at=None,
            snooze_until=None,
            consecutive_failures=0,
        ),
        policy=LOGS_ALERT_POLICY,
        now=datetime(2026, 10, 15, tzinfo=UTC),
    )
    outcome = decision.as_outcome(
        configuration_id=check.id,
        evaluation_key="window:x",
        grouping=check.grouping,
        query_duration_ms=1,
        results_cut=False,
    )

    assert len(outcome.groups) == MAX_INSTANCES_CEILING
    assert payload_bytes(outcome) < MAX_BATCH_PAYLOAD_BYTES


@pytest.mark.parametrize(
    "kinds, incident_keys, failure, expected",
    [
        ((AlertEventKind.FIRING,), (), None, 1),
        ((AlertEventKind.FIRING,) * (MAX_TRANSITIONS_PER_DELIVERY + 1), (), None, 2),
        ((AlertEventKind.CHECK,) * (MAX_TRANSITIONS_PER_DELIVERY * 3), (), None, 1),
        ((AlertEventKind.CHECK,) * (MAX_TRANSITIONS_PER_DELIVERY + 1), ("0", "1", "2", "3", "4", "5"), None, 2),
        ((), (), CheckFailure(kind=AlertEventKind.ERRORED, new_state="errored", notified=True), 1),
    ],
)
def test_an_outcome_splits_its_delivery_by_the_transitions_it_announces(
    kinds: tuple[AlertEventKind, ...], incident_keys: tuple[str, ...], failure: CheckFailure | None, expected: int
) -> None:
    outcome = PlatformAlertOutcome(
        configuration_id=uuid4(),
        evaluation_key="window:x",
        consecutive_failures=0,
        groups=tuple(
            GroupOutcome(grouping_key=str(index), kind=kind, new_state="firing", notified=True)
            for index, kind in enumerate(kinds)
        ),
        failure=failure,
    )

    assert delivery_parts(outcome, incident_keys) == expected
