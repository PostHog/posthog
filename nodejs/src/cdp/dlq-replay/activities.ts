import { ApplicationFailure, Context } from '@temporalio/activity'
import { Message } from 'node-rdkafka'

import type { CdpDlqReplayer } from './cdp-dlq-replayer'
import { UnreplayableRecordsError } from './cdp-dlq-replayer'
import type { DlqPartitionReader } from './partition-reader'

/** Names the Python workflow calls these by. Changing one strands every workflow that is running. */
export const LIST_PARTITIONS_ACTIVITY = 'cdp-dlq-replay-list-partitions'
export const REPLAY_PARTITION_ACTIVITY = 'cdp-dlq-replay-partition'

const BATCH_SIZE = 500
/** Keeps the result far below Temporal's payload limit however many records a run skips. */
const MAX_SKIPPED_LISTED = 100
const MAX_ERROR_LENGTH = 500

export interface ReplayPartitionInput {
    partition: number
    skip_unreplayable?: boolean
}

export interface SkippedRecord {
    offset: number
    error: string
}

export interface ReplayPartitionResult {
    partition: number
    records_read: number
    records_skipped: number
    invocations_queued: number
    skipped: SkippedRecord[]
}

export interface ReplayActivityContext {
    heartbeat(): void
    readonly cancellationSignal: AbortSignal
}

export interface ReplayActivityDeps {
    replayer: Pick<CdpDlqReplayer, 'replayBatch'>
    openReader: () => Promise<DlqPartitionReader>
    topic: string
}

const truncate = (error: unknown): string =>
    String(error instanceof Error ? error.message : error).slice(0, MAX_ERROR_LENGTH)

export async function listPartitions(deps: ReplayActivityDeps): Promise<number[]> {
    const reader = await deps.openReader()
    try {
        return await reader.partitions(deps.topic)
    } finally {
        await reader.close()
    }
}

/**
 * Replays one partition from where the last replay committed to the end of the topic as it stood
 * when this one began. Records parked while it runs are left for the next replay.
 *
 * The offset is committed after every queued batch, so a retry or the next replay never sends a
 * committed record again. At most the batch in flight when a pod dies is sent twice, which is the
 * same guarantee the events consumer gives.
 *
 * A record that still cannot be replayed fails the activity without retries, naming its offset.
 * Everything before it is committed, so running the replay again after the fix starts at it.
 */
export async function replayPartition(
    deps: ReplayActivityDeps,
    input: ReplayPartitionInput,
    context: ReplayActivityContext
): Promise<ReplayPartitionResult> {
    const { topic } = deps
    const { partition } = input
    const result: ReplayPartitionResult = {
        partition,
        records_read: 0,
        records_skipped: 0,
        invocations_queued: 0,
        skipped: [],
    }

    const reader = await deps.openReader()
    try {
        const end = await reader.highWatermark(topic, partition)
        let next = await reader.startOffset(topic, partition)
        if (next < end) {
            reader.seek(topic, partition, next)
        }
        while (next < end) {
            context.cancellationSignal.throwIfAborted()
            const batch = (await reader.read(Math.min(BATCH_SIZE, end - next))).filter(
                (message) => message.offset < end
            )
            if (!batch.length) {
                break
            }
            result.records_read += batch.length
            next = await replayRecords(deps, reader, batch, input, result)
            context.heartbeat()
        }
        return result
    } finally {
        await reader.close()
    }
}

/** Replays a batch and commits past it. Returns the offset to continue from. */
async function replayRecords(
    deps: ReplayActivityDeps,
    reader: DlqPartitionReader,
    batch: Message[],
    input: ReplayPartitionInput,
    result: ReplayPartitionResult
): Promise<number> {
    const { topic } = deps
    const commitAfter = (message: Message): number => {
        reader.commit(topic, input.partition, message.offset + 1)
        return message.offset + 1
    }

    try {
        result.invocations_queued += (await deps.replayer.replayBatch(batch)).queued
        return commitAfter(batch[batch.length - 1])
    } catch (error) {
        // Any other error can come after part of the batch was queued, so replaying it again
        // record by record would deliver that part twice. It fails the attempt instead, and the
        // retry starts from the last commit.
        if (!(error instanceof UnreplayableRecordsError)) {
            throw error
        }
    }

    // Nothing from the batch was queued, so each record can go on its own. Two records for the same
    // event name different sources, so replaying them apart rebuilds nothing twice.
    let next = batch[0].offset
    for (const message of batch) {
        try {
            result.invocations_queued += (await deps.replayer.replayBatch([message])).queued
        } catch (error) {
            if (!(error instanceof UnreplayableRecordsError)) {
                throw error
            }
            if (!input.skip_unreplayable) {
                throw ApplicationFailure.nonRetryable(
                    `Partition ${input.partition} offset ${message.offset} cannot be replayed: ${truncate(error)}`,
                    'UnreplayableRecord'
                )
            }
            result.records_skipped += 1
            if (result.skipped.length < MAX_SKIPPED_LISTED) {
                result.skipped.push({ offset: message.offset, error: truncate(error) })
            }
        }
        next = commitAfter(message)
    }
    return next
}

export function createReplayActivities(deps: ReplayActivityDeps): Record<string, (input: any) => Promise<unknown>> {
    return {
        [LIST_PARTITIONS_ACTIVITY]: () => listPartitions(deps),
        [REPLAY_PARTITION_ACTIVITY]: (input: ReplayPartitionInput) => {
            const context = Context.current()
            return replayPartition(deps, input, {
                heartbeat: () => context.heartbeat(),
                cancellationSignal: context.cancellationSignal,
            })
        },
    }
}
