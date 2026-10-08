from datetime import UTC, datetime

import time_machine
from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.delivery.root_state import current_state_line
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration

EPISODE = datetime(2026, 10, 8, 14, 0, tzinfo=UTC)
LATER_EPISODE = datetime(2026, 10, 8, 16, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 8, 14, 32, tzinfo=UTC)


class TestRootStateLine(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team_id=self.team.id,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={},
                check_interval_minutes=1,
            )

    def _line(self) -> str | None:
        with time_machine.travel(NOW, tick=False):
            return current_state_line(
                team_id=self.team.id,
                configuration_id=str(self.configuration.id),
                grouping_key="",
                episode_started_at=EPISODE,
            )

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
        with team_scope(self.team.id):
            PlatformAlert.objects.create(
                team_id=self.team.id,
                configuration=self.configuration,
                grouping_key="",
                state=state,
                firing_started_at=firing_started_at,
            )

        assert self._line() == expected

    def test_a_group_with_no_recorded_state_leaves_the_root_alone(self) -> None:
        assert self._line() is None
