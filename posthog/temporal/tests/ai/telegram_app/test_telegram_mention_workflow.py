import os
import uuid
from typing import Literal

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai.slack_app.types import PostHogCodeRepoCascadeOutcome
from posthog.temporal.ai.telegram_app.types import TelegramAppMentionWorkflowInputs
from posthog.temporal.ai.telegram_app.workflow import TelegramAppMentionWorkflow

_CascadeMode = Literal["auto", "no_repo", "agent_needed", "needs_user_github"]


def _inputs() -> TelegramAppMentionWorkflowInputs:
    return TelegramAppMentionWorkflowInputs(
        integration_id=1,
        chat_id="-100555",
        message={
            "message_id": 42,
            "chat": {"id": -100555, "type": "supergroup"},
            "from": {"id": 777},
            "text": "fix the bug",
        },
        user_id=7,
        update_id=1001,
    )


class _Recorder:
    def __init__(self, *, limited: bool = False, cascade_mode: _CascadeMode = "auto", needs_repo: bool = True) -> None:
        self.limited = limited
        self.cascade_mode = cascade_mode
        self.needs_repo = needs_repo
        self.replies: list[str] = []
        # repository argument per create-task call.
        self.created: list[str | None] = []


def _fake_activities(rec: _Recorder) -> list:
    @activity.defn(name="enforce_telegram_billing_quota_activity")
    async def fake_quota(inputs: TelegramAppMentionWorkflowInputs) -> bool:
        return rec.limited

    @activity.defn(name="post_telegram_reply_activity")
    async def fake_reply(inputs: TelegramAppMentionWorkflowInputs, text: str) -> None:
        rec.replies.append(text)

    @activity.defn(name="cascade_telegram_repository_activity")
    async def fake_cascade(inputs: TelegramAppMentionWorkflowInputs) -> PostHogCodeRepoCascadeOutcome:
        repository = "org/repo" if rec.cascade_mode == "auto" else None
        return PostHogCodeRepoCascadeOutcome(mode=rec.cascade_mode, repository=repository, reason="test")

    @activity.defn(name="classify_telegram_task_needs_repo_activity")
    async def fake_classify(inputs: TelegramAppMentionWorkflowInputs) -> bool:
        return rec.needs_repo

    @activity.defn(name="create_telegram_task_activity")
    async def fake_create(inputs: TelegramAppMentionWorkflowInputs, repository: str | None) -> None:
        rec.created.append(repository)

    return [fake_quota, fake_reply, fake_cascade, fake_classify, fake_create]


async def _run(rec: _Recorder) -> None:
    task_queue = str(uuid.uuid4())
    env_cm = await WorkflowEnvironment.start_time_skipping(
        test_server_existing_path=os.environ.get("TEMPORAL_TEST_SERVER_PATH")
    )
    async with env_cm as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[TelegramAppMentionWorkflow],
            activities=_fake_activities(rec),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                TelegramAppMentionWorkflow.run,
                _inputs(),
                id=f"wf-{uuid.uuid4()}",
                task_queue=task_queue,
            )


@pytest.mark.asyncio
async def test_quota_blocked_posts_denial_and_creates_nothing():
    rec = _Recorder(limited=True)

    await _run(rec)

    assert rec.created == []
    assert len(rec.replies) == 1
    assert "out of AI credits" in rec.replies[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_snippet",
    [
        ("agent_needed", "Tell me which one to use"),
        ("needs_user_github", "Connect your GitHub account"),
    ],
)
async def test_unresolvable_repo_asks_instead_of_dead_ending(mode: _CascadeMode, expected_snippet: str):
    # The no-picker contract: when the cascade can't resolve a repo, the user gets an
    # actionable reply — a silent stop would read as the bot ignoring the mention.
    rec = _Recorder(cascade_mode=mode, needs_repo=True)

    await _run(rec)

    assert rec.created == []
    assert len(rec.replies) == 1
    assert expected_snippet in rec.replies[0]


@pytest.mark.asyncio
async def test_analytics_question_with_many_repos_creates_no_repo_task():
    # A multi-repo workspace must still answer analytics/config questions: the
    # needs-repo classifier gates the ask-for-repo reply, so dropping it turns
    # every question into "tell me which repo" (the v1 dogfood bug).
    rec = _Recorder(cascade_mode="agent_needed", needs_repo=False)

    await _run(rec)

    assert rec.created == [None]
    assert rec.replies == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_repository",
    [
        ("auto", "org/repo"),
        ("no_repo", None),
    ],
)
async def test_resolvable_modes_create_task_with_expected_repository(
    mode: _CascadeMode, expected_repository: str | None
):
    rec = _Recorder(cascade_mode=mode)

    await _run(rec)

    assert rec.created == [expected_repository]
    assert rec.replies == []
