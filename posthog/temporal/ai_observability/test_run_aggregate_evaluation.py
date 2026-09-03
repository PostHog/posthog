import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, Team
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.evaluation_workflow_activities import RunEvaluationInputs
from posthog.temporal.ai_observability.run_aggregate_evaluation import (
    MAX_SETTLE_POLLS_PER_RUN,
    CheckSessionSettledInputs,
    CheckTraceSettledInputs,
    RunAggregateEvaluationInputs,
    RunAggregateEvaluationWorkflow,
    SettlePlan,
    check_session_settled_activity,
    check_trace_settled_activity,
    resolve_poll_interval,
    resolve_settle_plan,
)
from posthog.temporal.ai_observability.run_session_evaluation import ExecuteSessionEvaluationInputs
from posthog.temporal.ai_observability.run_trace_evaluation import (
    EmitTraceEvaluationEventInputs,
    ExecuteTraceEvaluationInputs,
)


@pytest.fixture
def setup_data():
    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=organization, name="Test Team")
    return {"organization": organization, "team": team}


def _insert_ai_event(
    *,
    team: Team,
    event: str,
    trace_id: str,
    arrival: datetime,
    event_timestamp: datetime | None = None,
    session_id: str | None = None,
) -> None:
    """Insert a minimal ai_events row with `_timestamp` (arrival) set independently of
    `timestamp` — the settle-poll activity judges liveness on `_timestamp`, not `timestamp`.

    `event_timestamp` controls the client-set `timestamp` column; it defaults to "now" so
    callers that don't care about it get the old behavior of a fresh, unremarkable event.

    `bulk_create_ai_events` (posthog/models/ai_events/test_util.py) can't do this: it derives
    `_timestamp` from the same `timestamp` value it inserts, so tests that need to simulate
    ingestion lag write directly against the columns AI_EVENTS_TABLE_BASE_SQL leaves without
    a default.

    `retention_days` is pinned the same way `bulk_create_ai_events` pins it. ai_events is
    `TTL drop_date` with `drop_date = toDate(timestamp) + retention_days`, and TTL runs on the
    server's real clock while these rows carry a frozen `timestamp` — on the column default of 30
    days, a fixture row silently expires once the frozen date falls more than 30 days behind today
    and the poll finds nothing.
    """
    sync_execute(
        """
        INSERT INTO sharded_ai_events (
            uuid, event, timestamp, team_id, distinct_id, person_id, properties,
            trace_id, session_id, is_error, retention_days, _timestamp, _offset, _partition
        ) VALUES (
            %(uuid)s, %(event)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(person_id)s, %(properties)s,
            %(trace_id)s, %(session_id)s, 0, %(retention_days)s, %(_timestamp)s, 0, 0
        )
        """,
        {
            "uuid": str(uuid.uuid4()),
            "event": event,
            "timestamp": (event_timestamp or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "team_id": team.id,
            "distinct_id": "test-user",
            "person_id": str(uuid.uuid4()),
            "properties": "{}",
            "trace_id": trace_id,
            "session_id": session_id,
            "retention_days": 10000,
            "_timestamp": arrival.strftime("%Y-%m-%d %H:%M:%S"),
        },
        flush=False,
    )


class TestResolveSettlePlan:
    @pytest.mark.parametrize(
        "settle,expected",
        [
            (None, SettlePlan(strategy="fixed_window", primary_seconds=1800, max_age_seconds=1800)),
            ({}, SettlePlan(strategy="fixed_window", primary_seconds=1800, max_age_seconds=1800)),
            (
                {"strategy": "fixed_window", "window_seconds": 60},
                SettlePlan(strategy="fixed_window", primary_seconds=60, max_age_seconds=60),
            ),
            # Legacy sub-floor values are bumped to the floor (the old workflow only re-clamped the max).
            ({"window_seconds": 0}, SettlePlan(strategy="fixed_window", primary_seconds=10, max_age_seconds=10)),
            (
                {"window_seconds": 99999},
                SettlePlan(strategy="fixed_window", primary_seconds=7200, max_age_seconds=7200),
            ),
            ({"strategy": "inactivity"}, SettlePlan(strategy="inactivity", primary_seconds=300, max_age_seconds=7200)),
            (
                {"strategy": "inactivity", "quiet_period_seconds": 120, "max_age_seconds": 600},
                SettlePlan(strategy="inactivity", primary_seconds=120, max_age_seconds=600),
            ),
            # Sub-floor and above-ceiling quiet_period_seconds are clamped the same way as window_seconds.
            (
                {"strategy": "inactivity", "quiet_period_seconds": 5},
                SettlePlan(strategy="inactivity", primary_seconds=10, max_age_seconds=7200),
            ),
            (
                {"strategy": "inactivity", "quiet_period_seconds": 5000},
                SettlePlan(strategy="inactivity", primary_seconds=1800, max_age_seconds=7200),
            ),
            # max_age below quiet period is coerced up so the loop's min() can't fire before one quiet period.
            (
                {"strategy": "inactivity", "quiet_period_seconds": 600, "max_age_seconds": 60},
                SettlePlan(strategy="inactivity", primary_seconds=600, max_age_seconds=600),
            ),
            (
                {"strategy": "bogus", "window_seconds": 60},
                SettlePlan(strategy="fixed_window", primary_seconds=60, max_age_seconds=60),
            ),
        ],
    )
    def test_resolves_and_clamps(self, settle, expected):
        assert resolve_settle_plan(settle) == expected

    @pytest.mark.parametrize(
        "settle,expected",
        [
            # Absent strategy resolves to the session default, not the trace default.
            (None, SettlePlan(strategy="inactivity", primary_seconds=3600, max_age_seconds=86400)),
            ({}, SettlePlan(strategy="inactivity", primary_seconds=3600, max_age_seconds=86400)),
            # Session-sized values survive; the trace ceilings would have crushed these to 1800/7200.
            (
                {"strategy": "inactivity", "quiet_period_seconds": 86400, "max_age_seconds": 604800},
                SettlePlan(strategy="inactivity", primary_seconds=86400, max_age_seconds=604800),
            ),
            (
                {"strategy": "inactivity", "quiet_period_seconds": 3600},
                SettlePlan(strategy="inactivity", primary_seconds=3600, max_age_seconds=86400),
            ),
            # Session ceilings still clamp above their own bounds.
            (
                {"strategy": "inactivity", "quiet_period_seconds": 999999},
                SettlePlan(strategy="inactivity", primary_seconds=86400, max_age_seconds=86400),
            ),
            (
                {"strategy": "inactivity", "max_age_seconds": 9999999},
                SettlePlan(strategy="inactivity", primary_seconds=3600, max_age_seconds=604800),
            ),
            (
                {"strategy": "fixed_window", "window_seconds": 604800},
                SettlePlan(strategy="fixed_window", primary_seconds=604800, max_age_seconds=604800),
            ),
            (
                {"strategy": "fixed_window", "window_seconds": 9999999},
                SettlePlan(strategy="fixed_window", primary_seconds=604800, max_age_seconds=604800),
            ),
        ],
    )
    def test_resolves_and_clamps_for_session_target(self, settle, expected):
        assert resolve_settle_plan(settle, "session") == expected


class TestResolvePollInterval:
    @pytest.mark.parametrize(
        "primary_seconds,poll_budget_seconds,expected",
        [
            # Session defaults: a quarter of the quiet period, unchanged by the budget floor.
            (3600, 82785, 900),
            # The corner the floor exists for — quiet=10s with a 7-day max age. A quarter of the
            # quiet period alone would be 10s, i.e. ~60k polls for one (evaluation, session).
            (10, 604775, 605),
            # Every in-bounds trace config must keep its old interval so in-flight trace runs
            # replay with an unchanged retry policy. These are the trace extremes.
            (10, 7175, 10),
            (300, 6885, 75),
            (1800, 5385, 450),
        ],
    )
    def test_floors_the_cadence_on_the_budget_as_well_as_the_quiet_period(
        self, primary_seconds, poll_budget_seconds, expected
    ):
        assert resolve_poll_interval(primary_seconds, poll_budget_seconds) == expected

    def test_no_config_can_exceed_the_poll_ceiling(self):
        for primary_seconds, poll_budget_seconds in [(10, 604775), (60, 604740), (10, 7175)]:
            interval = resolve_poll_interval(primary_seconds, poll_budget_seconds)
            assert poll_budget_seconds // interval <= MAX_SETTLE_POLLS_PER_RUN


def _mock_activities(calls: list[str], exclude: set[str] | None = None) -> list[Any]:
    exclude = exclude or set()

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

    @activity.defn(name="check_session_settled_activity")
    async def mock_check_session_settled(inputs: CheckSessionSettledInputs) -> str:
        calls.append("check_session_settled")
        return "2026-07-23T00:00:00+00:00"

    @activity.defn(name="execute_session_hog_eval_activity")
    async def mock_execute_session_hog(inputs: ExecuteSessionEvaluationInputs) -> EvaluationActivityResult:
        calls.append("execute_session")
        return {"result_type": "boolean", "verdict": True, "reasoning": "ok", "allows_na": False}

    @activity.defn(name="execute_session_llm_judge_activity")
    async def mock_execute_session_judge(inputs: ExecuteSessionEvaluationInputs) -> EvaluationActivityResult:
        calls.append("execute_session")
        return {"result_type": "boolean", "verdict": True, "reasoning": "ok", "allows_na": False}

    all_activities = {
        "fetch_evaluation_activity": mock_fetch_evaluation,
        "execute_trace_hog_eval_activity": mock_execute_trace_hog,
        "emit_trace_evaluation_event_activity": mock_emit,
        "emit_internal_telemetry_activity": mock_telemetry,
        "check_session_settled_activity": mock_check_session_settled,
        "execute_session_hog_eval_activity": mock_execute_session_hog,
        "execute_session_llm_judge_activity": mock_execute_session_judge,
    }
    return [fn for name, fn in all_activities.items() if name not in exclude]


def _workflow_inputs(settle: dict[str, Any], **overrides: Any) -> RunAggregateEvaluationInputs:
    defaults: dict[str, Any] = {
        "evaluation_id": str(uuid.uuid4()),
        "team_id": 1,
        "trace_id": "trace-123",
        "distinct_id": "user-1",
        "session_id": None,
        "settle": settle,
    }
    defaults.update(overrides)
    return RunAggregateEvaluationInputs(**defaults)


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
                result = await env.client.execute_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "fixed_window", "window_seconds": 600}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
                elapsed = (await env.get_current_time()) - start
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        assert result["verdict"] is True
        assert elapsed >= timedelta(seconds=600)
        assert elapsed < timedelta(seconds=900)

    @pytest.mark.asyncio
    async def test_inactivity_settles_after_one_quiet_period_when_silent(self):
        calls: list[str] = []

        @activity.defn(name="check_trace_settled_activity")
        async def mock_settles_immediately(inputs: CheckTraceSettledInputs) -> str:
            return "2026-07-23T00:00:00+00:00"

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=[*_mock_activities(calls), mock_settles_immediately],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 7200}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
                await handle.result()
                # env.get_current_time() after an execute_activity call with a schedule-to-close
                # timeout can skew forward to that timeout even once the activity has already
                # succeeded; the server-recorded execution window doesn't have that problem.
                description = await handle.describe()
                assert description.start_time is not None and description.close_time is not None
                elapsed = description.close_time - description.start_time
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        assert elapsed >= timedelta(seconds=300)
        assert elapsed < timedelta(seconds=600)

    @pytest.mark.asyncio
    async def test_inactivity_settles_after_failed_polls(self):
        calls: list[str] = []
        poll_attempts = {"n": 0}

        @activity.defn(name="check_trace_settled_activity")
        async def mock_check_settled(inputs: CheckTraceSettledInputs) -> str:
            poll_attempts["n"] += 1
            if poll_attempts["n"] <= 2:
                raise ApplicationError("still active", type="trace_not_settled")
            return "2026-07-23T00:00:00+00:00"

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=[*_mock_activities(calls), mock_check_settled],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 7200}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
                result = await handle.result()
                # env.get_current_time() after a retried activity leaves a stale schedule-to-close
                # timer that skews a second read; the server-recorded execution window doesn't.
                description = await handle.describe()
                assert description.start_time is not None and description.close_time is not None
                elapsed = description.close_time - description.start_time
        assert poll_attempts["n"] == 3
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        assert result["verdict"] is True
        # quiet sleep (300) + two retry intervals (2 x 75); generous upper bound for task latency
        assert elapsed >= timedelta(seconds=450)
        assert elapsed < timedelta(seconds=750)

    @pytest.mark.asyncio
    async def test_inactivity_max_age_cap_evaluates_despite_never_settling(self):
        calls: list[str] = []

        @activity.defn(name="check_trace_settled_activity")
        async def mock_never_settled(inputs: CheckTraceSettledInputs) -> str:
            raise ApplicationError("still active", type="trace_not_settled")

        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=[*_mock_activities(calls), mock_never_settled],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 600}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
                result = await handle.result()
                description = await handle.describe()
                assert description.start_time is not None and description.close_time is not None
                elapsed = description.close_time - description.start_time
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        assert result["verdict"] is True
        # The trace never settles, so we wait out the full max-age window (600) before grading,
        # rather than giving up early once the next poll would overrun the budget.
        assert elapsed >= timedelta(seconds=600)
        assert elapsed < timedelta(seconds=750)

    @pytest.mark.asyncio
    async def test_session_target_polls_the_session_activity_and_evaluates(self):
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
                result = await env.client.execute_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs(
                        {"strategy": "inactivity", "quiet_period_seconds": 3600, "max_age_seconds": 86400},
                        target="session",
                        ai_session_id="session-abc",
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
        assert "check_session_settled" in calls
        assert "check_trace_settled" not in calls
        assert "execute_session" in calls
        assert "execute" not in calls, "the trace execute activity must not run for a session target"
        assert result["verdict"] is True

    @pytest.mark.asyncio
    async def test_session_still_active_at_max_age_grades_what_it_has(self):
        """Guards the _is_still_not_settled error-type set: a hardcoded `trace_not_settled` match
        would let this re-raise and fail the run instead of grading a partial session."""
        calls: list[str] = []
        task_queue = str(uuid.uuid4())

        @activity.defn(name="check_session_settled_activity")
        async def never_settles(inputs: CheckSessionSettledInputs) -> str:
            calls.append("check_session_settled")
            raise ApplicationError("session active 1s ago", type="session_not_settled")

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=[*_mock_activities(calls, exclude={"check_session_settled_activity"}), never_settles],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs(
                        {"strategy": "inactivity", "quiet_period_seconds": 60, "max_age_seconds": 300},
                        target="session",
                        ai_session_id="session-abc",
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
        assert result["verdict"] is True
        assert "execute_session" in calls

    @pytest.mark.asyncio
    async def test_session_runaway_stops_polling_and_lets_the_fetch_report_it(self):
        calls: list[str] = []
        task_queue = str(uuid.uuid4())

        @activity.defn(name="check_session_settled_activity")
        async def runaway(inputs: CheckSessionSettledInputs) -> str:
            calls.append("check_session_settled")
            raise ApplicationError("session has 99999 events", type="session_runaway", non_retryable=True)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=[*_mock_activities(calls, exclude={"check_session_settled_activity"}), runaway],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs(
                        {"strategy": "inactivity", "quiet_period_seconds": 60, "max_age_seconds": 86400},
                        target="session",
                        ai_session_id="session-abc",
                    ),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
                await handle.result()
                # env.get_current_time() skews forward to the schedule-to-close timeout even once
                # a non-retryable activity failure has already been delivered; the server-recorded
                # execution window doesn't have that problem.
                description = await handle.describe()
                assert description.start_time is not None and description.close_time is not None
                elapsed = description.close_time - description.start_time
        assert calls.count("check_session_settled") == 1
        assert "execute_session" in calls
        # The point of the guard: it must not sit out the full 24h max_age first.
        assert elapsed < timedelta(hours=1)


@freeze_time("2026-07-23T12:00:00Z")
class TestCheckTraceSettledActivity:
    @pytest.mark.django_db(transaction=True)
    def test_settled_when_quiet_beyond_margin(self, setup_data):
        team = setup_data["team"]
        trace_id = f"t-settled-{uuid.uuid4()}"
        _insert_ai_event(
            team=team, event="$ai_generation", trace_id=trace_id, arrival=datetime.now(UTC) - timedelta(seconds=60)
        )
        result = check_trace_settled_activity(
            CheckTraceSettledInputs(team_id=team.id, trace_id=trace_id, quiet_period_seconds=30)
        )
        assert result is not None

    @pytest.mark.django_db(transaction=True)
    def test_not_settled_when_recent_activity(self, setup_data):
        team = setup_data["team"]
        trace_id = f"t-live-{uuid.uuid4()}"
        _insert_ai_event(
            team=team, event="$ai_generation", trace_id=trace_id, arrival=datetime.now(UTC) - timedelta(seconds=5)
        )
        with pytest.raises(ApplicationError) as err:
            check_trace_settled_activity(
                CheckTraceSettledInputs(team_id=team.id, trace_id=trace_id, quiet_period_seconds=30)
            )
        assert err.value.type == "trace_not_settled"

    @pytest.mark.django_db(transaction=True)
    def test_null_visibility_is_not_settled(self, setup_data):
        team = setup_data["team"]
        trace_id = f"t-missing-{uuid.uuid4()}"
        with pytest.raises(ApplicationError) as err:
            check_trace_settled_activity(
                CheckTraceSettledInputs(team_id=team.id, trace_id=trace_id, quiet_period_seconds=30)
            )
        assert err.value.type == "trace_not_settled"

    @pytest.mark.django_db(transaction=True)
    def test_annotation_events_do_not_defer_settling(self, setup_data):
        team = setup_data["team"]
        trace_id = f"t-annot-{uuid.uuid4()}"
        _insert_ai_event(
            team=team, event="$ai_generation", trace_id=trace_id, arrival=datetime.now(UTC) - timedelta(seconds=120)
        )
        _insert_ai_event(
            team=team, event="$ai_evaluation", trace_id=trace_id, arrival=datetime.now(UTC) - timedelta(seconds=2)
        )
        assert (
            check_trace_settled_activity(
                CheckTraceSettledInputs(team_id=team.id, trace_id=trace_id, quiet_period_seconds=30)
            )
            is not None
        )

    @pytest.mark.django_db(transaction=True)
    def test_backdated_client_timestamp_still_counts_as_activity(self, setup_data):
        team = setup_data["team"]
        trace_id = f"t-backdated-{uuid.uuid4()}"
        _insert_ai_event(
            team=team,
            event="$ai_generation",
            trace_id=trace_id,
            arrival=datetime.now(UTC) - timedelta(seconds=5),
            event_timestamp=datetime.now(UTC) - timedelta(days=3),
        )
        with pytest.raises(ApplicationError) as err:
            check_trace_settled_activity(
                CheckTraceSettledInputs(team_id=team.id, trace_id=trace_id, quiet_period_seconds=30)
            )
        # Must be the "seen recently" not-settled path, not the "nothing visible" NULL path —
        # a client timestamp outside the lookback window used to make the row invisible to the poll.
        assert err.value.type == "trace_not_settled"
        assert "trace active" in err.value.message


@freeze_time("2026-07-23T12:00:00Z")
class TestCheckSessionSettledActivity:
    @pytest.mark.django_db(transaction=True)
    def test_settled_when_quiet_beyond_margin(self, setup_data):
        team = setup_data["team"]
        session_id = f"s-settled-{uuid.uuid4()}"
        _insert_ai_event(
            team=team,
            event="$ai_generation",
            trace_id=f"t-{uuid.uuid4()}",
            arrival=datetime.now(UTC) - timedelta(seconds=60),
            session_id=session_id,
        )
        result = check_session_settled_activity(
            CheckSessionSettledInputs(
                team_id=team.id, session_id=session_id, quiet_period_seconds=30, lookback_seconds=86400
            )
        )
        assert result is not None

    @pytest.mark.django_db(transaction=True)
    def test_not_settled_while_activity_is_recent(self, setup_data):
        team = setup_data["team"]
        session_id = f"s-active-{uuid.uuid4()}"
        _insert_ai_event(
            team=team,
            event="$ai_generation",
            trace_id=f"t-{uuid.uuid4()}",
            arrival=datetime.now(UTC),
            session_id=session_id,
        )
        with pytest.raises(ApplicationError) as exc:
            check_session_settled_activity(
                CheckSessionSettledInputs(
                    team_id=team.id, session_id=session_id, quiet_period_seconds=300, lookback_seconds=86400
                )
            )
        assert exc.value.type == "session_not_settled"

    @pytest.mark.django_db(transaction=True)
    def test_keeps_polling_when_nothing_is_visible(self, setup_data):
        team = setup_data["team"]
        with pytest.raises(ApplicationError) as exc:
            check_session_settled_activity(
                CheckSessionSettledInputs(
                    team_id=team.id,
                    session_id=f"s-missing-{uuid.uuid4()}",
                    quiet_period_seconds=30,
                    lookback_seconds=86400,
                )
            )
        assert exc.value.type == "session_not_settled"
        assert exc.value.non_retryable is False

    @pytest.mark.django_db(transaction=True)
    def test_events_carrying_another_session_id_do_not_count_as_activity(self, setup_data):
        """Liveness must be scoped to the session, not the team."""
        team = setup_data["team"]
        session_id = f"s-quiet-{uuid.uuid4()}"
        _insert_ai_event(
            team=team,
            event="$ai_generation",
            trace_id=f"t-{uuid.uuid4()}",
            arrival=datetime.now(UTC) - timedelta(seconds=60),
            session_id=session_id,
        )
        _insert_ai_event(
            team=team,
            event="$ai_generation",
            trace_id=f"t-{uuid.uuid4()}",
            arrival=datetime.now(UTC),
            session_id=f"s-other-{uuid.uuid4()}",
        )
        result = check_session_settled_activity(
            CheckSessionSettledInputs(
                team_id=team.id, session_id=session_id, quiet_period_seconds=30, lookback_seconds=86400
            )
        )
        assert result is not None

    @pytest.mark.django_db(transaction=True)
    def test_evaluation_events_never_defer_settling(self, setup_data):
        """Session verdicts now carry $ai_session_id, so two session evals would otherwise
        defer each other's settling forever."""
        team = setup_data["team"]
        session_id = f"s-annotated-{uuid.uuid4()}"
        _insert_ai_event(
            team=team,
            event="$ai_generation",
            trace_id=f"t-{uuid.uuid4()}",
            arrival=datetime.now(UTC) - timedelta(seconds=60),
            session_id=session_id,
        )
        _insert_ai_event(
            team=team,
            event="$ai_evaluation",
            trace_id="",
            arrival=datetime.now(UTC),
            session_id=session_id,
        )
        result = check_session_settled_activity(
            CheckSessionSettledInputs(
                team_id=team.id, session_id=session_id, quiet_period_seconds=30, lookback_seconds=86400
            )
        )
        assert result is not None

    @pytest.mark.django_db(transaction=True)
    def test_over_cap_fails_fast_and_non_retryably(self, setup_data):
        """A shared or constant $ai_session_id would otherwise poll for the full max_age."""
        team = setup_data["team"]
        session_id = f"s-huge-{uuid.uuid4()}"
        for _ in range(3):
            _insert_ai_event(
                team=team,
                event="$ai_generation",
                trace_id=f"t-{uuid.uuid4()}",
                arrival=datetime.now(UTC) - timedelta(seconds=60),
                session_id=session_id,
            )
        with pytest.raises(ApplicationError) as exc:
            check_session_settled_activity(
                CheckSessionSettledInputs(
                    team_id=team.id,
                    session_id=session_id,
                    quiet_period_seconds=30,
                    lookback_seconds=86400,
                    runaway_events=2,
                )
            )
        assert exc.value.type == "session_runaway"
        assert exc.value.non_retryable is True
