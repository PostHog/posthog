from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.contracts import AlertEventKind
from products.alerts_platform.backend.logic.platform_alert_events import (
    PlatformAlertEventRow,
    history,
    insert_events,
    last_checks,
    notable_checks,
)
from products.alerts_platform.backend.models import PlatformAlertConfiguration

CHECKED = datetime(2026, 1, 1, 12, tzinfo=UTC)


class TestGroupedHistory(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="Errors per service",
                source_kind=PlatformAlertConfiguration.SourceKind.TRACES,
                source_config={},
                check_interval_minutes=1,
            )
        # One group of a grouped alert fires. Its row has a grouping key, as every grouped check does.
        insert_events(
            self.team.id,
            [
                PlatformAlertEventRow(
                    team_id=self.team.id,
                    source_kind="traces",
                    configuration_id=self.configuration.id,
                    alert_id=uuid4(),
                    grouping_key='{"service_name":"checkout"}',
                    evaluation_key="eval-1",
                    kind=AlertEventKind.FIRING,
                    alert_name="Errors per service",
                    previous_state="not_firing",
                    state="firing",
                    episode_started_at=CHECKED,
                    value=0.2,
                    labels={"service_name": "checkout"},
                    condition_snapshot={"measure": "error_rate"},
                    source_config_snapshot={},
                    query_duration_ms=12,
                    error_message="",
                    consecutive_failures=0,
                    muted_notification="",
                    occurred_at=CHECKED,
                )
            ],
        )

    @parameterized.expand([("every group", True, 1), ("the ungrouped instance only", False, 0)])
    def test_grouped_checks_are_read_only_when_asked_for(self, _name: str, all_groups: bool, expected: int) -> None:
        ids = [self.configuration.id]
        window = {"since": CHECKED - timedelta(hours=1), "until": CHECKED + timedelta(hours=1)}

        changes = history(self.team.id, ids, **window, all_groups=all_groups).get(self.configuration.id)
        last = last_checks(self.team.id, ids, all_groups=all_groups)
        events = notable_checks(
            self.team.id, self.configuration.id, since=window["since"], limit=10, all_groups=all_groups
        )

        assert (
            len(changes.state_changes) if changes else 0,
            len(last),
            len(events.events),
        ) == (expected, expected, expected)
