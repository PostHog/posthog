import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import type { CommonConfig } from '~/common/config'
import { RedisV2, createRedisV2PoolFromConfig, getRedisPipelineResults } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'

export type CrashGuardMode = 'off' | 'shadow'

const batchAttemptsMarked = new Counter({
    name: 'cdp_batch_attempts_marked_total',
    help: 'Partitions of a consumed batch counted in Valkey, by outcome. new is a first attempt, repeat retries a batch that did not finish, unavailable ran without a count.',
    labelNames: ['group', 'outcome'],
})

const batchesDiverted = new Counter({
    name: 'cdp_batch_diverted_total',
    help: 'Partitions of a batch that crashed the worker CDP_BATCH_QUARANTINE_MAX_ATTEMPTS times. In shadow mode the batch is processed anyway.',
    labelNames: ['group', 'mode'],
})

export type CrashGuardValkeyConfig = Pick<
    CdpConfig,
    | 'CDP_VALKEY_HOST'
    | 'CDP_VALKEY_PORT'
    | 'CDP_VALKEY_PASSWORD'
    | 'CDP_VALKEY_TLS'
    | 'CDP_BATCH_QUARANTINE_VALKEY_TIMEOUT_MS'
> &
    Pick<CommonConfig, 'REDIS_POOL_MAX_SIZE'>

// A value that is not a number would fail quietly: the threshold would never trip, a key would get no TTL,
// and ioredis would wait forever for a command.
function positiveInteger<C extends object>(config: C, name: keyof C & string): number {
    const value: unknown = config[name]
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
        throw new Error(`${name} must be a positive integer, got "${value}"`)
    }
    return value
}

export function createCrashGuardValkeyPool(config: CrashGuardValkeyConfig): RedisV2 {
    positiveInteger(config, 'CDP_BATCH_QUARANTINE_VALKEY_TIMEOUT_MS')
    return createRedisV2PoolFromConfig({
        connection: {
            url: config.CDP_VALKEY_HOST,
            options: {
                port: config.CDP_VALKEY_PORT,
                password: config.CDP_VALKEY_PASSWORD,
                tls: config.CDP_VALKEY_TLS ? {} : undefined,
                commandTimeout: config.CDP_BATCH_QUARANTINE_VALKEY_TIMEOUT_MS,
                // A queued command waits for the reconnect and commandTimeout never starts for it, so a
                // dropped connection would hold the batch until Valkey returns.
                enableOfflineQueue: false,
            },
            name: 'cdp-batch-attempts',
            // Counting is best effort, so a Valkey outage must not stop the worker.
            exitOnRepeatedErrors: false,
        },
        poolMinSize: 0,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        discardStalledClients: true,
        acquireTimeoutMillis: config.CDP_BATCH_QUARANTINE_VALKEY_TIMEOUT_MS,
    })
}

export function parseCrashGuardMode(value: string): CrashGuardMode {
    const mode = value.trim().toLowerCase()
    if (mode !== 'off' && mode !== 'shadow') {
        throw new Error(`CDP_BATCH_QUARANTINE_MODE must be off or shadow, got "${value}"`)
    }
    return mode
}

export type CrashGuardSettings = {
    valkey: RedisV2
    mode: Exclude<CrashGuardMode, 'off'>
    maxAttempts: number
    keyTtlSeconds: number
}

type CrashGuardConfig = CrashGuardValkeyConfig &
    Pick<
        CdpConfig,
        'CDP_BATCH_QUARANTINE_MODE' | 'CDP_BATCH_QUARANTINE_MAX_ATTEMPTS' | 'CDP_BATCH_QUARANTINE_KEY_TTL_SECONDS'
    >

export function createCrashGuardSettings(config: CrashGuardConfig): CrashGuardSettings | null {
    const mode = parseCrashGuardMode(config.CDP_BATCH_QUARANTINE_MODE)
    if (mode === 'off') {
        return null
    }
    const maxAttempts = positiveInteger(config, 'CDP_BATCH_QUARANTINE_MAX_ATTEMPTS')
    const keyTtlSeconds = positiveInteger(config, 'CDP_BATCH_QUARANTINE_KEY_TTL_SECONDS')
    return { valkey: createCrashGuardValkeyPool(config), mode, maxAttempts, keyTtlSeconds }
}

export type ConsumedBatch = { backgroundTask: Promise<unknown> }

// A worker that crashes restarts at the last committed offset, so a crashing batch starts at the
// same offset every time and the start identifies it.
export const batchAttemptsKey = (group: string, partition: number, start: number): string =>
    `cdp:batch-attempts:${group}:${partition}:${start}`

type BatchStart = { partition: number; start: number }

type CountedStart = BatchStart & { attempts: number }

const batchStarts = (messages: Message[]): BatchStart[] => {
    const starts = new Map<number, number>()
    for (const { partition, offset } of messages) {
        starts.set(partition, Math.min(offset, starts.get(partition) ?? offset))
    }
    return [...starts].map(([partition, start]) => ({ partition, start }))
}

/**
 * Counts how often each partition's batch of a consumer group started without finishing. A count above
 * maxAttempts means a fetch that held the batch killed the worker. A healthy partition that shares that
 * fetch with a poisoned one is counted too, so the flag does not identify which partition or message is
 * at fault.
 */
export class CrashGuard {
    constructor(
        private settings: CrashGuardSettings,
        private group: string
    ) {}

    public get mode(): CrashGuardSettings['mode'] {
        return this.settings.mode
    }

    /**
     * The job queue calls this for every fetched batch, in place of consuming it directly. The order is:
     * 1. count: add 1 to the attempt count of each partition in the fetch.
     * 2. consume the messages.
     * 3. clear: when the background task of the consume finishes, delete the counts of the consumed partitions.
     *
     * A crash at any step leaves the counts in place. The next start of the worker fetches the same offsets
     * and counts them again.
     */
    public async run(
        messages: Message[],
        consume: (messages: Message[]) => Promise<ConsumedBatch>
    ): Promise<ConsumedBatch> {
        if (messages.length === 0) {
            return await consume(messages)
        }

        const counted = await this.count(batchStarts(messages))
        const { mode, maxAttempts } = this.settings
        for (const batch of counted?.filter((x) => x.attempts > maxAttempts) ?? []) {
            batchesDiverted.labels(this.group, mode).inc()
            logger.warn('☠️', 'batch crashed the worker repeatedly and would be diverted', {
                group: this.group,
                mode,
                ...batch,
            })
        }

        const { backgroundTask } = await consume(messages)
        return { backgroundTask: counted ? backgroundTask.then(() => this.clear(counted)) : backgroundTask }
    }

    private keys(starts: BatchStart[]): string[] {
        return starts.map(({ partition, start }) => batchAttemptsKey(this.group, partition, start))
    }

    /**
     * Adds 1 to the attempt count of each partition in the fetch and refreshes its TTL. run calls this
     * first, before any message runs, so a crash anywhere later still leaves the count. When Valkey is
     * unavailable, this returns null and run consumes the whole fetch without a count.
     */
    private async count(starts: BatchStart[]): Promise<CountedStart[] | null> {
        try {
            const { valkey, keyTtlSeconds } = this.settings
            const results = await valkey.usePipeline({ name: 'cdp-batch-attempts-count' }, (pipeline) => {
                for (const key of this.keys(starts)) {
                    pipeline.incr(key)
                    pipeline.expire(key, keyTtlSeconds)
                }
            })
            const counted = starts.map((batch, i) => {
                const [[incrError, attempts], [expireError]] = getRedisPipelineResults(results!, i, 2)
                if (incrError || expireError) {
                    throw incrError ?? expireError
                }
                return { ...batch, attempts: attempts as number }
            })
            for (const { attempts } of counted) {
                batchAttemptsMarked.labels(this.group, attempts === 1 ? 'new' : 'repeat').inc()
            }
            return counted
        } catch (error) {
            batchAttemptsMarked.labels(this.group, 'unavailable').inc(starts.length)
            logger.warn('☠️', 'could not count batch attempts, processing the batch without a count', {
                group: this.group,
                error: String(error),
            })
            return null
        }
    }

    /**
     * Deletes the attempt counts of the consumed partitions after their background task finishes. Without
     * this, a later fetch from the same start offset, for example after a rebalance, would start with a
     * leftover attempt.
     */
    private async clear(counted: CountedStart[]): Promise<void> {
        try {
            const results = await this.settings.valkey.usePipeline({ name: 'cdp-batch-attempts-clear' }, (pipeline) => {
                for (const key of this.keys(counted)) {
                    pipeline.del(key)
                }
            })
            const failed = results?.find(([error]) => error)
            if (failed) {
                throw failed[0]
            }
        } catch (error) {
            // The key expires on its own. Until then a replay of this batch counts one attempt too many.
            logger.warn('☠️', 'could not clear batch attempts', { group: this.group, error: String(error) })
        }
    }
}
