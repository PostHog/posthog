import uuid
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import pytest

import temporalio.worker
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.weekly_digest.types import (
    CommonInput,
    Digest,
    GenerateDigestDataInput,
    SendWeeklyDigestBatchInput,
    SendWeeklyDigestInput,
    WeeklyDigestInput,
)
from posthog.temporal.weekly_digest.workflows import (
    GenerateDigestDataWorkflow,
    SendWeeklyDigestWorkflow,
    WeeklyDigestWorkflow,
)


class _TestState(TypedDict):
    generate_called: bool
    send_called: bool
    captured_digest_key: str | None


# Track calls in these module-level variables for testing
_test_state: _TestState = {"generate_called": False, "send_called": False, "captured_digest_key": None}


@workflow.defn(name="generate-digest-data")
class MockGenerateDigestDataWorkflow:
    @workflow.run
    async def run(self, input: GenerateDigestDataInput) -> None:
        _test_state["generate_called"] = True


@workflow.defn(name="send-weekly-digest")
class MockSendWeeklyDigestWorkflow:
    @workflow.run
    async def run(self, input: SendWeeklyDigestInput) -> None:
        _test_state["send_called"] = True
        _test_state["captured_digest_key"] = input.digest.key


@pytest.mark.asyncio
async def test_weekly_digest_workflow():
    """Test the main weekly digest workflow that orchestrates generation and sending."""
    _test_state["generate_called"] = False
    _test_state["send_called"] = False

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[WeeklyDigestWorkflow, MockGenerateDigestDataWorkflow, MockSendWeeklyDigestWorkflow],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                WeeklyDigestWorkflow.run,
                WeeklyDigestInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert _test_state["generate_called"], "Generate workflow should have been called"
    assert _test_state["send_called"], "Send workflow should have been called"


@pytest.mark.asyncio
async def test_weekly_digest_workflow_skip_generate():
    """Test that weekly digest workflow can skip the generate phase."""
    _test_state["generate_called"] = False
    _test_state["send_called"] = False

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[WeeklyDigestWorkflow, MockGenerateDigestDataWorkflow, MockSendWeeklyDigestWorkflow],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                WeeklyDigestWorkflow.run,
                WeeklyDigestInput(skip_generate=True, dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert not _test_state["generate_called"], "Generate workflow should not have been called"
    assert _test_state["send_called"], "Send workflow should have been called"


@pytest.mark.asyncio
async def test_generate_digest_data_workflow():
    """Test the digest data generation workflow with batched activities."""
    TEST_TEAM_COUNT = 5
    TEST_ORG_COUNT = 2
    TEST_BATCH_SIZE = 2

    activity_calls = {
        "count_teams": 0,
        "count_organizations": 0,
        "dashboard": 0,
        "event_definition": 0,
        "experiment_completed": 0,
        "experiment_launched": 0,
        "external_data_source": 0,
        "survey": 0,
        "feature_flag": 0,
        "user_notification": 0,
        "filter": 0,
        "recording": 0,
        "org_digest": 0,
    }

    @activity.defn(name="count-teams")
    async def count_teams_mocked() -> int:
        activity_calls["count_teams"] += 1
        return TEST_TEAM_COUNT

    @activity.defn(name="count-organizations")
    async def count_organizations_mocked() -> int:
        activity_calls["count_organizations"] += 1
        return TEST_ORG_COUNT

    @activity.defn(name="generate-dashboard-lookup")
    async def generate_dashboard_lookup_mocked(input) -> None:
        activity_calls["dashboard"] += 1

    @activity.defn(name="generate-event-definition-lookup")
    async def generate_event_definition_lookup_mocked(input) -> None:
        activity_calls["event_definition"] += 1

    @activity.defn(name="generate-experiment-completed-lookup")
    async def generate_experiment_completed_lookup_mocked(input) -> None:
        activity_calls["experiment_completed"] += 1

    @activity.defn(name="generate-experiment-launched-lookup")
    async def generate_experiment_launched_lookup_mocked(input) -> None:
        activity_calls["experiment_launched"] += 1

    @activity.defn(name="generate-external-data-source-lookup")
    async def generate_external_data_source_lookup_mocked(input) -> None:
        activity_calls["external_data_source"] += 1

    @activity.defn(name="generate-survey-lookup")
    async def generate_survey_lookup_mocked(input) -> None:
        activity_calls["survey"] += 1

    @activity.defn(name="generate-feature-flag-lookup")
    async def generate_feature_flag_lookup_mocked(input) -> None:
        activity_calls["feature_flag"] += 1

    @activity.defn(name="generate-user-notification-lookup")
    async def generate_user_notification_lookup_mocked(input) -> None:
        activity_calls["user_notification"] += 1

    @activity.defn(name="generate-filter-lookup")
    async def generate_filter_lookup_mocked(input) -> None:
        activity_calls["filter"] += 1

    @activity.defn(name="generate-recording-lookup")
    async def generate_recording_lookup_mocked(input) -> None:
        activity_calls["recording"] += 1

    @activity.defn(name="generate-organization-digest-batch")
    async def generate_organization_digest_batch_mocked(input) -> None:
        activity_calls["org_digest"] += 1

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[GenerateDigestDataWorkflow],
            activities=[
                count_teams_mocked,
                count_organizations_mocked,
                generate_dashboard_lookup_mocked,
                generate_event_definition_lookup_mocked,
                generate_experiment_completed_lookup_mocked,
                generate_experiment_launched_lookup_mocked,
                generate_external_data_source_lookup_mocked,
                generate_survey_lookup_mocked,
                generate_feature_flag_lookup_mocked,
                generate_user_notification_lookup_mocked,
                generate_filter_lookup_mocked,
                generate_recording_lookup_mocked,
                generate_organization_digest_batch_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            period_end = datetime.now(UTC)
            period_start = period_end - timedelta(days=7)
            digest = Digest(key="test-digest", period_start=period_start, period_end=period_end)

            await env.client.execute_workflow(
                GenerateDigestDataWorkflow.run,
                GenerateDigestDataInput(
                    digest=digest,
                    common=CommonInput(batch_size=TEST_BATCH_SIZE, redis_host="localhost", redis_port=6379),
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert activity_calls["count_teams"] == 1
    assert activity_calls["count_organizations"] == 1

    # Calculate expected batches for teams
    expected_team_batches = (TEST_TEAM_COUNT + TEST_BATCH_SIZE - 1) // TEST_BATCH_SIZE

    # Each generator should be called once per batch
    assert activity_calls["dashboard"] == expected_team_batches
    assert activity_calls["event_definition"] == expected_team_batches
    assert activity_calls["experiment_completed"] == expected_team_batches
    assert activity_calls["experiment_launched"] == expected_team_batches
    assert activity_calls["external_data_source"] == expected_team_batches
    assert activity_calls["survey"] == expected_team_batches
    assert activity_calls["feature_flag"] == expected_team_batches
    assert activity_calls["user_notification"] == expected_team_batches
    assert activity_calls["filter"] == expected_team_batches
    assert activity_calls["recording"] == expected_team_batches

    # Calculate expected batches for organizations
    expected_org_batches = (TEST_ORG_COUNT + TEST_BATCH_SIZE - 1) // TEST_BATCH_SIZE
    assert activity_calls["org_digest"] == expected_org_batches


@pytest.mark.asyncio
async def test_send_weekly_digest_workflow():
    """Test the digest sending workflow with batched activities."""
    TEST_ORG_COUNT = 10
    TEST_BATCH_SIZE = 3

    activity_calls = {
        "count_organizations": 0,
        "send_batch": 0,
    }

    @activity.defn(name="count-organizations")
    async def count_organizations_mocked() -> int:
        activity_calls["count_organizations"] += 1
        return TEST_ORG_COUNT

    @activity.defn(name="send-weekly-digest-batch")
    async def send_weekly_digest_batch_mocked(input: SendWeeklyDigestBatchInput) -> None:
        activity_calls["send_batch"] += 1
        assert input.dry_run is True
        assert input.digest.key == "test-digest"

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[SendWeeklyDigestWorkflow],
            activities=[
                count_organizations_mocked,
                send_weekly_digest_batch_mocked,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            period_end = datetime.now(UTC)
            period_start = period_end - timedelta(days=7)
            digest = Digest(key="test-digest", period_start=period_start, period_end=period_end)

            await env.client.execute_workflow(
                SendWeeklyDigestWorkflow.run,
                SendWeeklyDigestInput(
                    dry_run=True,
                    digest=digest,
                    common=CommonInput(batch_size=TEST_BATCH_SIZE, redis_host="localhost", redis_port=6379),
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert activity_calls["count_organizations"] == 1

    # Calculate expected batches
    expected_batches = (TEST_ORG_COUNT + TEST_BATCH_SIZE - 1) // TEST_BATCH_SIZE
    assert activity_calls["send_batch"] == expected_batches


@pytest.mark.asyncio
async def test_weekly_digest_workflow_with_custom_key():
    """Test that digest key override works correctly."""
    _test_state["captured_digest_key"] = None

    task_queue_name = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[WeeklyDigestWorkflow, MockGenerateDigestDataWorkflow, MockSendWeeklyDigestWorkflow],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                WeeklyDigestWorkflow.run,
                WeeklyDigestInput(dry_run=True, skip_generate=True, digest_key_override="custom-test-digest-key"),
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
            )

    assert _test_state["captured_digest_key"] == "custom-test-digest-key"
