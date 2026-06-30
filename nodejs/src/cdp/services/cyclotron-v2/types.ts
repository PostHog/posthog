import { DateTime } from 'luxon'
import { z } from 'zod'

export type CyclotronV2JobStatus = 'available' | 'running' | 'completed' | 'failed' | 'canceled'

export type CyclotronV2PoolConfig = {
    dbUrl: string
    maxConnections?: number
    idleTimeoutMs?: number
}

export const CyclotronV2JobInitSchema = z.object({
    id: z.string().min(1).optional(),
    teamId: z.number().int(),
    functionId: z.string().min(1).nullish(),
    queueName: z.string().min(1),
    priority: z.number().int().optional(),
    scheduled: z.date().optional(),
    parentRunId: z.string().nullish(),
    state: z.instanceof(Buffer).nullish(),
    distinctId: z.string().nullish(),
    personId: z.string().nullish(),
    actionId: z.string().nullish(),
    // When `true`, the insert uses ON CONFLICT (id) DO UPDATE — the existing
    // row's status is reset to 'available', the lock is cleared, and state is
    // replaced. Used by the rerun path so a re-execution can reuse the
    // original `invocation_id` (so lifecycle rows collapse under one
    // ReplacingMergeTree key) without colliding on the cyclotron_jobs PK.
    overwriteExisting: z.boolean().optional(),
})

export type CyclotronV2JobInit = z.infer<typeof CyclotronV2JobInitSchema>

export const CyclotronV2RescheduleOptionsSchema = z.object({
    scheduledAt: z.date().optional(),
    state: z.instanceof(Buffer).nullish(),
    distinctId: z.string().nullish(),
    personId: z.string().nullish(),
    actionId: z.string().nullish(),
    queueName: z.string().optional(),
})

export type CyclotronV2RescheduleOptions = z.infer<typeof CyclotronV2RescheduleOptionsSchema>

/**
 * Atomic enqueue-and-check-in primitive for fan-out workflows.
 *
 * Produces N new jobs AND re-queues (or terminates) the current worker's job
 * in a single Postgres transaction. Used by the batch resolver: each page
 * inserts ~500 child workflow invocations AND advances its own cursor state
 * atomically — so a worker crash between the two writes can't leak partial
 * progress (children enqueued but cursor not advanced).
 *
 * `selfDisposition`:
 *   - `{ kind: 'reschedule', scheduledAt?, state? }` → re-queue self (status
 *     back to 'available') for the next page.
 *   - `{ kind: 'ack' }` → terminal success (completed).
 *   - `{ kind: 'fail' }` → terminal failure.
 */
export interface CyclotronV2BulkCreateAndCheckInInput {
    newJobs: CyclotronV2JobInit[]
    selfDisposition:
        | { kind: 'reschedule'; scheduledAt?: Date; state?: Buffer | null }
        | { kind: 'ack' }
        | { kind: 'fail' }
}

export interface CyclotronV2DequeuedJob {
    readonly id: string
    readonly teamId: number
    readonly functionId: string | null
    readonly queueName: string
    readonly priority: number
    readonly scheduled: DateTime
    readonly created: DateTime
    readonly parentRunId: string | null
    readonly transitionCount: number
    readonly state: Buffer | null
    readonly distinctId: string | null
    readonly personId: string | null
    readonly actionId: string | null

    ack(): Promise<void>
    fail(): Promise<void>
    reschedule(options?: CyclotronV2RescheduleOptions): Promise<void>
    cancel(): Promise<void>
    heartbeat(): Promise<void>
    bulkCreateAndCheckIn(input: CyclotronV2BulkCreateAndCheckInInput): Promise<{ newJobIds: string[] }>
}

export type CyclotronV2ManagerConfig = {
    pool: CyclotronV2PoolConfig
    depthLimit?: number
    depthCheckIntervalMs?: number
}

/**
 * Producer-side surface of `CyclotronV2Manager`. Lets API entrypoints depend
 * on the interface (testable, mockable) without pulling the full manager
 * implementation. Add methods here as new producers need them.
 */
export interface CyclotronV2JobProducer {
    createJob(input: CyclotronV2JobInit): Promise<string>
    disconnect(): Promise<void>
}

/**
 * Per-poll decision returned by a rate-limited worker's hook.
 *   `{ limit: 0, sleepMs }` → skip the dequeue and sleep.
 *   `{ limit: N }`          → dequeue up to `min(N, batchMaxSize)` rows.
 *   `undefined`             → fall back to the static `batchMaxSize`.
 */
export type CyclotronV2BatchLimit = { limit: number; sleepMs?: number }

export type CyclotronV2WorkerConfig = {
    pool: CyclotronV2PoolConfig
    queueName: string
    batchMaxSize?: number
    pollDelayMs?: number
    heartbeatTimeoutMs?: number
    includeEmptyBatches?: boolean
}

export type CyclotronV2JanitorConfig = {
    pool: CyclotronV2PoolConfig
    cleanupBatchSize?: number
    cleanupIntervalMs?: number
    stallTimeoutMs?: number
    maxTouchCount?: number
    cleanupGraceMs?: number
}

export type CyclotronV2CleanupResult = {
    deleted: number
    stalled: number
    poisoned: number
    depths: Map<string, number>
}
