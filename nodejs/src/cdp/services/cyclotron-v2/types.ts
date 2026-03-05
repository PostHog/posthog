import { DateTime } from 'luxon'

export type CyclotronV2JobStatus = 'available' | 'running' | 'completed' | 'failed' | 'canceled'

export type CyclotronV2PoolConfig = {
    dbUrl: string
    maxConnections?: number
    idleTimeoutMs?: number
}

export type CyclotronV2JobInit = {
    id?: string
    teamId: number
    functionId?: string | null
    queueName: string
    priority?: number
    scheduled?: Date
    parentRunId?: string | null
    state?: Buffer | null
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

    ack(): Promise<void>
    fail(): Promise<void>
    retry(options?: { delayMs?: number; state?: Buffer | null }): Promise<void>
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
