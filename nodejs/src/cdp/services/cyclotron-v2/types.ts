import { DateTime } from 'luxon'
import { z } from 'zod'

export type CyclotronV2JobStatus = 'available' | 'running' | 'completed' | 'failed' | 'canceled'

export type CyclotronV2PoolConfig = {
    dbUrl: string
    maxConnections?: number
    idleTimeoutMs?: number
}

// `id` and `functionId` use PostHog's UUIDT-style identifiers which don't set
// valid UUID version bits, so we only validate them as non-empty strings here.
// `personId` comes from posthog_person.uuid (a real UUID v4/v7) and ingestion's
// resolution, so we validate it strictly to catch any bad data at the boundary.
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
    personId: z.uuid().nullish(),
    actionId: z.string().nullish(),
})

export type CyclotronV2JobInit = z.infer<typeof CyclotronV2JobInitSchema>

export const CyclotronV2RescheduleOptionsSchema = z.object({
    scheduledAt: z.date().optional(),
    state: z.instanceof(Buffer).nullish(),
    distinctId: z.string().nullish(),
    personId: z.uuid().nullish(),
    actionId: z.string().nullish(),
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
}

export type CyclotronV2CleanupResult = {
    deleted: number
    stalled: number
    poisoned: number
    depths: Map<string, number>
}
