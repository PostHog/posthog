import os
import uuid
import asyncio
from typing import Any, Literal

import pytest

from temporalio import activity
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai.slack_app import derive_mention_workflow_id
from posthog.temporal.ai.slack_app.slack_app_mention import SlackAppMentionWorkflow
from posthog.temporal.ai.slack_app.types import (
    PostHogCodeRepoCascadeOutcome,
    PostHogCodeSlackMentionWorkflowInputs,
    SlackAppMentionWorkflowInputs,
    SlackRepoSelectionOutcome,
)


def _message(
    ts: str,
    *,
    event_id: str | None = None,
    untagged: bool = False,
) -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C1", "ts": ts, "thread_ts": "100.0", "user": "U1", "text": "fix the bug"},
        integration_id=1,
        slack_team_id="T1",
        slack_event_id=event_id,
        user_id=42,
        untagged_followup=untagged,
    )


class _Recorder:
    def __init__(self) -> None:
        # (ts, repository) per create-task call, in execution order.
        self.created: list[tuple[str, str | None]] = []
        # ts per forwarded followup, in execution order.
        self.forwarded: list[str] = []
        # ts -> forward result; missing means False (no existing task, fall through to new-task path).
        self.forward_results: dict[str, bool] = {}
        # ts -> cascade mode; missing means "auto" with a fixed repository.
        self.cascade_modes: dict[str, Literal["auto", "no_repo", "agent_needed", "needs_user_github"]] = {}
        # ts -> gate the create-task fake blocks on, to hold a message mid-processing.
        self.create_gates: dict[str, asyncio.Event] = {}
        self.create_reached: dict[str, asyncio.Event] = {}
        self.picker_posted = asyncio.Event()
        self.picker_workflow_id: str | None = None


def _fake_activities(rec: _Recorder) -> list:
    @activity.defn(name="enforce_posthog_code_billing_quota_activity")
    async def quota(
        inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str, slack_user_id: str
    ) -> bool:
        return False

    @activity.defn(name="classify_untagged_followup_activity")
    async def classify_followup(
        inputs: PostHogCodeSlackMentionWorkflowInputs,
        channel: str,
        thread_ts: str,
        slack_user_id: str,
        event_text: str,
    ) -> bool:
        return True

    @activity.defn(name="forward_posthog_code_followup_activity")
    async def forward(
        inputs: PostHogCodeSlackMentionWorkflowInputs,
        channel: str,
        thread_ts: str,
        slack_user_id: str,
        event_text: str,
        user_message_ts: str | None,
    ) -> bool:
        ts = inputs.event["ts"]
        if rec.forward_results.get(ts, False):
            rec.forwarded.append(ts)
            return True
        return False

    @activity.defn(name="collect_posthog_code_thread_messages_activity")
    async def collect(
        inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str
    ) -> list[dict[str, str]]:
        return [{"user": "U1", "text": inputs.event["text"]}]

    @activity.defn(name="cascade_posthog_code_repository_activity")
    async def cascade(
        inputs: PostHogCodeSlackMentionWorkflowInputs, event_text: str, user_id: int | None = None
    ) -> PostHogCodeRepoCascadeOutcome:
        mode = rec.cascade_modes.get(inputs.event["ts"], "auto")
        repository = "org/auto-repo" if mode == "auto" else None
        return PostHogCodeRepoCascadeOutcome(mode=mode, repository=repository, reason="test")

    @activity.defn(name="classify_posthog_code_task_needs_repo_activity")
    async def needs_repo(event_text: str, thread_messages: list[dict[str, str]]) -> bool:
        return True

    @activity.defn(name="discover_posthog_code_repository_via_agent_activity")
    async def discover(
        inputs: PostHogCodeSlackMentionWorkflowInputs,
        channel: str,
        event: dict[str, Any],
        thread_messages: list[dict[str, str]],
        user_id: int,
    ) -> SlackRepoSelectionOutcome:
        return SlackRepoSelectionOutcome(status="failed", repository=None, reason="agent crashed")

    @activity.defn(name="post_posthog_code_repo_picker_activity")
    async def post_picker(
        inputs: PostHogCodeSlackMentionWorkflowInputs,
        channel: str,
        thread_ts: str,
        slack_user_id: str,
        event: dict[str, Any],
        workflow_id: str,
        guidance: str,
        allow_no_repo: bool,
        user_id: int | None = None,
    ) -> None:
        rec.picker_workflow_id = workflow_id
        rec.picker_posted.set()

    @activity.defn(name="resolve_posthog_code_authorship_activity")
    async def resolve_authorship(
        inputs: PostHogCodeSlackMentionWorkflowInputs,
        channel: str,
        thread_ts: str,
        slack_user_id: str,
        user_id: int,
        workflow_id: str,
        repository: str,
    ) -> str:
        return "proceed"

    @activity.defn(name="block_posthog_code_task_if_no_personal_github_activity")
    async def block_github(
        inputs: PostHogCodeSlackMentionWorkflowInputs,
        channel: str,
        thread_ts: str,
        user_id: int,
        allow_bot_prs: bool = False,
    ) -> bool:
        return False

    @activity.defn(name="create_posthog_code_task_for_repo_activity")
    async def create_task(
        inputs: PostHogCodeSlackMentionWorkflowInputs,
        channel: str,
        thread_ts: str,
        slack_user_id: str,
        user_id: int,
        event: dict[str, Any],
        thread_messages: list[dict[str, str]],
        repository: str | None,
        repo_research_task_id: str | None = None,
        repo_research_run_id: str | None = None,
    ) -> None:
        ts = inputs.event["ts"]
        reached = rec.create_reached.get(ts)
        if reached:
            reached.set()
        gate = rec.create_gates.get(ts)
        if gate:
            await gate.wait()
        rec.created.append((ts, repository))

    @activity.defn(name="post_posthog_code_picker_timeout_activity")
    async def picker_timeout(inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str) -> None:
        return None

    @activity.defn(name="post_posthog_code_authorship_timeout_activity")
    async def authorship_timeout(inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str) -> None:
        return None

    @activity.defn(name="post_posthog_code_internal_error_activity")
    async def internal_error(inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str) -> None:
        return None

    @activity.defn(name="resolve_posthog_code_slack_user_activity")
    async def resolve_user(
        inputs: PostHogCodeSlackMentionWorkflowInputs, channel: str, thread_ts: str, slack_user_id: str
    ) -> int | None:
        return 42

    return [
        quota,
        classify_followup,
        forward,
        collect,
        cascade,
        needs_repo,
        discover,
        post_picker,
        resolve_authorship,
        block_github,
        create_task,
        picker_timeout,
        authorship_timeout,
        internal_error,
        resolve_user,
    ]


async def _signal_with_start(env, task_queue: str, workflow_id: str, message: PostHogCodeSlackMentionWorkflowInputs):
    """Mirror the production dispatch shape from api._start_mention_workflow."""
    return await env.client.start_workflow(
        SlackAppMentionWorkflow.run,
        SlackAppMentionWorkflowInputs(),
        id=workflow_id,
        task_queue=task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        start_signal="new_message",
        start_signal_args=[message],
    )


class _Harness:
    """One time-skipping environment + worker per test.

    Time only skips while the test awaits the workflow result, so the idle
    timer (and the 15-minute picker timer) stay parked while the test delivers
    signals in real time — no sleeps, no timer races.
    """

    def __init__(self, rec: _Recorder) -> None:
        self.rec = rec
        self.task_queue = str(uuid.uuid4())

    async def __aenter__(self):
        # Escape hatch for networks where the SDK's temporal.download fetch is
        # blocked: point at a pre-downloaded temporal-test-server binary (from
        # the temporalio/sdk-java GitHub releases). Unset, the SDK downloads
        # and caches the binary itself.
        self._env_cm = await WorkflowEnvironment.start_time_skipping(
            test_server_existing_path=os.environ.get("TEMPORAL_TEST_SERVER_PATH")
        )
        self.env = await self._env_cm.__aenter__()
        self._worker_cm = Worker(
            self.env.client,
            task_queue=self.task_queue,
            workflows=[SlackAppMentionWorkflow],
            activities=_fake_activities(self.rec),
            workflow_runner=UnsandboxedWorkflowRunner(),
        )
        await self._worker_cm.__aenter__()
        return self

    async def __aexit__(self, *exc_info):
        await self._worker_cm.__aexit__(*exc_info)
        await self._env_cm.__aexit__(*exc_info)


@pytest.mark.asyncio
async def test_queued_messages_process_serially_in_arrival_order():
    rec = _Recorder()
    first, second, third = _message("1.1"), _message("1.2"), _message("1.3")
    rec.create_reached["1.1"] = asyncio.Event()
    rec.create_gates["1.1"] = asyncio.Event()

    async with _Harness(rec) as h:
        handle = await _signal_with_start(h.env, h.task_queue, f"wf-{uuid.uuid4()}", first)
        # Hold the first message inside its create-task activity, queue two
        # more behind it, then release. FIFO must be preserved.
        await asyncio.wait_for(rec.create_reached["1.1"].wait(), timeout=30)
        await handle.signal(SlackAppMentionWorkflow.new_message, second)
        await handle.signal(SlackAppMentionWorkflow.new_message, third)
        rec.create_gates["1.1"].set()
        await asyncio.wait_for(handle.result(), timeout=30)

    assert rec.created == [("1.1", "org/auto-repo"), ("1.2", "org/auto-repo"), ("1.3", "org/auto-repo")]


@pytest.mark.asyncio
async def test_signal_with_start_on_running_workflow_signals_same_run():
    rec = _Recorder()
    first, second = _message("1.1"), _message("1.2")
    rec.create_reached["1.1"] = asyncio.Event()
    rec.create_gates["1.1"] = asyncio.Event()

    async with _Harness(rec) as h:
        workflow_id = f"wf-{uuid.uuid4()}"
        handle = await _signal_with_start(h.env, h.task_queue, workflow_id, first)
        # Issue a second signal-with-start (the exact production dispatch call)
        # while the first run is mid-message. It must NOT start a second
        # execution — the server delivers the signal to the running one.
        await asyncio.wait_for(rec.create_reached["1.1"].wait(), timeout=30)
        handle_two = await _signal_with_start(h.env, h.task_queue, workflow_id, second)
        rec.create_gates["1.1"].set()
        await asyncio.wait_for(handle.result(), timeout=30)
        assert handle_two.first_execution_run_id == handle.first_execution_run_id

    assert rec.created == [("1.1", "org/auto-repo"), ("1.2", "org/auto-repo")]


@pytest.mark.asyncio
async def test_duplicate_slack_event_id_is_processed_once():
    rec = _Recorder()
    message = _message("1.1", event_id="Ev123")

    async with _Harness(rec) as h:
        handle = await _signal_with_start(h.env, h.task_queue, f"wf-{uuid.uuid4()}", message)
        await handle.signal(SlackAppMentionWorkflow.new_message, message)
        await asyncio.wait_for(handle.result(), timeout=30)

    assert rec.created == [("1.1", "org/auto-repo")]


@pytest.mark.asyncio
async def test_untagged_followup_forwards_without_task_creation():
    rec = _Recorder()
    rec.forward_results["1.1"] = True

    async with _Harness(rec) as h:
        handle = await _signal_with_start(h.env, h.task_queue, f"wf-{uuid.uuid4()}", _message("1.1", untagged=True))
        await asyncio.wait_for(handle.result(), timeout=30)

    assert rec.forwarded == ["1.1"]
    assert rec.created == []


@pytest.mark.asyncio
async def test_idle_exit_then_signal_with_start_processes_in_fresh_run():
    rec = _Recorder()
    workflow_id = f"wf-{uuid.uuid4()}"

    async with _Harness(rec) as h:
        handle = await _signal_with_start(h.env, h.task_queue, workflow_id, _message("1.1"))
        await asyncio.wait_for(handle.result(), timeout=30)
        # First run has idled out and completed; the production dispatch shape
        # must start a fresh run under the same conversation ID.
        handle_two = await _signal_with_start(h.env, h.task_queue, workflow_id, _message("2.1"))
        await asyncio.wait_for(handle_two.result(), timeout=30)
        assert handle_two.result_run_id != handle.result_run_id

    assert rec.created == [("1.1", "org/auto-repo"), ("2.1", "org/auto-repo")]


@pytest.mark.asyncio
async def test_repo_picker_signal_resolves_and_queue_continues():
    rec = _Recorder()
    rec.cascade_modes["1.1"] = "agent_needed"

    async with _Harness(rec) as h:
        workflow_id = f"wf-{uuid.uuid4()}"
        handle = await _signal_with_start(h.env, h.task_queue, workflow_id, _message("1.1"))
        # First message falls through discovery to the picker and blocks the
        # queue; a second message queues up behind it in the meantime.
        await asyncio.wait_for(rec.picker_posted.wait(), timeout=30)
        await handle.signal(SlackAppMentionWorkflow.new_message, _message("1.2"))
        await handle.signal(SlackAppMentionWorkflow.repo_selected, "org/picked")
        await asyncio.wait_for(handle.result(), timeout=30)

        # The picker message must carry the conversation workflow ID — it is what
        # the interactivity webhook uses to route the click back as a signal.
        assert rec.picker_workflow_id == workflow_id

    assert rec.created == [("1.1", "org/picked"), ("1.2", "org/auto-repo")]


@pytest.mark.asyncio
async def test_continue_as_new_carry_over_processes_pending_and_dedups_seen():
    rec = _Recorder()
    pending = _message("1.1", event_id="Ev-pending")
    already_seen = _message("1.2", event_id="Ev-seen")

    async with _Harness(rec) as h:
        # Start with post-continue_as_new-shaped inputs: one carried pending
        # message and one already-processed key.
        handle = await h.env.client.start_workflow(
            SlackAppMentionWorkflow.run,
            SlackAppMentionWorkflowInputs(
                pending_messages=[pending],
                processed_event_keys=[derive_mention_workflow_id(already_seen)],
            ),
            id=f"wf-{uuid.uuid4()}",
            task_queue=h.task_queue,
        )
        await handle.signal(SlackAppMentionWorkflow.new_message, already_seen)
        await asyncio.wait_for(handle.result(), timeout=30)

    assert rec.created == [("1.1", "org/auto-repo")]
