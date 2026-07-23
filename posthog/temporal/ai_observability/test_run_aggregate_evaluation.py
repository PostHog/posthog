import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, Team
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.evaluation_workflow_activities import RunEvaluationInputs
from posthog.temporal.ai_observability.run_aggregate_evaluation import (
    CheckTraceSettledInputs,
    RunAggregateEvaluationInputs,
    RunAggregateEvaluationWorkflow,
    check_trace_settled_activity,
    resolve_settle_plan,
)
from posthog.temporal.ai_observability.run_trace_evaluation import (
    EmitTraceEvaluationEventInputs,
    ExecuteTraceEvaluationInputs,
)


@pytest.fixture
def setup_data():
    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=organization, name="Test Team")
    return {"organization": organization, "team": team}


def _insert_ai_event(*, team: Team, event: str, trace_id: str, arrival: datetime) -> None:
    """Insert a minimal ai_events row with `_timestamp` (arrival) set independently of
    `timestamp` — the settle-poll activity judges liveness on `_timestamp`, not `timestamp`.

    `bulk_create_ai_events` (posthog/models/ai_events/test_util.py) can't do this: it derives
    `_timestamp` from the same `timestamp` value it inserts, so tests that need to simulate
    ingestion lag write directly against the columns AI_EVENTS_TABLE_BASE_SQL leaves without
    a default.
    """
    sync_execute(
        """
        INSERT INTO sharded_ai_events (
            uuid, event, timestamp, team_id, distinct_id, person_id, properties,
            trace_id, is_error, _timestamp, _offset, _partition
        ) VALUES (
            %(uuid)s, %(event)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(person_id)s, %(properties)s,
            %(trace_id)s, 0, %(_timestamp)s, 0, 0
        )
        """,
        {
            "uuid": str(uuid.uuid4()),
            "event": event,
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "team_id": team.id,
            "distinct_id": "test-user",
            "person_id": str(uuid.uuid4()),
            "properties": "{}",
            "trace_id": trace_id,
            "_timestamp": arrival.strftime("%Y-%m-%d %H:%M:%S"),
        },
        flush=False,
    )


class TestResolveSettlePlan:
    @pytest.mark.parametrize(
        "settle,expected",
        [
            (None, ("fixed_window", 1800, 1800)),
            ({}, ("fixed_window", 1800, 1800)),
            ({"strategy": "fixed_window", "window_seconds": 60}, ("fixed_window", 60, 60)),
            # Legacy sub-floor values are bumped to the floor (the old workflow only re-clamped the max).
            ({"window_seconds": 0}, ("fixed_window", 10, 10)),
            ({"window_seconds": 99999}, ("fixed_window", 7200, 7200)),
            ({"strategy": "inactivity"}, ("inactivity", 300, 7200)),
            (
                {"strategy": "inactivity", "quiet_period_seconds": 120, "max_age_seconds": 600},
                ("inactivity", 120, 600),
            ),
            # Sub-floor and above-ceiling quiet_period_seconds are clamped the same way as window_seconds.
            ({"strategy": "inactivity", "quiet_period_seconds": 5}, ("inactivity", 10, 7200)),
            ({"strategy": "inactivity", "quiet_period_seconds": 5000}, ("inactivity", 1800, 7200)),
            # max_age below quiet period is coerced up so the loop's min() can't fire before one quiet period.
            (
                {"strategy": "inactivity", "quiet_period_seconds": 600, "max_age_seconds": 60},
                ("inactivity", 600, 600),
            ),
            ({"strategy": "bogus", "window_seconds": 60}, ("fixed_window", 60, 60)),
        ],
    )
    def test_resolves_and_clamps(self, settle, expected):
        assert resolve_settle_plan(settle) == expected


def _mock_activities(calls: list[str]) -> list[Any]:
    @activity.defn(name="fetch_evaluation_activity")
    async def mock_fetch_evaluation(inputs: RunEvaluationInputs) -> dict[str, Any]:
        calls.append("fetch")
        return {
            "id": inputs.evaluation_id,
            "name": "Hog eval",
            "evaluation_type": "hog",
            "evaluation_config": {},
            "output_type": "boolean",
            "output_config": {},
            "team_id": 1,
            "enabled": True,
            "deleted": False,
        }

    @activity.defn(name="execute_trace_hog_eval_activity")
    async def mock_execute_trace_hog(inputs: ExecuteTraceEvaluationInputs) -> EvaluationActivityResult:
        calls.append("execute")
        return {"result_type": "boolean", "verdict": True, "reasoning": "ok", "allows_na": False}

    @activity.defn(name="emit_trace_evaluation_event_activity")
    async def mock_emit(inputs: EmitTraceEvaluationEventInputs) -> None:
        calls.append("emit")

    @activity.defn(name="emit_internal_telemetry_activity")
    async def mock_telemetry(inputs: Any) -> None:
        calls.append("telemetry")

    return [mock_fetch_evaluation, mock_execute_trace_hog, mock_emit, mock_telemetry]


def _workflow_inputs(settle: dict[str, Any]) -> RunAggregateEvaluationInputs:
    return RunAggregateEvaluationInputs(
        evaluation_id=str(uuid.uuid4()),
        team_id=1,
        trace_id="trace-123",
        distinct_id="user-1",
        session_id=None,
        settle=settle,
    )


class TestRunAggregateEvaluationWorkflow:
    @pytest.mark.asyncio
    async def test_fixed_window_sleeps_then_evaluates(self):
        calls: list[str] = []
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=_mock_activities(calls),
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                start = await env.get_current_time()
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "fixed_window", "window_seconds": 600}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    start_signal="activity-seen",
                    start_signal_args=[{"event_uuid": "first-generation"}],
                )
                await env.sleep(200)
                await handle.signal("activity-seen", {"event_uuid": "mid-window"})
                result = await handle.result()
                elapsed = (await env.get_current_time()) - start
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        assert result["verdict"] is True
        # fixed_window ignores both the start-time and mid-window signals: window stays [600, 900).
        assert elapsed >= timedelta(seconds=600)
        assert elapsed < timedelta(seconds=900)

    @pytest.mark.asyncio
    async def test_inactivity_settles_after_one_quiet_period_when_silent(self):
        calls: list[str] = []
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=_mock_activities(calls),
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                start = await env.get_current_time()
                await env.client.execute_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 7200}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    start_signal="activity-seen",
                    start_signal_args=[{"event_uuid": "first-generation"}],
                )
                elapsed = (await env.get_current_time()) - start
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        assert elapsed >= timedelta(seconds=300)
        assert elapsed < timedelta(seconds=600)

    @pytest.mark.asyncio
    async def test_inactivity_signal_rearms_quiet_period(self):
        calls: list[str] = []
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=_mock_activities(calls),
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                start = await env.get_current_time()
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 7200}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    start_signal="activity-seen",
                    start_signal_args=[{"event_uuid": "first-generation"}],
                )
                await env.sleep(120)
                await handle.signal("activity-seen", {"event_uuid": "later-generation"})
                await handle.result()
                elapsed = (await env.get_current_time()) - start
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        # Signal at ~120s re-arms the 300s quiet timer: settles at ~420s, not 300s.
        assert elapsed >= timedelta(seconds=420)
        assert elapsed < timedelta(seconds=720)

    @pytest.mark.asyncio
    async def test_inactivity_max_age_caps_a_chatty_trace(self):
        calls: list[str] = []
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=_mock_activities(calls),
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                start = await env.get_current_time()
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 400}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    start_signal="activity-seen",
                    start_signal_args=[{"event_uuid": "first-generation"}],
                )
                await env.sleep(250)
                await handle.signal("activity-seen", {"event_uuid": "still-going"})
                await handle.result()
                elapsed = (await env.get_current_time()) - start
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        # Signal at ~250s would re-arm to ~550s, but max_age 400s wins.
        assert elapsed >= timedelta(seconds=400)
        assert elapsed < timedelta(seconds=550)


class TestCheckTraceSettledActivity:
    @pytest.mark.django_db(transaction=True)
    def test_settled_when_quiet_beyond_margin(self, setup_data):
        team = setup_data["team"]
        _insert_ai_event(
            team=team, event="$ai_generation", trace_id="t-settled", arrival=datetime.now(UTC) - timedelta(seconds=60)
        )
        result = check_trace_settled_activity(
            CheckTraceSettledInputs(team_id=team.id, trace_id="t-settled", quiet_period_seconds=30)
        )
        assert result is not None

    @pytest.mark.django_db(transaction=True)
    def test_not_settled_when_recent_activity(self, setup_data):
        team = setup_data["team"]
        _insert_ai_event(
            team=team, event="$ai_generation", trace_id="t-live", arrival=datetime.now(UTC) - timedelta(seconds=5)
        )
        with pytest.raises(ApplicationError) as err:
            check_trace_settled_activity(
                CheckTraceSettledInputs(team_id=team.id, trace_id="t-live", quiet_period_seconds=30)
            )
        assert err.value.type == "trace_not_settled"

    @pytest.mark.django_db(transaction=True)
    def test_null_visibility_is_not_settled(self, setup_data):
        team = setup_data["team"]
        with pytest.raises(ApplicationError) as err:
            check_trace_settled_activity(
                CheckTraceSettledInputs(team_id=team.id, trace_id="t-missing", quiet_period_seconds=30)
            )
        assert err.value.type == "trace_not_settled"

    @pytest.mark.django_db(transaction=True)
    def test_annotation_events_do_not_defer_settling(self, setup_data):
        team = setup_data["team"]
        _insert_ai_event(
            team=team, event="$ai_generation", trace_id="t-annot", arrival=datetime.now(UTC) - timedelta(seconds=120)
        )
        _insert_ai_event(
            team=team, event="$ai_evaluation", trace_id="t-annot", arrival=datetime.now(UTC) - timedelta(seconds=2)
        )
        assert (
            check_trace_settled_activity(
                CheckTraceSettledInputs(team_id=team.id, trace_id="t-annot", quiet_period_seconds=30)
            )
            is not None
        )
