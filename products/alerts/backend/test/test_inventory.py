from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from posthog.models import Team

from products.alerts.backend.facade.contracts import SourceKind
from products.alerts.backend.logic.inventory import count_inventory
from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


class TestAlertInventory(BaseTest):
    def _configuration(self, team: Team, *, enabled: bool, states: list[tuple[str, datetime | None]]) -> None:
        configuration = PlatformAlertConfiguration.objects.unscoped().create(
            team=team,
            name="alert",
            enabled=enabled,
            source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
            threshold_count=1,
            threshold_operator="above",
            window_minutes=5,
            check_interval_minutes=5,
        )
        for index, (state, snooze_until) in enumerate(states):
            PlatformAlert.objects.unscoped().create(
                team=team,
                configuration=configuration,
                grouping_key=str(index),
                state=state,
                snooze_until=snooze_until,
            )

    def test_counts_every_team_split_by_state_and_mute_and_leaves_disabled_alerts_out(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        self._configuration(
            self.team,
            enabled=True,
            states=[("firing", None), ("firing", NOW + timedelta(hours=1)), ("not_firing", NOW - timedelta(hours=1))],
        )
        self._configuration(other_team, enabled=True, states=[("broken", None)])
        self._configuration(other_team, enabled=False, states=[("firing", None)])

        inventory = count_inventory(NOW)

        configurations = {(c.source, c.enabled): c.count for c in inventory.configurations if c.count}
        alerts = {(a.source, a.state, a.muted): a.count for a in inventory.alerts if a.count}
        assert configurations == {("logs", True): 2, ("logs", False): 1}
        assert alerts == {
            ("logs", "firing", False): 1,
            ("logs", "firing", True): 1,
            ("logs", "not_firing", False): 1,
            ("logs", "broken", False): 1,
        }
        assert len(inventory.alerts) == len(SourceKind) * len(PlatformAlert.State) * 2
