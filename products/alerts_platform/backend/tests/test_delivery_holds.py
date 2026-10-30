from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.alerts_platform.backend.facade.api import record_outcomes, release_hold, reschedule_hold
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    FiringEpisode,
    GroupOutcome,
    HeldDelivery,
    HeldDeliveryAddress,
    IncidentAction,
    PlatformAlertOutcome,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import HoldRelease, HoldReleasedBy
from products.alerts_platform.backend.facade.payload import MAX_BATCH_PAYLOAD_BYTES
from products.alerts_platform.backend.logic.delivery_holds import (
    HOLD_RETENTION,
    START_GRACE,
    HoldSweep,
    holds_to_send,
    prune_holds,
    record_delivery_started,
    send_swept,
)
from products.alerts_platform.backend.models import PlatformAlertConfiguration, PlatformAlertDeliveryHold

NOW = datetime(2026, 10, 20, 9, tzinfo=UTC)


class TestDeliveryHolds(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.configuration = self._configuration()

    def _configuration(self, *, enabled: bool = True) -> PlatformAlertConfiguration:
        return PlatformAlertConfiguration.objects.for_team(self.team.id).create(
            team=self.team,
            name="Signups",
            enabled=enabled,
            source_kind=PlatformAlertConfiguration.SourceKind.INSIGHT,
            check_interval_minutes=60,
            next_check_at=NOW - timedelta(minutes=1),
        )

    def _request(self, configuration: PlatformAlertConfiguration, key: str = "slot:1") -> AlertDeliveryRequest:
        return AlertDeliveryRequest(
            source=SourceKind.INSIGHT,
            team_id=self.team.id,
            configuration_id=str(configuration.id),
            evaluation_key=key,
            destination_alert_id="legacy-1",
            event_ids_by_kind={"firing": "$insight_alert_firing"},
            incident_actions={"": IncidentAction.TRIGGER},
            owned_by_platform=True,
        )

    def _address(self, configuration: PlatformAlertConfiguration, key: str = "slot:1") -> HeldDeliveryAddress:
        return HeldDeliveryAddress(team_id=self.team.id, configuration_id=str(configuration.id), evaluation_key=key)

    def _hold(
        self,
        configuration: PlatformAlertConfiguration,
        *,
        key: str = "slot:1",
        held_at: datetime = NOW,
        release_after: datetime = NOW,
        released_at: datetime | None = None,
    ) -> None:
        PlatformAlertDeliveryHold.objects.for_team(self.team.id).create(
            team=self.team,
            configuration=configuration,
            evaluation_key=key,
            reason="investigation",
            request=self._request(configuration, key).to_stored(),
            held_at=held_at,
            release_after=release_after,
            released_at=released_at,
            release_action=HoldRelease.SEND if released_at else None,
        )

    def test_a_held_check_records_its_hold_with_the_outcome_and_a_replay_adds_none(self) -> None:
        request = self._request(self.configuration)

        def outcome(reason: str) -> PlatformAlertOutcome:
            return PlatformAlertOutcome(
                configuration_id=self.configuration.id,
                evaluation_key="slot:1",
                consecutive_failures=0,
                groups=(
                    GroupOutcome(
                        grouping_key="",
                        kind=AlertEventKind.FIRING,
                        new_state="firing",
                        notified=True,
                        firing_episode=FiringEpisode(started_at=NOW, ended=False),
                    ),
                ),
                held_delivery=HeldDelivery(request=request, reason=reason, release_after_seconds=5400),
            )

        assert record_outcomes(self.team.id, [outcome("investigation")], NOW) == 1
        assert record_outcomes(self.team.id, [outcome("replayed")], NOW) == 0

        hold = PlatformAlertDeliveryHold.objects.for_team(self.team.id).get()
        assert (hold.reason, hold.release_after, hold.released_at) == (
            "investigation",
            NOW + timedelta(minutes=90),
            None,
        )
        assert AlertDeliveryRequest.from_stored(hold.request) == request

    @parameterized.expand(
        [
            ("the first send wins", [(HoldRelease.SEND, HoldReleasedBy.VERDICT, True)]),
            (
                "a retry of the winning send gets the request again",
                [(HoldRelease.SEND, HoldReleasedBy.VERDICT, True), (HoldRelease.SEND, HoldReleasedBy.VERDICT, True)],
            ),
            (
                "another releaser after the winner gets nothing",
                [
                    (HoldRelease.SEND, HoldReleasedBy.VERDICT, True),
                    (HoldRelease.SEND, HoldReleasedBy.SAFETY_NET, False),
                ],
            ),
            (
                "a suppress keeps a later send from going out",
                [
                    (HoldRelease.SUPPRESS, HoldReleasedBy.VERDICT, False),
                    (HoldRelease.SEND, HoldReleasedBy.SAFETY_NET, False),
                ],
            ),
        ]
    )
    def test_one_release_wins_and_only_its_send_returns_the_request(
        self, _name: str, releases: list[tuple[HoldRelease, HoldReleasedBy, bool]]
    ) -> None:
        self._hold(self.configuration)
        address = self._address(self.configuration)

        for action, released_by, returned in releases:
            request = release_hold(address, action=action, released_by=released_by, now=NOW)
            assert request == (self._request(self.configuration) if returned else None)

        hold = PlatformAlertDeliveryHold.objects.for_team(self.team.id).get()
        assert (hold.release_action, hold.released_by) == (releases[0][0], releases[0][1])
        assert reschedule_hold(address, release_after=NOW + timedelta(hours=1)) is False

    def test_the_safety_net_sends_expired_holds_and_released_sends_nobody_started(self) -> None:
        late = NOW - timedelta(minutes=1)
        self._hold(self.configuration, key="due", release_after=late)
        self._hold(self.configuration, key="rescheduled", release_after=late)
        self._hold(self.configuration, key="waiting", release_after=NOW + timedelta(minutes=1))
        self._hold(self.configuration, key="unstarted", release_after=late, released_at=NOW - START_GRACE)
        self._hold(self.configuration, key="starting", release_after=late, released_at=NOW - timedelta(minutes=1))
        self._hold(self.configuration, key="started", release_after=late, released_at=NOW - START_GRACE)
        record_delivery_started([self._address(self.configuration, "started")], NOW)
        disabled = self._configuration(enabled=False)
        self._hold(disabled, key="disabled", release_after=late)
        self._hold(self.configuration, key="old", held_at=NOW - HOLD_RETENTION - timedelta(days=1))
        assert prune_holds(NOW, limit=10) == 1

        sweep = holds_to_send(NOW, limit=10)
        # A source can move the deadline after the sweep found the hold, and must keep it held.
        assert reschedule_hold(
            self._address(self.configuration, "rescheduled"), release_after=NOW + timedelta(minutes=5)
        )
        swept = send_swept(sweep, NOW, max_bytes=MAX_BATCH_PAYLOAD_BYTES)
        requests = swept.requests

        assert requests == (self._request(self.configuration, "unstarted"), self._request(self.configuration, "due"))
        # Only the deadline release counts as a stalled source, not the recovered start.
        assert swept.expired == (self._request(self.configuration, "due"),)
        assert send_swept(sweep, NOW, max_bytes=MAX_BATCH_PAYLOAD_BYTES).expired == ()
        suppressed = PlatformAlertDeliveryHold.objects.for_team(self.team.id).get(configuration=disabled)
        assert (suppressed.release_action, suppressed.released_by) == (HoldRelease.SUPPRESS, HoldReleasedBy.SAFETY_NET)
        record_delivery_started([self._address(self.configuration, r.evaluation_key) for r in requests], NOW)
        assert holds_to_send(NOW, limit=10) == HoldSweep(expired=(), unstarted=())

    def test_one_sweep_sends_no_more_than_fits_one_payload(self) -> None:
        for key in ("first", "second"):
            self._hold(self.configuration, key=key, release_after=NOW - timedelta(minutes=1))

        swept = send_swept(holds_to_send(NOW, limit=10), NOW, max_bytes=1)

        assert len(swept.requests) == 1
        assert len(holds_to_send(NOW, limit=10).expired) == 1
