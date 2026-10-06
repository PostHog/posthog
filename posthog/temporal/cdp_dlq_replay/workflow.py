import datetime as dt
from typing import Any

import temporalio.workflow as wf
from temporalio import common

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with wf.unsafe.imports_passed_through():
    from django.conf import settings

# The activity runs on the Node.js CDP worker (nodejs/src/cdp/dlq-replay/activities.ts), which
# registers it under this name. A rename on either side strands every running replay.
REPLAY_ACTIVITY = "cdp-dlq-replay"

# One replay at a time: two would read the same records and deliver them twice.
REPLAY_WORKFLOW_ID = "cdp-dlq-replay"


@frozen
class CdpDlqReplayInputs:
    skip_unreplayable: bool = False
    """Commit past a record that still cannot be replayed, and list it, instead of stopping at it."""
    task_queue: str | None = None


@frozen
class CdpDlqReplayResult:
    records_read: int
    records_skipped: int
    invocations_queued: int
    skipped: list[dict[str, Any]]
    """Partition, offset and reason of each record skipped with skip_unreplayable, up to 100."""


@wf.defn(name="cdp-dlq-replay")
class CdpDlqReplayWorkflow(PostHogWorkflow):
    """Replays the events the CDP events consumer parked on its dead-letter topic.

    One activity on the Node.js CDP worker drains every partition from where the last replay
    committed to the end of the topic as it stood when this one began. It rebuilds the invocations
    for each record and queues them, the same way the events consumer would have.

    A record that still cannot be replayed fails the run, naming its partition and offset.
    Everything before that record is committed, so starting the replay again after the fix picks up
    at it.
    """

    inputs_cls = CdpDlqReplayInputs
    inputs_optional = True

    @wf.run
    async def run(self, inputs: CdpDlqReplayInputs) -> CdpDlqReplayResult:
        # Reading a Django setting in a workflow body is normally banned, because it is not part of
        # the recorded history. Temporal does not replay-check the task queue, so a change only
        # redirects later activities.
        task_queue = inputs.task_queue or settings.CDP_DLQ_REPLAY_TASK_QUEUE

        result: dict[str, Any] = await wf.execute_activity(
            REPLAY_ACTIVITY,
            {"skip_unreplayable": inputs.skip_unreplayable},
            task_queue=task_queue,
            start_to_close_timeout=dt.timedelta(hours=6),
            # The activity heartbeats after every batch, and a retry starts from the last commit.
            heartbeat_timeout=dt.timedelta(minutes=2),
            retry_policy=common.RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(minutes=5),
                maximum_attempts=10,
            ),
        )
        return CdpDlqReplayResult(
            records_read=result["records_read"],
            records_skipped=result["records_skipped"],
            invocations_queued=result["invocations_queued"],
            skipped=result["skipped"],
        )
