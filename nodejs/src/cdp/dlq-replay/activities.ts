import { Context } from '@temporalio/activity'
import { Message } from 'node-rdkafka'

import type { CdpDlqReplayer, ReplayScope } from './cdp-dlq-replayer'
import { UnreplayableRecordsError } from './cdp-dlq-replayer'
import type { DlqPartitionReader } from './partition-reader'

/** Names the Python workflow calls these by. Changing one strands every workflow that is running. */
export const LIST_PARTITIONS_ACTIVITY = 'cdp-dlq-replay-list-partitions'
export const REPLAY_PARTITION_ACTIVITY = 'cdp-dlq-replay-partition'

const DEFAULT_BATCH_SIZE = 500
/** Keeps the result far below Temporal's payload limit however many records a run skips. */
const MAX_SKIPPED_LISTED = 100
const MAX_ERROR_LENGTH = 500

export interface ListPartitionsInput {
    topic?: string | null
}

export interface ListPartitionsResult {
    topic: string
    partitions: number[]
}

export interface ReplayPartitionInput {
    topic: string
    partition: number
    start_timestamp_ms: number
    end_timestamp_ms: number
    from_offset?: number | null
    /** Exclusive. Fixed by the first call, so every later call reads the same range. */
    end_offset?: number | null
    team_id?: number | null
    source_ids?: readonly string[] | null
    dry_run?: boolean
    skip_unreplayable?: boolean
    batch_size?: number | null
}

export interface ReplayRecordError {
    offset: number
    error: string
}

export interface ReplayPartitionResult {
    partition: number
    next_offset: number
    end_offset: number
    records_read: number
    records_in_scope: number
    records_out_of_scope: number
    records_unreadable: number
    records_skipped: number
    invocations_queued: number
    skipped: ReplayRecordError[]
    blocked: ReplayRecordError | null
}

export interface ReplayActivityContext {
    heartbeat(details: ReplayPartitionResult): void
    readonly heartbeatDetails: ReplayPartitionResult | undefined
    readonly cancellationSignal: AbortSignal
}

export interface ReplayActivityDeps {
    replayer: Pick<CdpDlqReplayer, 'replayBatch' | 'planBatch'>
    openReader: () => Promise<DlqPartitionReader>
    defaultTopic: string
}

const truncate = (error: unknown): string =>
    String(error instanceof Error ? error.message : error).slice(0, MAX_ERROR_LENGTH)

export async function listPartitions(
    deps: ReplayActivityDeps,
    input: ListPartitionsInput
): Promise<ListPartitionsResult> {
    const topic = input.topic || deps.defaultTopic
    const reader = await deps.openReader()
    try {
        return { topic, partitions: await reader.partitions(topic) }
    } finally {
        await reader.close()
    }
}

/**
 * Replays one partition from where the last call stopped to the end of the window.
 *
 * It returns when the range is done, or early with `blocked` set when a record cannot be replayed
 * and the run was not told to skip such records. Everything before that record is delivered. The
 * workflow then waits for an operator to retry or skip, and calls this again from `next_offset`.
 *
 * Progress is heartbeated after every batch. A retry after a crash resumes from the last
 * heartbeat, so at most the batch in flight is delivered twice, which is the same guarantee the
 * events consumer gives.
 */
export async function replayPartition(
    deps: ReplayActivityDeps,
    input: ReplayPartitionInput,
    context: ReplayActivityContext
): Promise<ReplayPartitionResult> {
    const { topic, partition } = input
    const scope: ReplayScope = {
        teamId: input.team_id ?? undefined,
        sourceIds: input.source_ids?.length ? new Set(input.source_ids) : undefined,
    }
    const batchSize = input.batch_size || DEFAULT_BATCH_SIZE

    const reader = await deps.openReader()
    try {
        const resumed = context.heartbeatDetails
        const result: ReplayPartitionResult = resumed
            ? { ...resumed, blocked: null }
            : {
                  partition,
                  next_offset:
                      input.from_offset ?? (await reader.offsetForTime(topic, partition, input.start_timestamp_ms)),
                  end_offset: input.end_offset ?? (await reader.highWatermark(topic, partition)),
                  records_read: 0,
                  records_in_scope: 0,
                  records_out_of_scope: 0,
                  records_unreadable: 0,
                  records_skipped: 0,
                  invocations_queued: 0,
                  skipped: [],
                  blocked: null,
              }
        const checkpoint = (): void => context.heartbeat(result)

        if (result.next_offset < result.end_offset) {
            reader.seek(topic, partition, result.next_offset)
        }
        while (result.next_offset < result.end_offset) {
            context.cancellationSignal.throwIfAborted()

            const inRange = (await reader.read(Math.min(batchSize, result.end_offset - result.next_offset))).filter(
                (message) => message.offset < result.end_offset
            )
            const pastWindow = inRange.findIndex((message) => (message.timestamp ?? 0) > input.end_timestamp_ms)
            const batch = pastWindow === -1 ? inRange : inRange.slice(0, pastWindow)

            if (batch.length) {
                result.records_read += batch.length
                if (input.dry_run) {
                    const plan = deps.replayer.planBatch(batch, scope)
                    result.records_in_scope += plan.inScope
                    result.records_out_of_scope += plan.outOfScope
                    result.records_unreadable += plan.unreadable
                    result.next_offset = batch[batch.length - 1].offset + 1
                } else if (!(await replayRecords(deps, batch, scope, input, result, checkpoint))) {
                    checkpoint()
                    return result
                }
            }

            if (pastWindow !== -1) {
                // Records are in timestamp order per partition, so nothing after this one is in the
                // window. Pinning the end here keeps a later call from reading past it.
                result.end_offset = inRange[pastWindow].offset
                result.next_offset = result.end_offset
            }
            checkpoint()
        }
        return result
    } finally {
        await reader.close()
    }
}

async function replayRecords(
    deps: ReplayActivityDeps,
    batch: Message[],
    scope: ReplayScope,
    input: ReplayPartitionInput,
    result: ReplayPartitionResult,
    checkpoint: () => void
): Promise<boolean> {
    const add = (replayed: { rebuilt: number; outOfScope: number; queued: number }): void => {
        result.records_in_scope += replayed.rebuilt
        result.records_out_of_scope += replayed.outOfScope
        result.invocations_queued += replayed.queued
    }

    try {
        add(await deps.replayer.replayBatch(batch, scope))
        result.next_offset = batch[batch.length - 1].offset + 1
        return true
    } catch (error) {
        // Any other error can come after part of the batch was queued, so replaying it again
        // record by record would deliver that part twice. It fails the attempt instead, and the
        // retry resumes from the last checkpoint.
        if (!(error instanceof UnreplayableRecordsError)) {
            throw error
        }
    }

    // Nothing from the batch was queued, so each record can go on its own. Two records for the same
    // event name different sources, so replaying them apart rebuilds nothing twice.
    for (const message of batch) {
        try {
            add(await deps.replayer.replayBatch([message], scope))
        } catch (error) {
            if (!(error instanceof UnreplayableRecordsError)) {
                throw error
            }
            const entry = { offset: message.offset, error: truncate(error) }
            if (!input.skip_unreplayable) {
                result.blocked = entry
                result.next_offset = message.offset
                return false
            }
            result.records_skipped += 1
            if (result.skipped.length < MAX_SKIPPED_LISTED) {
                result.skipped.push(entry)
            }
        }
        result.next_offset = message.offset + 1
        checkpoint()
    }
    return true
}

export function createReplayActivities(deps: ReplayActivityDeps): Record<string, (input: any) => Promise<unknown>> {
    return {
        [LIST_PARTITIONS_ACTIVITY]: (input: ListPartitionsInput) => listPartitions(deps, input),
        [REPLAY_PARTITION_ACTIVITY]: (input: ReplayPartitionInput) => {
            const context = Context.current()
            return replayPartition(deps, input, {
                heartbeat: (details) => context.heartbeat(details),
                heartbeatDetails: context.info.heartbeatDetails as ReplayPartitionResult | undefined,
                cancellationSignal: context.cancellationSignal,
            })
        },
    }
}
