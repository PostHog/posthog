import json
import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.db import transaction

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.entitlements import dispatch, execution, repair
from posthog.entitlements.contracts import EntitlementChange, EntitlementReactor
from posthog.entitlements.registry import EntitlementReactorRegistry
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig
from posthog.models.organization import Organization
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.entitlement_reactions.activities import (
    execute_entitlement_reactor_activity,
    list_behind_entitlement_reactors_activity,
)
from posthog.temporal.entitlement_reactions.test_workflow import (
    TestTimeouts,
    persisted,
    set_source,
    setup_organization,
    temporal_environment as temporal_environment,
    wait_event,
)
from posthog.temporal.entitlement_reactions.workflow import EntitlementReactionsWorkflow

from ee.billing import billing_manager
from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import BillingStatus
from ee.billing.queue.BillingConsumer import BillingConsumer

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def integration(monkeypatch) -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {"fail": False, "held": None, "release": None, "seen": []}

    def react(change: EntitlementChange) -> None:
        state["seen"].append(change.current.limit("fixture"))
        if state["held"]:
            state["held"].set()
            assert state["release"].wait(10)
        OrganizationEventsRetentionConfig.objects.using("default").filter(
            organization_id=change.organization_id
        ).update(default_events_retention_months=change.current.limit("fixture"))
        if state["fail"]:
            raise RuntimeError("Fixture reactor failure")

    registry = EntitlementReactorRegistry(
        reactors=(EntitlementReactor(key="fixture", feature_keys=frozenset({"fixture"}), react=react),)
    )
    for module in (dispatch, execution, repair, billing_manager):
        monkeypatch.setattr(module, "get_entitlement_reactor_registry", lambda: registry)
    monkeypatch.setattr(dispatch, "feature_enabled_or_false", lambda *a, **kw: True)
    yield state


class FixtureBillingConsumer(BillingConsumer):
    sqs: MagicMock


def consumer() -> FixtureBillingConsumer:
    with patch("ee.sqs.SQSConsumer.boto3"):
        instance = FixtureBillingConsumer(queue_url="https://example.com/queue")
    return instance


def message(organization_id: str, features: list[dict[str, Any]], receipt: str = "receipt") -> dict[str, Any]:
    return {
        "MessageId": receipt,
        "ReceiptHandle": receipt,
        "Body": json.dumps(
            {
                "type": "billing_customer_update",
                "organization_id": organization_id,
                "data": {"customer": {"available_product_features": features}},
            }
        ),
    }


async def process(instance: BillingConsumer, body: dict[str, Any]) -> None:
    with patch("ee.billing.queue.BillingConsumer.get_cached_instance_license", return_value=None):
        await database_sync_to_async_pool(instance.process_message)(body)


def deleted_receipts(instance: FixtureBillingConsumer) -> list[str]:
    return [call.kwargs["ReceiptHandle"] for call in instance.sqs.delete_message.call_args_list]


@asynccontextmanager
async def billing_task_worker(env: WorkflowEnvironment) -> AsyncIterator[AsyncMock]:
    connect = AsyncMock(return_value=env.client)
    with patch("posthog.entitlements.dispatch.async_connect", connect):
        async with Worker(
            env.client,
            task_queue=settings.BILLING_TASK_QUEUE,
            workflows=[EntitlementReactionsWorkflow],
            activities=[list_behind_entitlement_reactors_activity, execute_entitlement_reactor_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            interceptors=[TestTimeouts()],
        ):
            yield connect


async def wait_for_reactions(env: WorkflowEnvironment, organization_id: str) -> None:
    await env.client.get_workflow_handle(f"entitlement-reactions-{organization_id}").result()


async def stored_features(organization_id: str) -> list[dict[str, Any]]:
    return await database_sync_to_async_pool(
        lambda: Organization.objects.values_list("available_product_features", flat=True).get(id=organization_id)
    )()


async def behind_organization_ids() -> list[str]:
    return (await database_sync_to_async_pool(repair.list_behind_organizations_page)(None)).organization_ids


async def test_failed_reaction_acknowledges_and_stays_discoverable(temporal_environment, integration) -> None:
    organization_id = await setup_organization(baseline=True)
    integration["fail"] = True
    instance = consumer()
    async with billing_task_worker(temporal_environment):
        await process(instance, message(organization_id, [{"key": "fixture", "limit": 2}]))
        assert deleted_receipts(instance) == ["receipt"]
        await wait_for_reactions(temporal_environment, organization_id)
    assert integration["seen"] == [2, 2]
    assert organization_id in await behind_organization_ids()


@pytest.mark.parametrize("failure", ["handoff", "handoff-timeout"])
async def test_dispatch_failure_acknowledges_and_stays_discoverable(integration, monkeypatch, failure: str) -> None:
    organization_id = await setup_organization(baseline=False)
    instance = consumer()
    connect = AsyncMock(side_effect=RuntimeError("handoff"))
    if failure == "handoff-timeout":
        monkeypatch.setattr(dispatch, "HANDOFF_TIMEOUT_SECONDS", 0.05)

        async def stall() -> None:
            await asyncio.Event().wait()

        connect.side_effect = stall
    with patch("posthog.entitlements.dispatch.async_connect", connect):
        await process(instance, message(organization_id, [{"key": "fixture", "limit": 2}]))
    assert connect.called
    assert deleted_receipts(instance) == ["receipt"]
    assert await stored_features(organization_id) == [{"key": "fixture", "limit": 2}]
    assert (await persisted(organization_id))["applied"] == [
        ["fixture", [{"key": "fixture", "limit": 1, "unit": None}]]
    ]
    assert organization_id in await behind_organization_ids()


async def test_flag_failure_acknowledges_on_legacy_path(integration, monkeypatch) -> None:
    organization_id = await setup_organization(baseline=False)
    monkeypatch.setattr(dispatch, "feature_enabled_or_false", MagicMock(side_effect=RuntimeError("flag")))
    instance = consumer()
    connect = AsyncMock()
    with patch("posthog.entitlements.dispatch.async_connect", connect):
        await process(instance, message(organization_id, [{"key": "fixture", "limit": 2}]))
    assert not connect.called
    assert deleted_receipts(instance) == ["receipt"]
    assert await stored_features(organization_id) == [{"key": "fixture", "limit": 2}]
    assert (await persisted(organization_id))["applied"] == []


@pytest.mark.parametrize("case", ["empty", "flag-off", "no-registry", "presentation", "unwatched", "baseline"])
async def test_no_work_acknowledges_without_temporal(integration, monkeypatch, case: str) -> None:
    organization_id = await setup_organization(baseline=True)
    features: list[dict[str, Any]] = [{"key": "fixture", "limit": 1}]
    if case == "empty":
        features = []
    elif case in ("flag-off", "no-registry"):
        features[0]["limit"] = 2
        if case == "flag-off":
            monkeypatch.setattr(dispatch, "feature_enabled_or_false", lambda *a, **kw: False)
        else:
            monkeypatch.setattr(
                dispatch, "get_entitlement_reactor_registry", lambda: EntitlementReactorRegistry(reactors=())
            )
    elif case == "presentation":
        features[0]["name"] = "New name"
    elif case == "unwatched":
        features.append({"key": "other", "limit": 2})
    instance = consumer()
    connect = AsyncMock()
    with patch("posthog.entitlements.dispatch.async_connect", connect):
        await process(instance, message(organization_id, features))
    assert not connect.called
    assert instance.sqs.delete_message.called
    assert integration["seen"] == []


async def test_unchanged_write_with_behind_checkpoint_starts_workflow(integration) -> None:
    organization_id = await setup_organization(baseline=True)
    await set_source(organization_id, 2)
    instance = consumer()
    connect = AsyncMock()
    with patch("posthog.entitlements.dispatch.async_connect", connect):
        await process(instance, message(organization_id, [{"key": "fixture", "limit": 2}]))
    start_workflow = connect.return_value.start_workflow
    assert start_workflow.call_count == 1
    assert start_workflow.call_args.kwargs["id"] == f"entitlement-reactions-{organization_id}"


async def test_dispatch_waits_for_caller_commit(temporal_environment, integration) -> None:
    organization_id = await setup_organization(baseline=True)
    async with billing_task_worker(temporal_environment) as connect:

        def update() -> None:
            with transaction.atomic(using="default"):
                BillingManager(None).update_org_details(
                    Organization.objects.get(id=organization_id),
                    cast(BillingStatus, {"customer": {"available_product_features": [{"key": "fixture", "limit": 2}]}}),
                )
                assert connect.call_count == 0
            assert connect.call_count == 1

        await database_sync_to_async_pool(update)()
        await wait_for_reactions(temporal_environment, organization_id)
    assert (await persisted(organization_id))["product"] == 2


async def test_reversal_during_running_reaction_converges(temporal_environment, integration) -> None:
    organization_id = await setup_organization(baseline=True)
    instance = consumer()
    integration["held"] = threading.Event()
    integration["release"] = threading.Event()
    async with billing_task_worker(temporal_environment):
        pending = asyncio.create_task(
            process(instance, message(organization_id, [{"key": "fixture", "limit": 2}], "forward"))
        )
        try:
            await wait_event(integration["held"])
            await process(instance, message(organization_id, [{"key": "fixture", "limit": 1}], "reverse"))
        finally:
            integration["release"].set()
        await pending
        await wait_for_reactions(temporal_environment, organization_id)
    assert await stored_features(organization_id) == [{"key": "fixture", "limit": 1}]
    state = await persisted(organization_id)
    assert state["product"] == 1
    assert state["behind"] == []


@pytest.mark.parametrize("failure", ["flag", "handoff"])
async def test_best_effort_billing_refresh_survives_dispatch_errors(integration, monkeypatch, failure: str) -> None:
    organization_id = await setup_organization(baseline=True)
    if failure == "flag":
        monkeypatch.setattr(dispatch, "feature_enabled_or_false", MagicMock(side_effect=RuntimeError("flag")))

    def update() -> None:
        org = Organization.objects.get(id=organization_id)
        BillingManager(None).update_org_details(
            org, cast(BillingStatus, {"customer": {"available_product_features": [{"key": "fixture", "limit": 2}]}})
        )
        assert Organization.objects.get(id=organization_id).available_product_features[0]["limit"] == 2

    with patch("posthog.entitlements.dispatch.async_connect", AsyncMock(side_effect=RuntimeError("handoff"))):
        await database_sync_to_async_pool(update)()
    assert (await persisted(organization_id))["behind"] == ["fixture"]


async def test_consumer_requests_full_batch_with_reactor_registered(integration) -> None:
    instance = consumer()
    instance.sqs.receive_message.return_value = {"Messages": []}
    instance.receive_messages(max_messages=10)
    assert instance.sqs.receive_message.call_args.kwargs["MaxNumberOfMessages"] == 10
