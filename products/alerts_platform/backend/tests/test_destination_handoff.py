from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.delivery import (
    destinations as destinations_registry,
    evaluation,
    handoff,
)
from products.alerts_platform.backend.delivery.handoff import deliver_handoff
from products.alerts_platform.backend.delivery.thread_store import ThreadBusy
from products.alerts_platform.backend.delivery.transport import DeliveryError
from products.alerts_platform.backend.facade import api as platform_api
from products.alerts_platform.backend.facade.contracts import (
    ROUTING_FLAG,
    AlertDeliveryRequest,
    AlertDestinationData,
    AlertEventKind,
    AlertRouteEdit,
    DestinationType,
    IncidentAction,
    NativeAlertLifecycle,
    NewAlertDestination,
    RouteMatcher,
    SourceConfigSpec,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.logic import alert_routing, destination_handoff, platform_writes
from products.alerts_platform.backend.logic.platform_alert_events import insert_events
from products.alerts_platform.backend.logic.platform_lifecycle import event_row
from products.alerts_platform.backend.models import (
    AlertReceiver,
    AlertRoute,
    PlatformAlert,
    PlatformAlertConfiguration,
    PlatformAlertDeliveryHold,
)
from products.alerts_platform.backend.temporal import web_start
from products.alerts_platform.backend.tests.test_delivery_evaluation import PagingTransport, RecordingTransport
from products.alerts_platform.backend.tests.test_native_alerts import _edit, _WatchedRows

FIRING_STARTED = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)

_TYPES: dict[str, DestinationType] = {
    "pagerduty": DestinationType.PAGERDUTY,
    "incident_io": DestinationType.INCIDENT_IO,
    "slack": DestinationType.SLACK,
}


class IncidentIoTransport(RecordingTransport):
    provider = "incident_io"

    def channel_target(self, target: AlertDestinationData) -> str:
        return str(target.get("incident_io_alert_source_config_id", ""))


def _start_inline(requests: list[AlertDeliveryRequest]) -> list[AlertDeliveryRequest]:
    for request in requests:
        web_start.hand_over_inline(request)
    return []


def _start_into(started: list[AlertDeliveryRequest]) -> Callable[[list[AlertDeliveryRequest]], list[Any]]:
    def start(requests: list[AlertDeliveryRequest]) -> list[Any]:
        started.extend(requests)
        return []

    return start


def _data(kind: str, address: str) -> AlertDestinationData:
    if kind == "pagerduty":
        return cast(AlertDestinationData, {"type": DestinationType.PAGERDUTY, "pagerduty_routing_key": address})
    if kind == "incident_io":
        return cast(
            AlertDestinationData,
            {
                "type": DestinationType.INCIDENT_IO,
                "incident_io_alert_source_config_id": address,
                "incident_io_secret": "test-secret",
            },
        )
    return cast(
        AlertDestinationData, {"type": DestinationType.SLACK, "slack_workspace_id": 1, "slack_channel_id": address}
    )


class TestDestinationHandoff(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        RecordingTransport.sends = []
        spec = SourceConfigSpec(
            model=_WatchedRows,
            validate=lambda edit: None,
            check_in_team=MagicMock(),
            incident_event_ids={
                IncidentAction.TRIGGER: "$x_alert_incident_opened",
                IncidentAction.RESOLVE: "$x_alert_incident_closed",
            },
            native=NativeAlertLifecycle(
                check_interval_minutes=5, platform_destinations=False, remove_destinations=MagicMock()
            ),
        )
        for patcher in (
            patch("products.alerts_platform.backend.logic.source_configs.spec", return_value=spec),
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: key == ROUTING_FLAG,
            ),
            patch.dict(
                evaluation._TRANSPORTS,
                {
                    DestinationType.SLACK: RecordingTransport,
                    DestinationType.PAGERDUTY: PagingTransport,
                    DestinationType.INCIDENT_IO: IncidentIoTransport,
                },
            ),
            # The workflow runs the same two sends, so the test runs them inline.
            patch.object(web_start, "start_hand_overs", side_effect=_start_inline),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        with team_scope(self.team.id):
            self.configuration_id = platform_writes.create_configuration(
                team_id=self.team.id, source_kind=SourceKind.LOGS, edit=_edit(), created_by_id=self.user.id
            ).id
            PlatformAlertConfiguration.objects.filter(id=self.configuration_id).update(labels={"team": "infra"})
            configuration = PlatformAlertConfiguration.objects.get(id=self.configuration_id)
            alert, _ = PlatformAlert.objects.update_or_create(
                team=self.team,
                configuration=configuration,
                grouping_key="",
                defaults={"state": PlatformAlertState.FIRING, "firing_started_at": FIRING_STARTED},
            )
        insert_events(
            self.team.id,
            [
                event_row(
                    configuration,
                    alert=alert,
                    evaluation_key="opening-check",
                    kind=AlertEventKind.FIRING.value,
                    previous_state=PlatformAlertState.NOT_FIRING.value,
                    state=PlatformAlertState.FIRING.value,
                    episode_started_at=FIRING_STARTED,
                    consecutive_failures=0,
                    now=FIRING_STARTED,
                )
            ],
        )

    def _receiver(self, kind: str, address: str, team_label: str | None) -> AlertReceiver:
        receiver = AlertReceiver.objects.for_team(self.team.id).create(
            team=self.team, name=address, type=_TYPES[kind], config=_data(kind, address)
        )
        if team_label is not None:
            AlertRoute.objects.for_team(self.team.id).create(
                team=self.team,
                receiver=receiver,
                matchers=[{"label": "team", "op": "=", "value": team_label}],
                event_kinds=["firing", "resolved"],
            )
        return receiver

    def _fire(self, grouping_key: str, labels: dict[str, str]) -> None:
        configuration = PlatformAlertConfiguration.objects.for_team(self.team.id).get(id=self.configuration_id)
        alert = PlatformAlert.objects.for_team(self.team.id).create(
            team=self.team,
            configuration=configuration,
            grouping_key=grouping_key,
            labels=labels,
            state=PlatformAlertState.FIRING,
            firing_started_at=FIRING_STARTED,
        )
        insert_events(
            self.team.id,
            [
                event_row(
                    configuration,
                    alert=alert,
                    evaluation_key="opening-check",
                    kind=AlertEventKind.FIRING.value,
                    previous_state=PlatformAlertState.NOT_FIRING.value,
                    state=PlatformAlertState.FIRING.value,
                    episode_started_at=FIRING_STARTED,
                    consecutive_failures=0,
                    now=FIRING_STARTED,
                )
            ],
        )

    def _sends(self) -> list[tuple[str, IncidentAction | None, AlertEventKind]]:
        return sorted(
            (
                (channel, message.incident_action, message.transition.kind)
                for channel, message in RecordingTransport.sends
            ),
            key=str,
        )

    def _route_edit(self, kind: str) -> None:
        old = self._receiver(kind, "old", "infra")
        new = self._receiver(kind, "new", None)
        route = AlertRoute.objects.for_team(self.team.id).get(receiver=old)
        alert_routing.update_route(team_id=self.team.id, route_id=route.id, edit=AlertRouteEdit(receiver_id=new.id))

    def _receiver_delete(self, kind: str) -> None:
        old = self._receiver(kind, "old", "infra")
        alert_routing.delete_receiver(team_id=self.team.id, receiver_id=old.id)

    def _label_edit(self, kind: str) -> None:
        self._receiver(kind, "old", "infra")
        self._receiver(kind, "new", "billing")
        with team_scope(self.team.id):
            platform_writes.update_configuration(
                team_id=self.team.id,
                source_kinds=[SourceKind.LOGS.value],
                configuration_id=self.configuration_id,
                change=lambda current: replace(current, labels={"team": "billing"}),
            )

    def _destination_add(self, kind: str) -> None:
        platform_api.create_alert_destinations(
            team_id=self.team.id,
            configuration_id=self.configuration_id,
            destinations=[NewAlertDestination(data=_data(kind, "new"), event_kinds=(AlertEventKind.FIRING,))],
        )

    def _live_copy_add(self, kind: str) -> None:
        self.enterContext(
            patch.object(destinations_registry, "_live_lookup", lambda **kwargs: frozenset(kwargs["hog_function_ids"]))
        )
        platform_api.create_alert_destinations(
            team_id=self.team.id,
            configuration_id=self.configuration_id,
            destinations=[
                NewAlertDestination(
                    data=_data(kind, "new"), event_kinds=(AlertEventKind.FIRING,), legacy_hog_function_ids=(uuid4(),)
                )
            ],
        )

    _FIRING = AlertEventKind.FIRING
    _TRIGGER_NEW = ("new", IncidentAction.TRIGGER, _FIRING)
    _RESOLVE_OLD = ("old", IncidentAction.RESOLVE, _FIRING)

    @parameterized.expand(
        [
            ("route_edit_pagerduty", "_route_edit", "pagerduty", [_TRIGGER_NEW, _RESOLVE_OLD]),
            ("receiver_delete_pagerduty", "_receiver_delete", "pagerduty", [_RESOLVE_OLD]),
            ("label_edit_pagerduty", "_label_edit", "pagerduty", [_TRIGGER_NEW, _RESOLVE_OLD]),
            ("label_edit_incident_io", "_label_edit", "incident_io", [_TRIGGER_NEW, _RESOLVE_OLD]),
            ("destination_add_pagerduty", "_destination_add", "pagerduty", [_TRIGGER_NEW]),
            # The HogFunction the row copies keeps paging, so the row is not paged as well.
            ("live_copy_add_pagerduty", "_live_copy_add", "pagerduty", []),
            # A message destination keeps no incident, so a move sends it nothing.
            ("label_edit_slack", "_label_edit", "slack", []),
        ]
    )
    def test_an_edit_mid_firing_hands_the_firing_over(
        self, _name: str, edit: str, kind: str, expected: list[tuple[str, Any, AlertEventKind]]
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            cast(Callable[[str], None], getattr(self, edit))(kind)

        assert self._sends() == sorted(expected, key=str)

    def test_a_firing_that_ended_before_the_edit_is_not_handed_over(self) -> None:
        PlatformAlert.objects.for_team(self.team.id).update(state=PlatformAlertState.NOT_FIRING, firing_started_at=None)

        with self.captureOnCommitCallbacks(execute=True):
            self._route_edit("pagerduty")

        assert self._sends() == []

    def test_a_handoff_a_later_edit_undid_does_not_undo_that_edit(self) -> None:
        started: list[AlertDeliveryRequest] = []
        with patch.object(web_start, "start_hand_overs", side_effect=_start_into(started)):
            with self.captureOnCommitCallbacks(execute=True):
                self._route_edit("pagerduty")
            old = AlertReceiver.objects.for_team(self.team.id).get(name="old")
            route = AlertRoute.objects.for_team(self.team.id).get()
            with self.captureOnCommitCallbacks(execute=True):
                alert_routing.update_route(
                    team_id=self.team.id, route_id=route.id, edit=AlertRouteEdit(receiver_id=old.id)
                )

        # Each edit's resolve went out when it committed. The first edit's trigger runs last, after the
        # firing is back where it started, and would open an incident on the new destination for good.
        for request in reversed(started):
            web_start.hand_over_inline(request)

        assert self._sends() == sorted(
            [
                ("old", IncidentAction.RESOLVE, AlertEventKind.FIRING),
                ("new", IncidentAction.RESOLVE, AlertEventKind.FIRING),
                ("old", IncidentAction.TRIGGER, AlertEventKind.FIRING),
            ],
            key=str,
        )

    def test_a_destination_gained_while_the_opening_trigger_is_held_is_not_paged(self) -> None:
        PlatformAlertDeliveryHold.objects.for_team(self.team.id).create(
            team=self.team,
            configuration_id=self.configuration_id,
            evaluation_key="opening-check",
            reason="investigation",
            request={},
            held_at=FIRING_STARTED,
            release_after=FIRING_STARTED,
        )

        with self.captureOnCommitCallbacks(execute=True):
            self._destination_add("pagerduty")

        assert self._sends() == []

    def test_a_receiver_deleted_before_its_handoff_runs_still_gets_its_resolve(self) -> None:
        started: list[AlertDeliveryRequest] = []
        with patch.object(web_start, "start_hand_overs", side_effect=_start_into(started)):
            with self.captureOnCommitCallbacks(execute=True):
                self._route_edit("pagerduty")
            with self.captureOnCommitCallbacks(execute=True):
                alert_routing.delete_receiver(
                    team_id=self.team.id, receiver_id=AlertReceiver.objects.for_team(self.team.id).get(name="old").id
                )
        for request in started:
            web_start.hand_over_inline(request)

        assert self._sends() == sorted([self._RESOLVE_OLD, self._TRIGGER_NEW], key=str)

    def test_an_unreadable_routing_flag_retries_a_routed_trigger(self) -> None:
        started: list[AlertDeliveryRequest] = []
        with patch.object(web_start, "start_hand_overs", side_effect=_start_into(started)):
            with self.captureOnCommitCallbacks(execute=True):
                self._route_edit("pagerduty")
        RecordingTransport.sends = []

        with (
            patch(
                "products.alerts_platform.backend.delivery.team_flags.posthoganalytics.feature_enabled",
                return_value=None,
            ),
            pytest.raises(DeliveryError),
        ):
            deliver_handoff(started[0])

        assert self._sends() == []

    def test_a_route_on_a_group_label_hands_over_only_the_groups_it_matches(self) -> None:
        PlatformAlert.objects.for_team(self.team.id).filter(grouping_key="").update(labels={"service": "api"})
        self._fire("web", {"service": "web"})
        receiver = self._receiver("pagerduty", "new", None)

        with self.captureOnCommitCallbacks(execute=True):
            alert_routing.create_route(
                team_id=self.team.id,
                edit=AlertRouteEdit(receiver_id=receiver.id, matchers=(RouteMatcher(label="service", value="api"),)),
            )

        assert [
            (message.transition.grouping_key, message.incident_action) for _, message in RecordingTransport.sends
        ] == [("", IncidentAction.TRIGGER)]

    @parameterized.expand(
        [
            # Its row is still there, so the workflow reads it by id and the resolve still goes out.
            ("receiver_still_there", "_route_edit", [_TRIGGER_NEW, _RESOLVE_OLD]),
            # Its row is gone and the edit's inline budget is spent, so nothing can send its resolve.
            ("receiver_deleted", "_receiver_delete", []),
        ]
    )
    def test_resolves_past_the_inline_budget(self, _name: str, edit: str, expected: list[Any]) -> None:
        with (
            patch.object(destination_handoff, "MAX_INLINE_SENDS_PER_EDIT", 0),
            self.captureOnCommitCallbacks(execute=True),
        ):
            cast(Callable[[str], None], getattr(self, edit))("pagerduty")

        assert self._sends() == sorted(expected, key=str)

    def test_an_inline_resolve_that_fails_is_retried_through_the_workflow(self) -> None:
        real_send = handoff.send_handoff
        failed: list[bool] = []

        def held_once(request: AlertDeliveryRequest, targets: Any) -> int:
            if not failed and not any(send.gained for send in request.handoff):
                failed.append(True)
                raise ThreadBusy("held by the opening trigger")
            return real_send(request, targets)

        with (
            patch.object(handoff, "send_handoff", side_effect=held_once),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self._route_edit("pagerduty")

        assert failed == [True]
        assert self._sends() == sorted([self._TRIGGER_NEW, self._RESOLVE_OLD], key=str)

    def test_a_snapshot_reads_the_same_number_of_queries_however_many_alerts_fire(self) -> None:
        self._receiver("pagerduty", "old", "infra")

        def queries() -> int:
            with CaptureQueriesContext(connection) as captured:
                destination_handoff.snapshot(self.team.id, routes_only=True)
            return len(captured.captured_queries)

        one = queries()
        for _ in range(2):
            with team_scope(self.team.id):
                configuration_id = platform_writes.create_configuration(
                    team_id=self.team.id, source_kind=SourceKind.LOGS, edit=_edit(), created_by_id=self.user.id
                ).id
                PlatformAlertConfiguration.objects.filter(id=configuration_id).update(labels={"team": "infra"})
                PlatformAlert.objects.update_or_create(
                    team=self.team,
                    configuration_id=configuration_id,
                    grouping_key="",
                    defaults={"state": PlatformAlertState.FIRING, "firing_started_at": FIRING_STARTED},
                )

        assert queries() == one

    def test_each_part_of_a_handoff_gets_its_own_workflow(self) -> None:
        self._fire("web", {})
        started: list[AlertDeliveryRequest] = []
        with (
            patch.object(destination_handoff, "MAX_SENDS_PER_HANDOFF", 1),
            patch.object(web_start, "start_hand_overs", side_effect=_start_into(started)),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self._destination_add("pagerduty")

        assert [len(request.handoff) for request in started] == [1, 1]
        assert len({request.evaluation_key for request in started}) == 2

    def test_handoffs_temporal_cannot_start_send_inline_only_within_the_edit_budget(self) -> None:
        self._fire("web", {})
        with (
            patch.object(destination_handoff, "MAX_INLINE_SENDS_PER_EDIT", 1),
            patch.object(web_start, "start_hand_overs", side_effect=list),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self._destination_add("pagerduty")

        assert self._sends() == [self._TRIGGER_NEW]

    def test_an_edit_reads_the_same_number_of_queries_however_many_groups_it_moves(self) -> None:
        def queries() -> int:
            receiver = self._receiver("pagerduty", "old", "infra")
            before = destination_handoff.snapshot(self.team.id, routes_only=True)
            receiver.delete()
            with CaptureQueriesContext(connection) as captured, self.captureOnCommitCallbacks():
                destination_handoff.hand_over_after_commit(before)
            return len(captured.captured_queries)

        one = queries()
        for key in ("web", "worker"):
            self._fire(key, {})

        assert queries() == one
