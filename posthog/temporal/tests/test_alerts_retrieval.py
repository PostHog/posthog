from datetime import UTC, datetime

import pytest
import time_machine
from unittest.mock import MagicMock, call, patch

from asgiref.sync import sync_to_async
from temporalio.common import MetricCounter, MetricMeter
from temporalio.testing import ActivityEnvironment

from posthog.schema import AlertCalculationInterval

from posthog.models import Team
from posthog.temporal.alerts.activities import _RetrievedAlerts, retrieve_due_alerts
from posthog.temporal.alerts.types import AlertInfo, ScheduleDueAlertChecksWorkflowInputs
from posthog.temporal.tests.test_alerts_activities import _create_alert


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("alerts_per_team", "max_alerts_per_run", "expected_team_order"),
    [
        pytest.param([3, 1], 4, [0, 1, 0, 0], id="unused-rounds-return-to-busy-team"),
        pytest.param([3, 3, 3], 5, [0, 1, 2, 0, 1], id="cap-truncates-a-rank-round"),
        pytest.param([4, 1, 1, 1], 4, [0, 1, 2, 3], id="each-team-gets-first-rank-before-second"),
        pytest.param([1, 1, 1], 2, [0, 1], id="cap-smaller-than-due-team-count"),
    ],
)
async def test_retrieve_due_alerts_uses_team_rank_rounds(
    ateam: Team,
    alerts_per_team: list[int],
    max_alerts_per_run: int,
    expected_team_order: list[int],
) -> None:
    teams = [ateam]
    for team_index in range(1, len(alerts_per_team)):
        teams.append(
            await sync_to_async(Team.objects.create)(
                organization_id=ateam.organization_id,
                project_id=ateam.project_id,
                name=f"Team {team_index}",
            )
        )

    for team, alert_count in zip(teams, alerts_per_team, strict=True):
        for _ in range(alert_count):
            await _create_alert(team)

    alerts = await ActivityEnvironment().run(
        retrieve_due_alerts,
        ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=max_alerts_per_run),
    )

    team_index_by_id = {team.id: index for index, team in enumerate(teams)}
    assert [team_index_by_id[alert.team_id] for alert in alerts] == expected_team_order


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_retrieve_due_alerts_excludes_future_checks_and_applies_the_documented_order_within_each_team(
    ateam: Team,
) -> None:
    alert_specs = [
        # These high-priority intervals would lead the result if due filtering regressed.
        ("future_real_time", AlertCalculationInterval.REAL_TIME, datetime(2026, 9, 10, 12, 1, tzinfo=UTC)),
        ("future_15_minutes", AlertCalculationInterval.EVERY_15_MINUTES, datetime(2026, 9, 10, 12, 15, tzinfo=UTC)),
        ("fresh_daily_tie_lower_id", AlertCalculationInterval.DAILY, datetime(2026, 9, 10, 11, 47, tzinfo=UTC)),
        ("fresh_hourly", AlertCalculationInterval.HOURLY, datetime(2026, 9, 10, 11, 46, tzinfo=UTC)),
        ("aged_real_time", AlertCalculationInterval.REAL_TIME, datetime(2026, 9, 10, 11, 40, tzinfo=UTC)),
        ("fresh_daily_earlier", AlertCalculationInterval.DAILY, datetime(2026, 9, 10, 11, 46, tzinfo=UTC)),
        ("never_checked", AlertCalculationInterval.DAILY, None),
        ("fresh_real_time", AlertCalculationInterval.REAL_TIME, datetime(2026, 9, 10, 11, 59, tzinfo=UTC)),
        ("aged_daily_oldest", AlertCalculationInterval.DAILY, datetime(2026, 9, 10, 11, 30, tzinfo=UTC)),
        ("fresh_15_minutes", AlertCalculationInterval.EVERY_15_MINUTES, datetime(2026, 9, 10, 11, 58, tzinfo=UTC)),
        ("fresh_daily_tie_higher_id", AlertCalculationInterval.DAILY, datetime(2026, 9, 10, 11, 47, tzinfo=UTC)),
    ]
    alert_label_by_id: dict[str, str] = {}
    for label, calculation_interval, next_check_at in alert_specs:
        alert = await _create_alert(
            ateam,
            calculation_interval=calculation_interval.value,
            next_check_at=next_check_at,
        )
        alert_label_by_id[str(alert.id)] = label

    with time_machine.travel("2026-09-10T12:00:00Z", tick=False):
        alerts = await ActivityEnvironment().run(
            retrieve_due_alerts,
            ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=len(alert_specs)),
        )

    assert [alert_label_by_id[alert.alert_id] for alert in alerts] == [
        "aged_real_time",
        "fresh_real_time",
        "fresh_15_minutes",
        "fresh_hourly",
        "never_checked",
        "aged_daily_oldest",
        "fresh_daily_earlier",
        "fresh_daily_tie_lower_id",
        "fresh_daily_tie_higher_id",
    ]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_retrieve_due_alerts_reselects_the_same_oldest_due_alerts_until_checks_advance(ateam: Team) -> None:
    due_alerts = [
        await _create_alert(
            ateam,
            next_check_at=datetime(2026, 9, 10, 11, minute, tzinfo=UTC),
        )
        for minute in range(3)
    ]
    inputs = ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=2)

    with time_machine.travel("2026-09-10T12:00:00Z", tick=False):
        first_sweep = await ActivityEnvironment().run(retrieve_due_alerts, inputs)
        second_sweep = await ActivityEnvironment().run(retrieve_due_alerts, inputs)

    oldest_due_alert_ids = [str(alert.id) for alert in due_alerts[:2]]
    first_sweep_ids = [alert.alert_id for alert in first_sweep]
    second_sweep_ids = [alert.alert_id for alert in second_sweep]

    assert first_sweep_ids == oldest_due_alert_ids
    # Retrieval does not advance next_check_at, so the next sweep sees the same oldest cohort as due.
    assert second_sweep_ids == first_sweep_ids


@pytest.mark.asyncio
async def test_retrieve_due_alerts_records_capacity_and_selected_alert_counters() -> None:
    meter = MagicMock(spec=MetricMeter)
    capacity_counter = MagicMock(spec=MetricCounter)
    selected_counter = MagicMock(spec=MetricCounter)
    counters = {
        "insight_alert_scheduler_capacity": capacity_counter,
        "insight_alert_scheduler_alerts_selected": selected_counter,
    }
    meter.create_counter.side_effect = lambda name, description: counters[name]
    environment = ActivityEnvironment()
    polled_at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    async def fake_get_alerts() -> _RetrievedAlerts:
        return _RetrievedAlerts(alerts=[MagicMock()] * 9, due_count=42, oldest_due_at=None, polled_at=polled_at)

    with (
        patch(
            "posthog.temporal.alerts.activities.database_sync_to_async",
            return_value=MagicMock(return_value=fake_get_alerts),
        ),
        patch("posthog.temporal.alerts.activities.record_due_insight_alert_metrics"),
        patch("posthog.temporal.alerts.activities.get_metric_meter", return_value=meter),
    ):
        for max_alerts_per_run in (11, 10, 9):
            await environment.run(
                retrieve_due_alerts,
                ScheduleDueAlertChecksWorkflowInputs(max_alerts_per_run=max_alerts_per_run),
            )

    expected_counter_names = [
        "insight_alert_scheduler_capacity",
        "insight_alert_scheduler_alerts_selected",
    ] * 3
    created_counter_names = [metric_call.args[0] for metric_call in meter.create_counter.call_args_list]
    assert created_counter_names == expected_counter_names
    assert capacity_counter.add.call_args_list == [call(11), call(10), call(9)]
    assert selected_counter.add.call_args_list == [call(9), call(9), call(9)]
    meter.with_additional_attributes.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_metrics", ["due_alerts", "scheduler_counters"])
async def test_retrieve_due_alerts_succeeds_when_metric_recording_fails(failing_metrics: str) -> None:
    expected_alerts: list[AlertInfo] = [MagicMock()]
    polled_at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    async def fake_get_alerts() -> _RetrievedAlerts:
        return _RetrievedAlerts(alerts=expected_alerts, due_count=1, oldest_due_at=None, polled_at=polled_at)

    record_due_metrics = MagicMock()
    get_metric_meter = MagicMock(return_value=MagicMock(spec=MetricMeter))
    if failing_metrics == "due_alerts":
        record_due_metrics.side_effect = RuntimeError("due alert metrics backend unavailable")
    else:
        get_metric_meter.side_effect = RuntimeError("scheduler metrics backend unavailable")

    with (
        patch(
            "posthog.temporal.alerts.activities.database_sync_to_async",
            return_value=MagicMock(return_value=fake_get_alerts),
        ),
        patch("posthog.temporal.alerts.activities.record_due_insight_alert_metrics", new=record_due_metrics),
        patch("posthog.temporal.alerts.activities.get_metric_meter", new=get_metric_meter),
    ):
        alerts = await ActivityEnvironment().run(retrieve_due_alerts)

    assert alerts == expected_alerts
    record_due_metrics.assert_called_once_with(1, None, polled_at)
    get_metric_meter.assert_called_once_with()
