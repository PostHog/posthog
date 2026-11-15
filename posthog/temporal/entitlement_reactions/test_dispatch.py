import json
import asyncio
import logging
import threading
from collections.abc import Iterator
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
from posthog.models.organization_entitlement_applied_state import OrganizationEntitlementAppliedState
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.entitlement_reactions.activities import (
    execute_entitlement_reactor_activity,
    list_behind_entitlement_reactors_activity,
)
from posthog.temporal.entitlement_reactions.test_workflow import (
    TestTimeouts,
    persisted,
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
        if "elapsed" in state:
            state["elapsed"][0] += 239
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


async def test_failed_checkpoint_redelivery_waits_for_success(temporal_environment, integration) -> None:
    organization_id = await setup_organization(baseline=True)
    instance = consumer()
    body = message(organization_id, [{"key": "fixture", "limit": 2}])
    with patch("posthog.entitlements.dispatch.async_connect", AsyncMock(return_value=temporal_environment.client)):
        async with Worker(
            temporal_environment.client,
            task_queue=settings.BILLING_TASK_QUEUE,
            workflows=[EntitlementReactionsWorkflow],
            activities=[list_behind_entitlement_reactors_activity, execute_entitlement_reactor_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            interceptors=[TestTimeouts()],
        ):
            with patch(
                "django.db.models.query.QuerySet.update_or_create",
                side_effect=RuntimeError("checkpoint fixture failure"),
            ):
                await process(instance, body)
            assert not instance.sqs.delete_message.called
            failed = await persisted(organization_id)
            assert failed["product"] == 1
            assert failed["behind"] == ["fixture"]
            integration["held"] = threading.Event()
            integration["release"] = threading.Event()
            pending = asyncio.create_task(process(instance, body))
            try:
                await wait_event(integration["held"])
                assert not instance.sqs.delete_message.called
            finally:
                integration["release"].set()
            await pending
            assert instance.sqs.delete_message.call_args.kwargs["ReceiptHandle"] == "receipt"
            succeeded = await persisted(organization_id)
            assert succeeded["product"] == 2
            assert succeeded["behind"] == []
            await process(instance, body)
            assert integration["seen"] == [2, 2, 2]


@pytest.mark.parametrize("failure", ["handoff", "handoff-timeout", "timeout", "flag"])
async def test_transport_failure_withholds_receipt(
    temporal_environment, integration, monkeypatch, failure: str
) -> None:
    organization_id = await setup_organization(baseline=True)
    instance = consumer()
    if failure == "flag":
        monkeypatch.setattr(dispatch, "feature_enabled_or_false", MagicMock(side_effect=RuntimeError("flag")))
    connect = (
        AsyncMock(side_effect=RuntimeError("handoff"))
        if failure == "handoff"
        else AsyncMock(return_value=temporal_environment.client)
    )
    if failure == "handoff-timeout":
        monkeypatch.setattr(dispatch, "HANDOFF_TIMEOUT_SECONDS", 0.05)

        async def stall() -> None:
            await asyncio.Event().wait()

        connect.side_effect = stall
    if failure == "timeout":
        monkeypatch.setattr(dispatch, "COMPLETION_TIMEOUT_SECONDS", 0.1)
        integration["held"] = threading.Event()
        integration["release"] = threading.Event()
    with patch("posthog.entitlements.dispatch.async_connect", connect):
        async with Worker(
            temporal_environment.client,
            task_queue=settings.BILLING_TASK_QUEUE,
            workflows=[EntitlementReactionsWorkflow],
            activities=[list_behind_entitlement_reactors_activity, execute_entitlement_reactor_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            interceptors=[TestTimeouts()],
        ):
            try:
                await process(instance, message(organization_id, [{"key": "fixture", "limit": 2}]))
                assert not instance.sqs.delete_message.called
                if failure == "timeout":
                    await wait_event(integration["held"])
            finally:
                if integration["release"]:
                    integration["release"].set()
            if failure == "timeout":
                handle = temporal_environment.client.get_workflow_handle(f"entitlement-reactions-{organization_id}")
                await handle.result()
                assert (await persisted(organization_id))["product"] == 2


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
    with patch(
        "posthog.entitlements.dispatch.async_connect", AsyncMock(side_effect=AssertionError("No handoff required"))
    ):
        await process(instance, message(organization_id, features))
    assert instance.sqs.delete_message.called
    assert integration["seen"] == []


async def test_best_effort_and_strict_transaction_visibility(temporal_environment, integration) -> None:
    organization_id = await setup_organization(baseline=True)

    def update() -> None:
        with transaction.atomic():
            org = Organization.objects.get(id=organization_id)
            BillingManager(None).update_org_details(
                org, cast(BillingStatus, {"customer": {"available_product_features": [{"key": "fixture", "limit": 2}]}})
            )
            assert (
                OrganizationEntitlementAppliedState.objects.get(organization_id=organization_id).snapshot[0]["limit"]
                == 1
            )

    with patch("posthog.entitlements.dispatch.async_connect", AsyncMock(return_value=temporal_environment.client)):
        async with Worker(
            temporal_environment.client,
            task_queue=settings.BILLING_TASK_QUEUE,
            workflows=[EntitlementReactionsWorkflow],
            activities=[list_behind_entitlement_reactors_activity, execute_entitlement_reactor_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            interceptors=[TestTimeouts()],
        ):
            await database_sync_to_async_pool(update)()
            await temporal_environment.client.get_workflow_handle(f"entitlement-reactions-{organization_id}").result()
            assert (await persisted(organization_id))["product"] == 2

    def strict() -> None:
        with transaction.atomic():
            instance = consumer()
            with (
                patch("ee.billing.queue.BillingConsumer.close_old_connections"),
                patch("ee.billing.queue.BillingConsumer.get_cached_instance_license", return_value=None),
            ):
                instance.process_message(message(organization_id, [{"key": "fixture", "limit": 3}]))
            assert not instance.sqs.delete_message.called

    await database_sync_to_async_pool(strict)()
    assert (await persisted(organization_id))["behind"] == ["fixture"]


async def test_serial_prefetch_stays_within_receipt_visibility(
    temporal_environment, integration, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=__name__)
    ids = [await setup_organization(baseline=True), await setup_organization(baseline=True)]
    instance = consumer()
    messages = [message(org_id, [{"key": "fixture", "limit": 2}], f"receipt-{n}") for n, org_id in enumerate(ids)]
    elapsed = [0]
    deleted: list[tuple[str, int]] = []
    leased: dict[str, int] = {}
    integration["elapsed"] = elapsed

    def receive(**kwargs: Any) -> dict[str, Any]:
        batch = messages[: kwargs["MaxNumberOfMessages"]]
        del messages[: kwargs["MaxNumberOfMessages"]]
        for body in batch:
            leased[body["ReceiptHandle"]] = elapsed[0]
        return {"Messages": batch}

    instance.sqs.receive_message.side_effect = receive
    instance.sqs.delete_message.side_effect = lambda **kw: deleted.append(
        (kw["ReceiptHandle"], elapsed[0] - leased[kw["ReceiptHandle"]])
    )
    with (
        patch("posthog.entitlements.dispatch.async_connect", AsyncMock(return_value=temporal_environment.client)),
        patch("ee.billing.queue.BillingConsumer.get_cached_instance_license", return_value=None),
    ):
        async with Worker(
            temporal_environment.client,
            task_queue=settings.BILLING_TASK_QUEUE,
            workflows=[EntitlementReactionsWorkflow],
            activities=[list_behind_entitlement_reactors_activity, execute_entitlement_reactor_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            interceptors=[TestTimeouts()],
        ):
            await database_sync_to_async_pool(instance.run)(continuous=False)
            await database_sync_to_async_pool(instance.run)(continuous=False)
    logging.getLogger(__name__).info(
        "VISIBILITY_OBSERVATION %s",
        {"requested": instance.sqs.receive_message.call_args.kwargs["MaxNumberOfMessages"], "deleted": deleted},
    )
    assert len(deleted) == 2
    assert [receipt for receipt, age in deleted if age >= 300] == []
    assert (await persisted(ids[0]))["product"] == 2
    assert (await persisted(ids[1]))["product"] == 2


async def test_reversal_during_running_reaction_remains_discoverable(temporal_environment, integration) -> None:
    organization_id = await setup_organization(baseline=True)
    instance = consumer()
    integration["held"] = threading.Event()
    integration["release"] = threading.Event()
    with patch("posthog.entitlements.dispatch.async_connect", AsyncMock(return_value=temporal_environment.client)):
        async with Worker(
            temporal_environment.client,
            task_queue=settings.BILLING_TASK_QUEUE,
            workflows=[EntitlementReactionsWorkflow],
            activities=[list_behind_entitlement_reactors_activity, execute_entitlement_reactor_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            interceptors=[TestTimeouts()],
        ):
            pending = asyncio.create_task(
                process(instance, message(organization_id, [{"key": "fixture", "limit": 2}], "forward"))
            )
            try:
                await wait_event(integration["held"])
                await process(instance, message(organization_id, [{"key": "fixture", "limit": 1}], "reverse"))
            finally:
                integration["release"].set()
            await pending
            state = await persisted(organization_id)
            assert state["product"] == 2
            assert state["behind"] == ["fixture"]
            await process(instance, message(organization_id, [{"key": "fixture", "limit": 1}], "retry"))
            assert (await persisted(organization_id))["product"] == 1
            assert (await persisted(organization_id))["behind"] == []


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


async def test_no_registry_keeps_native_receive_batch(integration, monkeypatch) -> None:
    monkeypatch.setattr(dispatch, "get_entitlement_reactor_registry", lambda: EntitlementReactorRegistry(reactors=()))
    instance = consumer()
    instance.sqs.receive_message.return_value = {"Messages": []}
    instance.receive_messages(max_messages=7)
    assert instance.sqs.receive_message.call_args.kwargs["MaxNumberOfMessages"] == 7


async def test_older_message_waits_for_stored_entitlements(
    temporal_environment: WorkflowEnvironment, integration: dict[str, Any]
) -> None:
    organization_id = await setup_organization(baseline=True)
    stored_features = [{"key": "fixture", "limit": 2}]
    stored_usage = {"billing_status_computed_at": "2026-11-14T10:00:00+00:00"}
    await database_sync_to_async_pool(Organization.objects.filter(id=organization_id).update)(
        available_product_features=stored_features, usage=stored_usage
    )
    before = await persisted(organization_id)
    instance = consumer()
    body = message(organization_id, [{"key": "fixture", "limit": 3}])
    payload = json.loads(body["Body"])
    payload["data"]["computed_at"] = "2026-11-14T09:00:00+00:00"
    body["Body"] = json.dumps(payload)
    connect = AsyncMock(side_effect=RuntimeError("Handoff failed"))
    with patch("posthog.entitlements.dispatch.async_connect", connect):
        await process(instance, body)
        assert not instance.sqs.delete_message.called
        assert await persisted(organization_id) == before

        connect.side_effect = None
        connect.return_value = temporal_environment.client
        async with Worker(
            temporal_environment.client,
            task_queue=settings.BILLING_TASK_QUEUE,
            workflows=[EntitlementReactionsWorkflow],
            activities=[list_behind_entitlement_reactors_activity, execute_entitlement_reactor_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
            interceptors=[TestTimeouts()],
        ):
            await process(instance, body)
    assert instance.sqs.delete_message.called
    after = await persisted(organization_id)
    assert after["product"] == 2
    assert after["behind"] == []
    organization = await database_sync_to_async_pool(Organization.objects.get)(id=organization_id)
    assert organization.available_product_features == stored_features
    assert organization.usage == stored_usage
