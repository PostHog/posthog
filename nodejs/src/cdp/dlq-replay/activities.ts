import { ApplicationFailure, Context } from '@temporalio/activity'
import { Message } from 'node-rdkafka'

import type { CdpDlqReplayer } from './cdp-dlq-replayer'
import { UnreplayableRecordsError } from './cdp-dlq-replayer'
import type { DlqPartitionReader } from './partition-reader'

/** The name the Python workflow calls this by. Changing it strands every workflow that is running. */
export const REPLAY_ACTIVITY = 'cdp-dlq-replay'

const BATCH_SIZE = 500
/** Keeps the result far below Temporal's payload limit however many records a run skips. */
const MAX_SKIPPED_LISTED = 100
const MAX_ERROR_LENGTH = 500

export interface ReplayInput {
    skip_unreplayable?: boolean
}

export interface SkippedRecord {
    partition: number
    offset: number
    error: string
}

export interface ReplayResult {
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

/**
 * Replays every partition from where the last replay committed to the end of the topic as it stood
 * when this one began. Records parked while it runs are left for the next replay.
 *
 * The offset is committed after every queued batch, so a retry or the next replay never sends a
 * committed record again. At most the batch in flight when a pod dies is sent twice, which is the
 * same guarantee the events consumer gives.
 *
 * A record that still cannot be replayed fails the activity without retries, naming its partition
 * and offset. Everything before it is committed, so running the replay again after the fix starts
 * at it.
 */
export async function replayTopic(
    deps: ReplayActivityDeps,
    input: ReplayInput,
    context: ReplayActivityContext
): Promise<ReplayResult> {
    const { topic } = deps
    const result: ReplayResult = { records_read: 0, records_skipped: 0, invocations_queued: 0, skipped: [] }

    const reader = await deps.openReader()
    try {
        const ends = new Map<number, number>()
        const starts = new Map<number, number>()
        for (const partition of await reader.partitions(topic)) {
            const [start, end] = [
                await reader.startOffset(topic, partition),
                await reader.highWatermark(topic, partition),
            ]
            if (start < end) {
                starts.set(partition, start)
                ends.set(partition, end)
            }
        }
        if (!ends.size) {
            return result
        }
        reader.assign(topic, starts)

        while (ends.size) {
            context.cancellationSignal.throwIfAborted()
            const byPartition = new Map<number, Message[]>()
            for (const message of await reader.read(BATCH_SIZE)) {
                byPartition.set(message.partition, [...(byPartition.get(message.partition) ?? []), message])
            }
            for (const [partition, messages] of byPartition) {
                const end = ends.get(partition)
                if (end === undefined) {
                    continue
                }
                const batch = messages.filter((message) => message.offset < end)
                if (batch.length) {
                    result.records_read += batch.length
                    await replayRecords(deps, reader, partition, batch, input, result)
                }
                if (messages[messages.length - 1].offset >= end - 1) {
                    ends.delete(partition)
                }
            }
            context.heartbeat()
        }
        return result
    } finally {
        await reader.close()
    }
}

/** Replays one partition's share of a batch and commits past it. */
async function replayRecords(
    deps: ReplayActivityDeps,
    reader: DlqPartitionReader,
    partition: number,
    batch: Message[],
    input: ReplayInput,
    result: ReplayResult
): Promise<void> {
    const commitAfter = (message: Message): void => reader.commit(deps.topic, partition, message.offset + 1)

    try {
        result.invocations_queued += (await deps.replayer.replayBatch(batch)).queued
        commitAfter(batch[batch.length - 1])
        return
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
    for (const message of batch) {
        try {
            result.invocations_queued += (await deps.replayer.replayBatch([message])).queued
        } catch (error) {
            if (!(error instanceof UnreplayableRecordsError)) {
                throw error
            }
            if (!input.skip_unreplayable) {
                throw ApplicationFailure.nonRetryable(
                    `Partition ${partition} offset ${message.offset} cannot be replayed: ${truncate(error)}`,
                    'UnreplayableRecord'
                )
            }
            result.records_skipped += 1
            if (result.skipped.length < MAX_SKIPPED_LISTED) {
                result.skipped.push({ partition, offset: message.offset, error: truncate(error) })
            }
        }
        commitAfter(message)
    }
}

export function createReplayActivities(deps: ReplayActivityDeps): Record<string, (input: any) => Promise<unknown>> {
    return {
        [REPLAY_ACTIVITY]: (input: ReplayInput) => {
            const context = Context.current()
            return replayTopic(deps, input, {
                heartbeat: () => context.heartbeat(),
                cancellationSignal: context.cancellationSignal,
            })
        },
    }
}
