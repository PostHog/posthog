import uuid
from datetime import UTC, datetime

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.delivery.root_state import state_line
from products.alerts_platform.backend.facade.contracts import PlatformAlertSnapshot
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.logic.platform_reads import alert_snapshot
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration

EPISODE = datetime(2026, 10, 8, 14, 0, tzinfo=UTC)
LATER_EPISODE = datetime(2026, 10, 8, 16, 0, tzinfo=UTC)
AS_OF = datetime(2026, 10, 8, 14, 32, tzinfo=UTC)


def _snapshot(state: PlatformAlertState, firing_started_at: datetime | None) -> PlatformAlertSnapshot:
    return PlatformAlertSnapshot(
        id=uuid.uuid4(),
        grouping_key="",
        state=state,
        firing_started_at=firing_started_at,
        last_notified_at=None,
        snooze_until=None,
    )


class TestRootStateLine(SimpleTestCase):
    @parameterized.expand(
        [
            ("this_firing_continues", PlatformAlertState.FIRING, EPISODE, "\U0001f534 Still firing as of 14:32 UTC"),
            ("resolved", PlatformAlertState.NOT_FIRING, None, "\U0001f7e2 Resolved as of 14:32 UTC"),
            ("a_later_firing", PlatformAlertState.FIRING, LATER_EPISODE, "\U0001f7e2 Resolved as of 14:32 UTC"),
            ("errored", PlatformAlertState.ERRORED, EPISODE, None),
            ("snoozed", PlatformAlertState.SNOOZED, EPISODE, None),
        ]
    )
    def test_the_line_follows_the_recorded_state_of_this_firing(
        self, _name: str, state: PlatformAlertState, firing_started_at: datetime | None, expected: str | None
    ) -> None:
        line = state_line(_snapshot(state, firing_started_at), episode_started_at=EPISODE, as_of=AS_OF)

        assert line == expected

    def test_a_group_with_no_recorded_state_leaves_the_root_alone(self) -> None:
        assert state_line(None, episode_started_at=EPISODE, as_of=AS_OF) is None


class TestAlertSnapshot(APIBaseTest):
    def test_it_reads_the_named_group_of_this_team_only(self) -> None:
        with team_scope(self.team.id):
            configuration = PlatformAlertConfiguration.objects.create(
                team_id=self.team.id,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={},
                check_interval_minutes=1,
            )
            for grouping_key, state in (
                ("checkout", PlatformAlertState.FIRING),
                ("search", PlatformAlertState.NOT_FIRING),
            ):
                PlatformAlert.objects.create(
                    team_id=self.team.id, configuration=configuration, grouping_key=grouping_key, state=state
                )

        snapshot = alert_snapshot(self.team.id, str(configuration.id), "checkout")

        assert snapshot is not None
        assert snapshot.state == PlatformAlertState.FIRING
        other_team = Team.objects.create(organization=self.organization, name="Other")
        assert alert_snapshot(other_team.id, str(configuration.id), "checkout") is None
