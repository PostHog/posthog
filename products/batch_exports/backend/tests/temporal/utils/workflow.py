import uuid
import contextlib

import pytest

from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import create_batch_export_run

from products.batch_exports.backend.temporal.batch_exports import StartBatchExportRunInputs


@activity.defn(name="start_batch_export_run")
async def mocked_start_batch_export_run(inputs: StartBatchExportRunInputs) -> str:
    """Create a run and return some count >0 to avoid early return."""
    run = await sync_to_async(create_batch_export_run)(
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        status=BatchExportRun.Status.STARTING,
    )

    return str(run.id)


@contextlib.contextmanager
def fail_on_application_error():
    """Context manager to fail the test if an application error is raised.

    Tests typically fail if a WorkflowFailureError is raised, but the error traceback you get back is not very helpful
    as it just contains the traceback from within Temporal's own code.
    This context manager will parse the error and fail the test with a more helpful message and trackback from our own
    code, which helps debug the issue.
    """
    try:
        yield
    except WorkflowFailureError as e:
        # try to parse the root cause of the error in case it's an error from our own code
        if isinstance(e.cause, ActivityError):
            if isinstance(e.cause.cause, ApplicationError):
                message = e.cause.cause.message
                error_type = e.cause.cause.type
                failure = e.cause.cause.failure
                stack_trace = failure.stack_trace if failure else None

                detailed_error = (
                    f"Workflow failed with an ApplicationError:\n\n"
                    f"  Error: {message}\n\n"
                    f"  Error Type: {error_type}\n"
                )
                if stack_trace:
                    detailed_error += f"  Error Stack Trace: {stack_trace}\n"

                pytest.fail(detailed_error)
        # not an application error, re-raise (which will also cause the test to fail)
        raise
