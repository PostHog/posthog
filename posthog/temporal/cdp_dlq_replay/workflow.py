import json
import asyncio
import hashlib
import datetime as dt
import dataclasses
from typing import Any, Literal

import temporalio.workflow as wf
from temporalio import common

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow

with wf.unsafe.imports_passed_through():
    from django.conf import settings

# The activities run on the Node.js CDP worker (nodejs/src/cdp/dlq-replay/activities.ts), which
# registers them under these names. A rename on either side strands every running replay.
LIST_PARTITIONS_ACTIVITY = "cdp-dlq-replay-list-partitions"
REPLAY_PARTITION_ACTIVITY = "cdp-dlq-replay-partition"

# Keeps the result and the status query far below Temporal's payload limit.
MAX_SKIPPED_LISTED = 100

Decision = Literal["retry", "skip"]


@frozen
class CdpDlqReplayInputs:
    start_timestamp: str
    """ISO datetime. Records parked before it are not read."""
    end_timestamp: str | None = None
    """ISO datetime. Defaults to when the workflow starts, so records parked during a run wait for the next one."""
    team_id: int | None = None
    source_ids: list[str] = dataclasses.field(default_factory=list)
    """Hog function and hog flow ids. A record is replayed only for the ids it names that are listed here."""
    dry_run: bool = False
    """Reads and counts the records in scope, and rebuilds nothing."""
    skip_unreplayable: bool = False
    """Lists a record that cannot be replayed and moves past it, instead of waiting for a decision."""
    topic: str | None = None
    """Defaults to the topic the events consumer parks records on."""
    batch_size: int = 500
    task_queue: str | None = None

    def __post_init__(self) -> None:
        start = dt.datetime.fromisoformat(self.start_timestamp)
        if self.end_timestamp and dt.datetime.fromisoformat(self.end_timestamp) < start:
            raise ValueError("end_timestamp is before start_timestamp")
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")


def replay_workflow_id(inputs: CdpDlqReplayInputs) -> str:
    """The same window, scope and mode always map to the same id, so Temporal can refuse a second run."""
    key = json.dumps(
        {
            "start": inputs.start_timestamp,
            "end": inputs.end_timestamp,
            "team_id": inputs.team_id,
            "source_ids": sorted(inputs.source_ids),
            "topic": inputs.topic,
            "dry_run": inputs.dry_run,
        },
        sort_keys=True,
    )
    return f"cdp-dlq-replay-{hashlib.sha256(key.encode()).hexdigest()[:16]}"


@frozen(frozen=False)
class PartitionReplay:
    """One partition's progress, summed across every activity call the workflow made for it."""

    partition: int
    status: Literal["running", "blocked", "done"] = "running"
    next_offset: int | None = None
    end_offset: int | None = None
    records_read: int = 0
    records_in_scope: int = 0
    records_out_of_scope: int = 0
    records_unreadable: int = 0
    records_skipped: int = 0
    invocations_queued: int = 0
    skipped: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    blocked: dict[str, Any] | None = None

    def absorb(self, result: dict[str, Any]) -> None:
        for count in (
            "records_read",
            "records_in_scope",
            "records_out_of_scope",
            "records_unreadable",
            "records_skipped",
            "invocations_queued",
        ):
            setattr(self, count, getattr(self, count) + result[count])
        self.next_offset = result["next_offset"]
        self.end_offset = result["end_offset"]
        self.blocked = result["blocked"]
        self._list_skipped(result["skipped"])

    def skip_blocked(self) -> None:
        assert self.blocked is not None
        self.records_skipped += 1
        self._list_skipped([self.blocked])
        self.blocked = None

    def _list_skipped(self, entries: list[dict[str, Any]]) -> None:
        self.skipped.extend(entries[: MAX_SKIPPED_LISTED - len(self.skipped)])


@frozen
class CdpDlqReplayResult:
    topic: str
    dry_run: bool
    records_read: int
    records_in_scope: int
    records_skipped: int
    invocations_queued: int
    partitions: list[PartitionReplay]


@wf.defn(name="cdp-dlq-replay")
class CdpDlqReplayWorkflow(PostHogWorkflow):
    """Replays events the CDP events consumer parked on its dead-letter topic.

    Each partition is read from the first record at or after `start_timestamp` to the last one at
    or before `end_timestamp`. The Node.js worker rebuilds the invocations for each record and
    queues them, the same way the events consumer would have.

    A record that still cannot be replayed stops its partition. Everything before it is delivered,
    and the other partitions carry on. The partition then waits for the `retry` signal, sent once
    the fix is deployed, or `skip`, which lists the record and moves past it. `status` shows where
    each partition is.

    Nothing records which windows were replayed except Temporal's history, and replaying the same
    window twice delivers it twice. `python manage.py replay_cdp_dlq` derives the workflow id from
    the inputs, which makes Temporal refuse an identical second run.
    """

    inputs_cls = CdpDlqReplayInputs

    def __init__(self) -> None:
        self._partitions: dict[int, PartitionReplay] = {}
        self._decisions: dict[int, Decision] = {}

    @wf.signal
    def retry(self, partition: int | None = None) -> None:
        """Replays the blocked record again. Without a partition, applies to every blocked one."""
        self._decide("retry", partition)

    @wf.signal
    def skip(self, partition: int | None = None) -> None:
        """Lists the blocked record as skipped and moves past it. Without a partition, applies to every blocked one."""
        self._decide("skip", partition)

    @wf.query
    def status(self) -> list[PartitionReplay]:
        return list(self._partitions.values())

    def _decide(self, decision: Decision, partition: int | None) -> None:
        for state in self._partitions.values():
            if state.status == "blocked" and partition in (None, state.partition):
                self._decisions[state.partition] = decision

    @wf.run
    async def run(self, inputs: CdpDlqReplayInputs) -> CdpDlqReplayResult:
        # Reading a Django setting in a workflow body is normally banned, because it is not part of
        # the recorded history. Temporal does not replay-check the task queue, so a change only
        # redirects later activities.
        task_queue = inputs.task_queue or settings.CDP_DLQ_REPLAY_TASK_QUEUE
        start_ms = int(dt.datetime.fromisoformat(inputs.start_timestamp).timestamp() * 1000)
        end_ms = int(
            (dt.datetime.fromisoformat(inputs.end_timestamp) if inputs.end_timestamp else wf.now()).timestamp() * 1000
        )

        listed: dict[str, Any] = await wf.execute_activity(
            LIST_PARTITIONS_ACTIVITY,
            {"topic": inputs.topic},
            task_queue=task_queue,
            start_to_close_timeout=dt.timedelta(minutes=2),
            retry_policy=common.RetryPolicy(maximum_attempts=3),
        )
        topic: str = listed["topic"]
        for partition in listed["partitions"]:
            self._partitions[partition] = PartitionReplay(partition=partition)

        await asyncio.gather(
            *(
                self._replay_partition(state, topic, inputs, task_queue, start_ms, end_ms)
                for state in self._partitions.values()
            )
        )

        partitions = list(self._partitions.values())
        return CdpDlqReplayResult(
            topic=topic,
            dry_run=inputs.dry_run,
            records_read=sum(p.records_read for p in partitions),
            records_in_scope=sum(p.records_in_scope for p in partitions),
            records_skipped=sum(p.records_skipped for p in partitions),
            invocations_queued=sum(p.invocations_queued for p in partitions),
            partitions=partitions,
        )

    async def _replay_partition(
        self,
        state: PartitionReplay,
        topic: str,
        inputs: CdpDlqReplayInputs,
        task_queue: str,
        start_ms: int,
        end_ms: int,
    ) -> None:
        while True:
            result: dict[str, Any] = await wf.execute_activity(
                REPLAY_PARTITION_ACTIVITY,
                {
                    "topic": topic,
                    "partition": state.partition,
                    "start_timestamp_ms": start_ms,
                    "end_timestamp_ms": end_ms,
                    "from_offset": state.next_offset,
                    "end_offset": state.end_offset,
                    "team_id": inputs.team_id,
                    "source_ids": inputs.source_ids,
                    "dry_run": inputs.dry_run,
                    "skip_unreplayable": inputs.skip_unreplayable,
                    "batch_size": inputs.batch_size,
                },
                task_queue=task_queue,
                start_to_close_timeout=dt.timedelta(hours=6),
                # The activity heartbeats after every batch, and a retry resumes from the last one.
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(minutes=5),
                    maximum_attempts=10,
                ),
            )
            state.absorb(result)
            if state.blocked is None:
                state.status = "done"
                return

            state.status = "blocked"
            wf.logger.warning(
                "cdp_dlq_replay.blocked",
                extra={"partition": state.partition, "offset": state.blocked["offset"]},
            )
            await wf.wait_condition(lambda: state.partition in self._decisions)
            if self._decisions.pop(state.partition) == "skip":
                assert state.next_offset is not None
                state.skip_blocked()
                state.next_offset += 1
            state.blocked = None
            state.status = "running"
