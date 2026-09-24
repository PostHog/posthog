from __future__ import annotations

import uuid
import asyncio
import logging
import itertools
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, TypedDict

import pytest
from unittest import mock

import temporalio.worker
from parameterized import parameterized
from temporalio import activity, common, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from posthog.temporal.weekly_digest.activities import (
    count_organizations,
    generate_dashboard_lookup,
    generate_error_issue_lookup,
    generate_event_definition_lookup,
    generate_experiment_completed_lookup,
    generate_experiment_launched_lookup,
    generate_external_data_source_lookup,
    generate_feature_flag_lookup,
    generate_filter_lookup,
    generate_organization_digest_batch,
    generate_product_suggestion_lookup,
    generate_recording_lookup,
    generate_survey_lookup,
    generate_usage_trends_lookup,
    generate_user_notification_lookup,
    list_team_id_ranges,
)
from posthog.temporal.weekly_digest.types import (
    CommonInput,
    Digest,
    GenerateDigestDataBatchInput,
    GenerateDigestDataInput,
    GenerateOrganizationDigestInput,
    SendWeeklyDigestBatchInput,
    SendWeeklyDigestInput,
    TeamIdRange,
    WeeklyDigestInput,
)
from posthog.temporal.weekly_digest.workflows import (
    MAX_CONCURRENT_GENERATION_ACTIVITIES,
    GenerateDigestDataWorkflow,
    SendWeeklyDigestWorkflow,
    WeeklyDigestWorkflow,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


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
        await workflow.sleep(timedelta(hours=7))
        _test_state["generate_called"] = True


@workflow.defn(name="send-weekly-digest")
class MockSendWeeklyDigestWorkflow:
    @workflow.run
    async def run(self, input: SendWeeklyDigestInput) -> None:
        _test_state["send_called"] = True
        _test_state["captured_digest_key"] = input.digest.key


@workflow.defn(name="generate-digest-data")
class LegacyGenerateDigestDataWorkflow:
    @workflow.run
    async def run(self, input: GenerateDigestDataInput) -> None:
        team_id_ranges = await workflow.execute_activity(
            list_team_id_ranges,
            input.common,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1)),
            heartbeat_timeout=timedelta(minutes=1),
        )
        generators = [
            generate_dashboard_lookup,
            generate_event_definition_lookup,
            generate_experiment_completed_lookup,
            generate_experiment_launched_lookup,
            generate_external_data_source_lookup,
            generate_survey_lookup,
            generate_feature_flag_lookup,
            generate_user_notification_lookup,
            generate_filter_lookup,
            generate_recording_lookup,
            generate_product_suggestion_lookup,
            generate_error_issue_lookup,
            generate_usage_trends_lookup,
        ]

        await asyncio.gather(
            *(
                workflow.execute_activity(
                    generator,
                    GenerateDigestDataBatchInput(
                        team_id_range=team_id_range,
                        digest=input.digest,
                        common=input.common,
                    ),
                    start_to_close_timeout=timedelta(hours=1),
                    retry_policy=common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1)),
                    heartbeat_timeout=timedelta(minutes=2),
                )
                for team_id_range, generator in itertools.product(team_id_ranges, generators)
            )
        )
        organization_count = await workflow.execute_activity(
            count_organizations,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1)),
            heartbeat_timeout=timedelta(minutes=1),
        )
        batch_size = input.common.batch_size
        org_batches = [(start, start + batch_size) for start in range(0, organization_count, batch_size)]
        await asyncio.gather(
            *(
                workflow.execute_activity(
                    generate_organization_digest_batch,
                    GenerateOrganizationDigestInput(
                        batch=batch,
                        digest=input.digest,
                        common=input.common,
                    ),
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=common.RetryPolicy(maximum_attempts=2, initial_interval=timedelta(minutes=1)),
                    heartbeat_timeout=timedelta(minutes=2),
                )
                for batch in org_batches
            )
        )


@pytest.mark.asyncio
async def test_weekly_digest_workflow():
    """Generation can take seven hours and still complete before sending starts."""
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


@parameterized.expand([(True,), (False,)])
@pytest.mark.asyncio
async def test_generate_digest_data_bounds_pending_activities(patched: bool) -> None:
    team_ranges = [TeamIdRange(start=i, end=i + 1) for i in range(200)]
    pending = 0
    peak_pending = 0
    completed: list[tuple[object, int, int]] = []
    aggregated: list[tuple[int, int]] = []

    async def execute_activity(activity_fn: object, activity_input: object = None, **_: object) -> object:
        nonlocal pending, peak_pending
        if activity_fn is list_team_id_ranges:
            return team_ranges
        if activity_fn is count_organizations:
            assert pending == 0
            assert len(completed) == 13 * len(team_ranges)
            return 3
        if activity_fn is generate_organization_digest_batch:
            assert isinstance(activity_input, GenerateOrganizationDigestInput)
            aggregated.append(activity_input.batch)
            return None

        assert isinstance(activity_input, GenerateDigestDataBatchInput)
        pending += 1
        peak_pending = max(peak_pending, pending)
        loop = asyncio.get_running_loop()
        completion: asyncio.Future[None] = loop.create_future()
        loop.call_soon(completion.set_result, None)
        try:
            await completion
            completed.append((activity_fn, activity_input.team_id_range.start, activity_input.team_id_range.end))
        finally:
            pending -= 1
        return None

    period_end = datetime.now(UTC)
    with (
        mock.patch("temporalio.workflow.execute_activity", side_effect=execute_activity),
        mock.patch("temporalio.workflow.patched", return_value=patched),
    ):
        await GenerateDigestDataWorkflow().run(
            GenerateDigestDataInput(
                digest=Digest(key="test-digest", period_start=period_end - timedelta(days=7), period_end=period_end),
                common=CommonInput(batch_size=2),
            )
        )

    assert len(completed) == len(set(completed)) == 13 * len(team_ranges)
    assert Counter((start, end) for _, start, end in completed) == {
        (team_range.start, team_range.end): 13 for team_range in team_ranges
    }
    assert aggregated == [(0, 2), (2, 4)]
    if patched:
        assert peak_pending <= MAX_CONCURRENT_GENERATION_ACTIVITIES < 2000
    else:
        assert peak_pending == 13 * len(team_ranges)


@pytest.mark.asyncio
async def test_generate_digest_data_replays_pre_patch_history(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    team_ranges = [TeamIdRange(start=i, end=i + 1) for i in range(8)]
    generator_names = [
        "generate-dashboard-lookup",
        "generate-event-definition-lookup",
        "generate-experiment-completed-lookup",
        "generate-experiment-launched-lookup",
        "generate-external-data-source-lookup",
        "generate-survey-lookup",
        "generate-feature-flag-lookup",
        "generate-user-notification-lookup",
        "generate-filter-lookup",
        "generate-recording-lookup",
        "generate-product-suggestion-lookup",
        "generate-error-issue-lookup",
        "generate-usage-trends-lookup",
    ]

    @activity.defn(name="list-team-id-ranges")
    async def list_team_id_ranges_mocked(_input: CommonInput) -> list[TeamIdRange]:
        return team_ranges

    @activity.defn(name="count-organizations")
    async def count_organizations_mocked() -> int:
        return 3

    @activity.defn(name="generate-organization-digest-batch")
    async def generate_organization_digest_batch_mocked(_input: GenerateOrganizationDigestInput) -> None:
        return None

    def make_generator(name: str) -> Callable[[GenerateDigestDataBatchInput], Awaitable[None]]:
        @activity.defn(name=name)
        async def generator(_input: GenerateDigestDataBatchInput) -> None:
            return None

        return generator

    activities: list[Callable[..., Awaitable[object]]] = [
        list_team_id_ranges_mocked,
        count_organizations_mocked,
        generate_organization_digest_batch_mocked,
        *(make_generator(name) for name in generator_names),
    ]
    task_queue_name = str(uuid.uuid4())
    period_end = datetime.now(UTC)
    digest_input = GenerateDigestDataInput(
        digest=Digest(key="replay-test", period_start=period_end - timedelta(days=7), period_end=period_end),
        common=CommonInput(batch_size=2, redis_host="localhost", redis_port=6379),
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue_name,
            workflows=[LegacyGenerateDigestDataWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                LegacyGenerateDigestDataWorkflow.run,
                digest_input,
                id=str(uuid.uuid4()),
                task_queue=task_queue_name,
                execution_timeout=timedelta(seconds=30),
            )
            await handle.result()
            pre_patch_history = await handle.fetch_history()

    scheduled_generator_events = [
        event
        for event in pre_patch_history.events
        if event.HasField("activity_task_scheduled_event_attributes")
        and event.activity_task_scheduled_event_attributes.activity_type.name in generator_names
    ]
    assert (
        len(scheduled_generator_events)
        == len(team_ranges) * len(generator_names)
        > MAX_CONCURRENT_GENERATION_ACTIVITIES
    )
    assert (
        len(
            {
                event.activity_task_scheduled_event_attributes.workflow_task_completed_event_id
                for event in scheduled_generator_events
            }
        )
        == 1
    )
    assert not any(event.HasField("marker_recorded_event_attributes") for event in pre_patch_history.events)
    await Replayer(
        workflows=[GenerateDigestDataWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ).replay_workflow(pre_patch_history)


@pytest.mark.asyncio
async def test_generate_digest_data_workflow():
    """Test the digest data generation workflow with batched activities."""
    TEST_TEAM_COUNT = 5
    TEST_ORG_COUNT = 2
    TEST_BATCH_SIZE = 2

    activity_calls = {
        "team_id_ranges": 0,
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
        "product_suggestion": 0,
        "error_issue": 0,
        "usage_trends": 0,
        "org_digest": 0,
    }

    @activity.defn(name="list-team-id-ranges")
    async def list_team_id_ranges_mocked(input) -> list[TeamIdRange]:
        activity_calls["team_id_ranges"] += 1
        return [TeamIdRange(start=i, end=i + TEST_BATCH_SIZE) for i in range(1, TEST_TEAM_COUNT + 1, TEST_BATCH_SIZE)]

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

    @activity.defn(name="generate-product-suggestion-lookup")
    async def generate_product_suggestion_lookup_mocked(input) -> None:
        activity_calls["product_suggestion"] += 1

    @activity.defn(name="generate-error-issue-lookup")
    async def generate_error_issue_lookup_mocked(input) -> None:
        activity_calls["error_issue"] += 1

    @activity.defn(name="generate-usage-trends-lookup")
    async def generate_usage_trends_lookup_mocked(input) -> None:
        activity_calls["usage_trends"] += 1

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
                list_team_id_ranges_mocked,
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
                generate_product_suggestion_lookup_mocked,
                generate_error_issue_lookup_mocked,
                generate_usage_trends_lookup_mocked,
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

    assert activity_calls["team_id_ranges"] == 1
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
    assert activity_calls["product_suggestion"] == expected_team_batches
    assert activity_calls["error_issue"] == expected_team_batches
    assert activity_calls["usage_trends"] == expected_team_batches

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
                    allow_already_sent=False,
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
