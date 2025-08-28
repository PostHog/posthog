import json
import uuid
import dataclasses

import pytest

from django.conf import settings

import temporalio.converter
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import NoOpInputs
from posthog.temporal.common.codec import EncryptionCodec

from products.batch_exports.backend.temporal.noop import NoOpWorkflow, noop_activity


def get_history_event_payloads(event):
    """Return a history event's payloads if it has any.

    Depending on the event_type, each event has a different attribute to store the payloads (ugh).
    """
    match event.event_type:
        case EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED:
            return event.workflow_execution_started_event_attributes.input.payloads
        case EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED:
            return event.workflow_execution_completed_event_attributes.result.payloads
        case EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            return event.activity_task_scheduled_event_attributes.input.payloads
        case EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            return event.activity_task_completed_event_attributes.result.payloads
        case _:
            return None


@pytest.mark.asyncio
async def test_payloads_are_encrypted():
    """Test the payloads of a Workflow are encrypted when running with EncryptionCodec."""
    codec = EncryptionCodec(settings=settings)
    client = await Client.connect(
        f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}",
        namespace=settings.TEMPORAL_NAMESPACE,
        data_converter=dataclasses.replace(temporalio.converter.default(), payload_codec=codec),
    )

    workflow_id = uuid.uuid4()
    input_str = str(uuid.uuid4())

    no_op_result_str = f"OK - {input_str}"
    inputs = NoOpInputs(
        arg=input_str,
        batch_export_id="123",
        team_id=1,
        backfill_details=None,
    )

    # The no-op Workflow can only produce a limited set of results, so we'll check if the events match any of these.
    # Either it's the final result (no_op_result_str), the input to an activity (no_op_activity_input_str), or the
    # input to the workflow (inputs).
    expected_results = (
        no_op_result_str,
        {"arg": input_str, "backfill_details": None},
        dataclasses.asdict(inputs),
    )

    async with Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[NoOpWorkflow],
        activities=[noop_activity],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ) as worker:
        handle = await client.start_workflow(
            NoOpWorkflow.run,
            inputs,
            id=f"workflow-{workflow_id}",
            task_queue=worker.task_queue,
        )

        result = await handle.result()
        assert result == no_op_result_str

        async for event in handle.fetch_history_events():
            payloads = get_history_event_payloads(event)

            if not payloads:
                continue

            payload = payloads[0]
            assert payload.metadata["encoding"] == b"binary/encrypted"

            decoded_payloads = await codec.decode([payload])
            loaded_payload = json.loads(decoded_payloads[0].data)
            assert loaded_payload in expected_results
