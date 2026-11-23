import json
import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from unittest.mock import patch

from django.db import connection

import pytest_asyncio
from temporalio import activity, common, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import (
    Interceptor,
    StartActivityInput,
    UnsandboxedWorkflowRunner,
    Worker,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
    WorkflowOutboundInterceptor,
)

from posthog.dataclasses import frozen
from posthog.entitlements import execution
from posthog.entitlements.contracts import EntitlementChange, EntitlementReactor, Entitlements
from posthog.entitlements.registry import EntitlementReactorRegistry
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig
from posthog.models.organization import Organization
from posthog.models.organization_entitlement_applied_state import OrganizationEntitlementAppliedState
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.entitlement_reactions.activities import (
    execute_entitlement_reactor_activity,
    list_behind_entitlement_reactors_activity,
)
from posthog.temporal.entitlement_reactions.contracts import EntitlementReactionsInputs, EntitlementReactionsResult
from posthog.temporal.entitlement_reactions.workflow import EntitlementReactionsWorkflow

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


class ShortActivityTimeouts(WorkflowOutboundInterceptor):
    def start_activity(self, input: StartActivityInput) -> workflow.ActivityHandle[Any]:
        input.start_to_close_timeout = timedelta(seconds=2)
        input.schedule_to_close_timeout = timedelta(seconds=15)
        input.retry_policy = common.RetryPolicy(
            initial_interval=timedelta(milliseconds=50), maximum_attempts=2, backoff_coefficient=1
        )
        return self.next.start_activity(input)


class TestWorkflowInbound(WorkflowInboundInterceptor):
    __test__ = False

    def init(self, outbound: WorkflowOutboundInterceptor) -> None:
        self.next.init(ShortActivityTimeouts(outbound))


class TestTimeouts(Interceptor):
    __test__ = False

    def workflow_interceptor_class(self, input: WorkflowInterceptorClassInput) -> type[WorkflowInboundInterceptor]:
        return TestWorkflowInbound


@pytest_asyncio.fixture
async def temporal_environment(caplog: pytest.LogCaptureFixture) -> AsyncIterator[WorkflowEnvironment]:
    caplog.set_level(logging.INFO, logger=__name__)
    loggers = [logging.getLogger(name) for name in ("temporalio.activity", "temporalio.workflow")]
    levels = [logger.level for logger in loggers]
    try:
        for logger in loggers:
            logger.setLevel(logging.INFO)
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with env.auto_time_skipping_disabled():
                yield env
    finally:
        for logger, level in zip(loggers, levels):
            logger.setLevel(level)


@frozen
class LockWait:
    event_type: str | None
    event: str | None
    blockers: list[int]


async def wait_event(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 10), "Fixture synchronization event was not reached"


def backend_id() -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        return cursor.fetchone()[0]


async def setup_organization(*, baseline: bool) -> str:
    def create() -> str:
        org = Organization.objects.create(name="Fixture organization")
        OrganizationEventsRetentionConfig.objects.create(organization=org, default_events_retention_months=1)
        Organization.objects.filter(id=org.id).update(available_product_features=[{"key": "fixture", "limit": 1}])
        if baseline:
            OrganizationEntitlementAppliedState.objects.create(
                organization_id=org.id,
                reactor_key="fixture",
                snapshot=[{"key": "fixture", "limit": 1, "unit": None}],
                applied_at="2026-11-13T00:00:00Z",
            )
        return str(org.id)

    return await database_sync_to_async_pool(create)()


async def set_source(organization_id: str, limit: int) -> None:
    await database_sync_to_async_pool(
        lambda: (
            Organization.objects.using("default")
            .filter(id=organization_id)
            .update(available_product_features=[{"key": "fixture", "limit": limit}])
        )
    )()


async def persisted(organization_id: str) -> dict[str, Any]:
    def read() -> dict[str, Any]:
        return {
            "product": OrganizationEventsRetentionConfig.objects.using("default")
            .get(organization_id=organization_id)
            .default_events_retention_months,
            "applied": [
                [key, snapshot]
                for key, snapshot in OrganizationEntitlementAppliedState.objects.using("default")
                .filter(organization_id=organization_id)
                .values_list("reactor_key", "snapshot")
            ],
            "behind": execution.list_behind_reactor_keys(organization_id),
        }

    return await database_sync_to_async_pool(read)()


def fixture_reactor(change: EntitlementChange) -> None:
    OrganizationEventsRetentionConfig.objects.using("default").filter(organization_id=change.organization_id).update(
        default_events_retention_months=change.current.limit("fixture")
    )


@asynccontextmanager
async def worker(
    env: WorkflowEnvironment,
    react: Callable[[EntitlementChange], None] = fixture_reactor,
    extra_reactors: tuple[EntitlementReactor, ...] = (),
) -> AsyncIterator[str]:
    queue = str(uuid4())
    registry = EntitlementReactorRegistry(
        reactors=(EntitlementReactor(key="fixture", feature_keys=frozenset({"fixture"}), react=react), *extra_reactors)
    )
    with patch.object(execution, "get_entitlement_reactor_registry", return_value=registry):
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[EntitlementReactionsWorkflow],
            activities=[list_behind_entitlement_reactors_activity, execute_entitlement_reactor_activity],
            interceptors=[TestTimeouts()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            yield queue


async def start(
    env: WorkflowEnvironment, queue: str, organization_id: str
) -> WorkflowHandle[Any, EntitlementReactionsResult]:
    return await env.client.start_workflow(
        EntitlementReactionsWorkflow.run,
        EntitlementReactionsInputs(organization_id=organization_id),
        id=str(uuid4()),
        task_queue=queue,
        execution_timeout=timedelta(seconds=40),
        start_signal="resync",
    )


async def test_checkpoint_failure_cannot_hide_product_drift(temporal_environment: WorkflowEnvironment) -> None:
    org = await setup_organization(baseline=True)
    await set_source(org, 2)
    attempts: list[tuple[int, int]] = []

    def react(change: EntitlementChange) -> None:
        attempts.append((activity.info().attempt, backend_id()))
        fixture_reactor(change)

    async with worker(temporal_environment, react) as queue:
        with patch(
            "django.db.models.query.QuerySet.update_or_create", side_effect=RuntimeError("checkpoint fixture failure")
        ):
            handle = await start(temporal_environment, queue, org)
            result = await handle.result()
        assert result.failed_reactor_keys == ["fixture"]
        assert [attempt for attempt, _ in attempts] == [1, 2]
        await set_source(org, 1)
        state = await persisted(org)
        logging.getLogger(__name__).info(json.dumps({"guard": "checkpoint", "attempts": attempts, "state": state}))
        assert state == {
            "product": 1,
            "applied": [["fixture", [{"key": "fixture", "limit": 1, "unit": None}]]],
            "behind": [],
        }


async def reactor_attempts(handle: WorkflowHandle[Any, EntitlementReactionsResult]) -> list[int]:
    history = await handle.fetch_history()
    scheduled = {
        event.event_id
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
        and event.activity_task_scheduled_event_attributes.activity_type.name == "execute-entitlement-reactor"
    }
    return [
        event.activity_task_started_event_attributes.attempt
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED
        and event.activity_task_started_event_attributes.scheduled_event_id in scheduled
    ]


async def test_timed_out_attempt_cannot_overwrite_newer_target(temporal_environment: WorkflowEnvironment) -> None:
    org = await setup_organization(baseline=True)
    await set_source(org, 2)
    captured = threading.Event()
    release = threading.Event()
    first_done = threading.Event()
    trace: list[tuple[int, int, int | None]] = []
    lock = execution._reactor_execution
    execute = execution.execute_entitlement_reactor

    @contextmanager
    def held_entry(organization_id: str, reactor_key: str) -> Iterator[None]:
        info = activity.info()
        initially_observed = execution.load_entitlements(organization_id)
        trace.append((info.attempt, backend_id(), initially_observed.limit("fixture")))
        if info.attempt == 1:
            captured.set()
            assert release.wait(10)
        with lock(organization_id, reactor_key):
            yield

    def tracked_execute(organization_id: str, reactor_key: str) -> execution.ReactorExecutionResult:
        try:
            return execute(organization_id, reactor_key)
        finally:
            if activity.info().attempt == 1:
                first_done.set()

    async with worker(temporal_environment) as queue:
        with (
            patch.object(execution, "_reactor_execution", held_entry),
            patch("posthog.temporal.entitlement_reactions.activities.execute_entitlement_reactor", tracked_execute),
        ):
            try:
                handle = await start(temporal_environment, queue, org)
                await wait_event(captured)
                await set_source(org, 3)
                result = await handle.result()
                assert result.failed_reactor_keys == []
                assert not first_done.is_set()
                before = await persisted(org)
                assert before["product"] == 3
                release.set()
                await wait_event(first_done)
                after = await persisted(org)
                attempts = await reactor_attempts(handle)
                logging.getLogger(__name__).info(
                    json.dumps(
                        {
                            "guard": "overlap",
                            "trace": trace,
                            "before": before,
                            "after": after,
                            "history_attempts": attempts,
                        }
                    )
                )
                assert attempts == [2]
                assert {attempt for attempt, _, _ in trace} == {1, 2}
                assert len({pid for _, pid, _ in trace}) == 2
                assert after["product"] == 3
                assert after["applied"] == [["fixture", [{"key": "fixture", "limit": 3, "unit": None}]]]
                assert after["behind"] == []
            finally:
                release.set()
                await wait_event(first_done)


async def test_retry_waits_for_critical_section_then_reads_fresh(temporal_environment: WorkflowEnvironment) -> None:
    org = await setup_organization(baseline=True)
    await set_source(org, 2)
    captured = threading.Event()
    release = threading.Event()
    retry_entered = threading.Event()
    first_done = threading.Event()
    second_done = threading.Event()
    entries: dict[int, int] = {}
    reads: list[tuple[int, int | None]] = []
    load = execution.load_entitlements
    lock = execution._reactor_execution
    execute = execution.execute_entitlement_reactor

    @contextmanager
    def tracked_entry(organization_id: str, reactor_key: str) -> Iterator[None]:
        attempt = activity.info().attempt
        entries[attempt] = backend_id()
        if attempt == 2:
            retry_entered.set()
        with lock(organization_id, reactor_key):
            yield

    def held_load(organization_id: str) -> Entitlements:
        current = load(organization_id)
        if activity.in_activity() and activity.info().activity_type == "execute-entitlement-reactor":
            attempt = activity.info().attempt
            reads.append((attempt, current.limit("fixture")))
        return current

    def held_reactor(change: EntitlementChange) -> None:
        if activity.info().attempt == 1:
            captured.set()
            assert release.wait(10)
        fixture_reactor(change)

    def tracked_execute(organization_id: str, reactor_key: str) -> execution.ReactorExecutionResult:
        try:
            return execute(organization_id, reactor_key)
        finally:
            if activity.info().attempt == 1:
                first_done.set()
            else:
                second_done.set()

    def lock_wait() -> LockWait:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type, wait_event, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid = %s",
                [entries[2]],
            )
            row = cursor.fetchone()
            return LockWait(event_type=row[0], event=row[1], blockers=row[2])

    async with worker(temporal_environment, held_reactor) as queue:
        with (
            patch.object(execution, "_reactor_execution", tracked_entry),
            patch.object(execution, "load_entitlements", held_load),
            patch("posthog.temporal.entitlement_reactions.activities.execute_entitlement_reactor", tracked_execute),
        ):
            try:
                handle = await start(temporal_environment, queue, org)
                await wait_event(captured)
                await set_source(org, 3)
                assert (await database_sync_to_async_pool(load)(org)).limit("fixture") == 3
                await wait_event(retry_entered)
                async with asyncio.timeout(3):
                    while True:
                        waiting = await database_sync_to_async_pool(lock_wait)()
                        if (waiting.event_type == "Lock" and waiting.event == "advisory") or second_done.is_set():
                            break
                release.set()
                assert (await handle.result()).failed_reactor_keys == []
                await wait_event(first_done)
                state = await persisted(org)
                attempts = await reactor_attempts(handle)
                logging.getLogger(__name__).info(
                    json.dumps(
                        {
                            "guard": "inside_lock",
                            "entries": entries,
                            "reads": reads,
                            "waiting": asdict(waiting),
                            "state": state,
                            "history_attempts": attempts,
                        }
                    )
                )
                assert state["product"] == 3
                assert state["applied"] == [["fixture", [{"key": "fixture", "limit": 3, "unit": None}]]]
                assert state["behind"] == []
                assert entries[1] != entries[2]
                assert reads == [(1, 2), (2, 3)]
                assert attempts == [2]
                assert waiting == LockWait(event_type="Lock", event="advisory", blockers=[entries[1]])
            finally:
                release.set()
                await wait_event(first_done)


async def test_failed_attempt_retries_with_fresh_source(temporal_environment: WorkflowEnvironment) -> None:
    org = await setup_organization(baseline=True)
    await set_source(org, 2)
    first_written = threading.Event()
    release = threading.Event()
    seen: list[tuple[int, int | None]] = []

    def react(change: EntitlementChange) -> None:
        attempt = activity.info().attempt
        seen.append((attempt, change.current.limit("fixture")))
        fixture_reactor(change)
        if attempt == 1:
            first_written.set()
            assert release.wait(10)
            raise RuntimeError("Fixture failure after product write")

    async with worker(temporal_environment, react) as queue:
        try:
            handle = await start(temporal_environment, queue, org)
            await wait_event(first_written)
            await set_source(org, 3)
            release.set()
            assert (await handle.result()).failed_reactor_keys == []
            state = await persisted(org)
            assert seen == [(1, 2), (2, 3)]
            assert state["product"] == 3
            assert state["applied"] == [["fixture", [{"key": "fixture", "limit": 3, "unit": None}]]]
            assert state["behind"] == []
            logging.getLogger(__name__).info(json.dumps({"control": "healthy_retry", "seen": seen, "state": state}))
        finally:
            release.set()


async def test_failure_preserves_successful_sibling_and_reports_required_failure(
    temporal_environment: WorkflowEnvironment,
) -> None:
    org = await setup_organization(baseline=True)
    await set_source(org, 2)
    await database_sync_to_async_pool(
        lambda: OrganizationEntitlementAppliedState.objects.create(
            organization_id=org,
            reactor_key="failure",
            snapshot=[{"key": "fixture", "limit": 1, "unit": None}],
            applied_at="2026-11-13T00:00:00Z",
        )
    )()
    successful_attempts: list[int] = []
    failed_attempts: list[int] = []
    fail = True

    def success(change: EntitlementChange) -> None:
        successful_attempts.append(activity.info().attempt)
        fixture_reactor(change)

    def failure(change: EntitlementChange) -> None:
        failed_attempts.append(activity.info().attempt)
        if fail:
            raise RuntimeError("Fixture reactor failure")
        fixture_reactor(change)

    async with worker(
        temporal_environment,
        success,
        extra_reactors=(EntitlementReactor(key="failure", feature_keys=frozenset({"fixture"}), react=failure),),
    ) as queue:
        handle = await start(temporal_environment, queue, org)
        result = await handle.result()
        state = await persisted(org)
        assert result.failed_reactor_keys == ["failure"]
        assert state["product"] == 2
        assert dict(state["applied"]) == {
            "fixture": [{"key": "fixture", "limit": 2, "unit": None}],
            "failure": [{"key": "fixture", "limit": 1, "unit": None}],
        }
        assert state["behind"] == ["failure"]
        assert successful_attempts == [1]
        assert failed_attempts == [1, 2]
        fail = False
        assert (await (await start(temporal_environment, queue, org)).result()).failed_reactor_keys == []
        assert successful_attempts == [1]
        assert failed_attempts == [1, 2, 1]
        assert (await persisted(org))["behind"] == []


async def test_signals_during_round_coalesce_and_continue_as_new_bounds_history(
    temporal_environment: WorkflowEnvironment,
) -> None:
    org = await setup_organization(baseline=True)
    await database_sync_to_async_pool(
        lambda: OrganizationEntitlementAppliedState.objects.filter(organization_id=org).update(
            snapshot=[{"key": "fixture", "limit": 0, "unit": None}]
        )
    )()
    loop = asyncio.get_running_loop()
    changes: list[int | None] = []
    workflow_id: str | None = None
    started = threading.Event()

    async def request_another_round(value: int) -> None:
        assert workflow_id is not None
        await set_source(org, value)
        handle = temporal_environment.client.get_workflow_handle(workflow_id)
        for _ in range(3):
            await handle.signal("resync")

    def react(change: EntitlementChange) -> None:
        assert started.wait(10)
        value = change.current.limit("fixture")
        changes.append(value)
        fixture_reactor(change)
        assert value is not None
        if value <= 20:
            asyncio.run_coroutine_threadsafe(request_another_round(value + 1), loop).result(10)

    async with worker(temporal_environment, react) as queue:
        handle = await start(temporal_environment, queue, org)
        workflow_id = handle.id
        started.set()
        assert (await handle.result()).failed_reactor_keys == []
        assert changes == list(range(1, 22))
        first_history = await temporal_environment.client.get_workflow_handle(
            handle.id, run_id=handle.result_run_id
        ).fetch_history()
        assert any(
            event.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW
            for event in first_history.events
        )
        state = await persisted(org)
        assert state["product"] == 21
        assert state["applied"] == [["fixture", [{"key": "fixture", "limit": 21, "unit": None}]]]
        assert state["behind"] == []
        assert (await (await start(temporal_environment, queue, org)).result()).failed_reactor_keys == []
        assert changes == list(range(1, 22))
        logging.getLogger(__name__).info(
            json.dumps({"control": "continue_as_new", "round_values": changes, "state": state})
        )


async def test_advisory_lock_timeout_exhausts_retries_without_advancing_state(
    temporal_environment: WorkflowEnvironment,
) -> None:
    org = await setup_organization(baseline=True)
    await set_source(org, 2)
    locked = threading.Event()
    release = threading.Event()
    holder_backend: list[int] = []
    attempts: list[tuple[int, int]] = []
    execute = execution.execute_entitlement_reactor

    def hold_lock() -> None:
        with execution._reactor_execution(org, "fixture"):
            holder_backend.append(backend_id())
            locked.set()
            assert release.wait(10)

    def tracked_execute(organization_id: str, reactor_key: str) -> execution.ReactorExecutionResult:
        attempts.append((activity.info().attempt, backend_id()))
        return execute(organization_id, reactor_key)

    with patch.object(execution, "_REACTOR_LOCK_TIMEOUT_MS", 100):
        holder = asyncio.create_task(database_sync_to_async_pool(hold_lock)())
        try:
            await wait_event(locked)
            async with worker(temporal_environment) as queue:
                with patch(
                    "posthog.temporal.entitlement_reactions.activities.execute_entitlement_reactor", tracked_execute
                ):
                    result = await (await start(temporal_environment, queue, org)).result()
                state = await persisted(org)
                assert result.failed_reactor_keys == ["fixture"]
                assert [attempt for attempt, _ in attempts] == [1, 2]
                assert all(pid != holder_backend[0] for _, pid in attempts)
                assert state["product"] == 1
                assert state["applied"] == [["fixture", [{"key": "fixture", "limit": 1, "unit": None}]]]
                assert state["behind"] == ["fixture"]
                logging.getLogger(__name__).info(
                    json.dumps(
                        {"control": "lock_timeout", "holder": holder_backend, "attempts": attempts, "state": state}
                    )
                )
                release.set()
                await holder
                assert (await (await start(temporal_environment, queue, org)).result()).failed_reactor_keys == []
                assert (await persisted(org))["product"] == 2
        finally:
            release.set()
            await holder
