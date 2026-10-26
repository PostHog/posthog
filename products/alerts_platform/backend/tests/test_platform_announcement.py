from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.contracts import AlertEventKind, SourceKind
from products.alerts_platform.backend.logic.platform_alert_events import (
    _INSERT_SQL,
    PlatformAlertEventRow,
    announcement,
    insert_events,
)
from products.alerts_platform.backend.models import PlatformAlertConfiguration

OCCURRED = datetime(2026, 9, 30, 10, tzinfo=UTC)
FIRING = datetime(2026, 9, 30, 9, tzinfo=UTC)


class TestAnnouncement(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={},
                check_interval_minutes=10,
            )

    def _row(self, **overrides) -> PlatformAlertEventRow:
        fields = {
            "team_id": self.team.id,
            "source_kind": "logs",
            "configuration_id": self.configuration.id,
            "alert_id": self.configuration.id,
            "grouping_key": "",
            "evaluation_key": "eval-1",
            "kind": AlertEventKind.FIRING,
            "alert_name": "API errors",
            "previous_state": "not_firing",
            "state": "firing",
            "episode_started_at": FIRING,
            "value": 300.0,
            "labels": {},
            "condition_snapshot": {"threshold_count": 10, "threshold_operator": "above"},
            "source_config_snapshot": {"service_names": ["checkout"]},
            "query_duration_ms": 12,
            "error_message": "",
            "consecutive_failures": 0,
            "muted_notification": "",
            "occurred_at": OCCURRED,
        }
        fields.update(overrides)
        return PlatformAlertEventRow(**fields)

    def _announcement(self, evaluation_key: str = "eval-1"):
        return announcement(self.team.id, str(self.configuration.id), evaluation_key, source=SourceKind.LOGS)

    def test_a_recorded_firing_comes_back_as_the_message_it_should_send(self) -> None:
        module = "products.alerts_platform.backend.logic.platform_alert_events"
        with patch(f"{module}.sync_execute", wraps=sync_execute) as executed:
            insert_events(self.team.id, [self._row(source_detail={"breaches": ["above 10"]})])
            result = self._announcement()

        # As `default`, the history write and read share that user's per-user concurrency limit
        # with every other caller, and a rejected insert loses the row.
        assert executed.call_args_list
        assert all(call.kwargs.get("ch_user") == ClickHouseUser.ALERTS_PLATFORM for call in executed.call_args_list)

        assert result is not None
        assert result.configuration_id == str(self.configuration.id)
        assert result.alert_name == "API errors"
        assert [t.kind for t in result.transitions] == [AlertEventKind.FIRING]
        transition = result.transitions[0]
        assert transition.episode_started_at == FIRING
        assert transition.occurred_at == OCCURRED
        assert transition.value == 300.0
        # The snapshots are what let a message state what its own check measured, however long
        # after the check it is rendered.
        assert transition.condition["threshold_count"] == 10
        assert transition.source_config["service_names"] == ["checkout"]
        assert transition.source_detail == {"breaches": ["above 10"]}

    def test_a_check_that_announced_nothing_reaches_no_destination(self) -> None:
        insert_events(self.team.id, [self._row(kind=AlertEventKind.CHECK)])

        assert self._announcement() is None

    def test_a_held_check_comes_back_only_for_a_group_whose_firing_moved(self) -> None:
        insert_events(
            self.team.id,
            [
                self._row(grouping_key="checkout", kind=AlertEventKind.CHECK),
                self._row(grouping_key="search", kind=AlertEventKind.CHECK),
            ],
        )

        result = announcement(
            self.team.id,
            str(self.configuration.id),
            "eval-1",
            source=SourceKind.LOGS,
            incident_grouping_keys=["checkout"],
        )

        assert result is not None
        assert [(t.grouping_key, t.kind) for t in result.transitions] == [("checkout", AlertEventKind.CHECK)]

    def test_every_group_that_announced_gets_its_own_transition(self) -> None:
        insert_events(
            self.team.id,
            [self._row(grouping_key="checkout"), self._row(grouping_key="search", kind=AlertEventKind.RESOLVED)],
        )

        result = self._announcement()

        assert result is not None
        assert {(t.grouping_key, t.kind) for t in result.transitions} == {
            ("checkout", AlertEventKind.FIRING),
            ("search", AlertEventKind.RESOLVED),
        }

    def test_a_group_written_twice_announces_once_from_the_newer_row(self) -> None:
        insert_events(self.team.id, [self._row()])
        # Under its own token the engine drops this, which is what the token is for. The window
        # it remembers tokens for is bounded, so a late enough retry does land a second row, and
        # announcing both would send the same alert twice.
        sync_execute(
            _INSERT_SQL,
            [self._row(kind=AlertEventKind.RESOLVED, occurred_at=OCCURRED + timedelta(minutes=1)).as_row()],
            # Unique per run: ClickHouse remembers tokens between them, so a fixed one would
            # make the second run of this test insert nothing.
            settings={"insert_deduplication_token": str(uuid4())},
            team_id=self.team.id,
        )

        result = self._announcement()

        assert result is not None
        assert [t.kind for t in result.transitions] == [AlertEventKind.RESOLVED]

    def test_another_evaluation_of_the_same_alert_is_not_mixed_in(self) -> None:
        insert_events(self.team.id, [self._row()])
        insert_events(self.team.id, [self._row(evaluation_key="eval-2", kind=AlertEventKind.RESOLVED)])

        result = self._announcement("eval-1")

        assert result is not None
        assert [t.kind for t in result.transitions] == [AlertEventKind.FIRING]

    def test_the_parts_of_a_split_delivery_read_each_group_once(self) -> None:
        keys = [f"service-{index}" for index in range(7)]
        insert_events(
            self.team.id,
            [self._row(grouping_key=key) for key in reversed(keys)]
            + [self._row(grouping_key="quiet", kind=AlertEventKind.CHECK)],
        )

        by_part = []
        for part in range(3):
            result = announcement(
                self.team.id, str(self.configuration.id), "eval-1", source=SourceKind.LOGS, part=part, parts=3
            )
            assert result is not None
            by_part.append([t.grouping_key for t in result.transitions])

        assert sorted(key for keys_in_part in by_part for key in keys_in_part) == keys
        assert [len(keys_in_part) for keys_in_part in by_part] == [3, 2, 2]
