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
}

export type CyclotronV2ManagerConfig = {
    pool: CyclotronV2PoolConfig
    depthLimit?: number
    depthCheckIntervalMs?: number
}

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
    // Fleet-health gate: dead-lettering is paused while stalls look fleet-wide
    // (an outage) rather than isolated (a genuinely bad job).
    fleetStallRatioThreshold?: number
    fleetHealthWindowMs?: number
    fleetMinStalledCount?: number
}

export type CyclotronV2CleanupResult = {
    deleted: number
    stalled: number
    poisoned: number
    poisonedIds: string[]
    poisoningPaused: boolean
    depths: Map<string, number>
    dlqDepth: number
}
