import { CODES, Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import type { CommonConfig } from '~/common/config'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'

export type CrashGuardMode = 'off' | 'shadow' | 'enforce'

const batchAttemptsMarked = new Counter({
    name: 'cdp_batch_attempts_marked_total',
    help: 'Partitions of a consumed batch counted in Valkey, by outcome. new is a first attempt, repeat retries a batch that did not finish, unavailable ran without a count.',
    labelNames: ['group', 'outcome'],
})

const batchesDiverted = new Counter({
    name: 'cdp_batch_diverted_total',
    help: 'Partitions of a batch that crashed the worker CDP_BATCH_QUARANTINE_MAX_ATTEMPTS times. In shadow mode the batch is processed anyway. In the dead letter consumer group, cdp-cyclotron-hogdlq-consumer, it counts quarantined batches.',
    labelNames: ['group', 'mode'],
})

const batchAttemptsUncounted = new Counter({
    name: 'cdp_batch_attempts_uncounted_total',
    help: 'Partitions whose attempt was taken back because the batch failed on an unavailable dependency or its background task outlived the guard timeout.',
    labelNames: ['group'],
})

const setAsideCeilingReached = new Counter({
    name: 'cdp_batch_set_aside_ceiling_reached_total',
    help: 'Flagged partitions the guard did not set aside, because more partitions of the group were flagged within the key TTL than CDP_BATCH_QUARANTINE_MAX_FLAGGED_PARTITIONS allows. The worker keeps crashing on them.',
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
export function positiveInteger<C extends object>(config: C, name: keyof C & string): number {
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
    if (mode !== 'off' && mode !== 'shadow' && mode !== 'enforce') {
        throw new Error(`CDP_BATCH_QUARANTINE_MODE must be off, shadow or enforce, got "${value}"`)
    }
    return mode
}

export type CrashGuardSettings = {
    valkey: RedisV2
    mode: Exclude<CrashGuardMode, 'off'>
    maxAttempts: number
    keyTtlSeconds: number
    maxFlaggedPartitions: number
    /** Shorter than CONSUMER_BACKGROUND_TASK_TIMEOUT_MS, so the take back finishes before consumer v2 restarts. */
    backgroundTaskTimeoutMs: number
}

type CrashGuardConfig = CrashGuardValkeyConfig &
    Pick<
        CdpConfig,
        | 'CDP_BATCH_QUARANTINE_MODE'
        | 'CDP_BATCH_QUARANTINE_MAX_ATTEMPTS'
        | 'CDP_BATCH_QUARANTINE_KEY_TTL_SECONDS'
        | 'CDP_BATCH_QUARANTINE_MAX_FLAGGED_PARTITIONS'
    > &
    Pick<CommonConfig, 'CONSUMER_BACKGROUND_TASK_TIMEOUT_MS'>

export function createCrashGuardSettings(config: CrashGuardConfig): CrashGuardSettings | null {
    const mode = parseCrashGuardMode(config.CDP_BATCH_QUARANTINE_MODE)
    if (mode === 'off') {
        return null
    }
    const maxAttempts = positiveInteger(config, 'CDP_BATCH_QUARANTINE_MAX_ATTEMPTS')
    const keyTtlSeconds = positiveInteger(config, 'CDP_BATCH_QUARANTINE_KEY_TTL_SECONDS')
    const maxFlaggedPartitions = positiveInteger(config, 'CDP_BATCH_QUARANTINE_MAX_FLAGGED_PARTITIONS')
    const valkeyTimeoutMs = positiveInteger(config, 'CDP_BATCH_QUARANTINE_VALKEY_TIMEOUT_MS')
    // The take back waits for a pooled client and then for its command, each up to the Valkey timeout.
    const backgroundTaskTimeoutMs =
        positiveInteger(config, 'CONSUMER_BACKGROUND_TASK_TIMEOUT_MS') - 2 * valkeyTimeoutMs - TAKE_BACK_MARGIN_MS
    if (backgroundTaskTimeoutMs < 1) {
        throw new Error(
            `CONSUMER_BACKGROUND_TASK_TIMEOUT_MS must exceed twice CDP_BATCH_QUARANTINE_VALKEY_TIMEOUT_MS plus ${TAKE_BACK_MARGIN_MS}ms, got "${config.CONSUMER_BACKGROUND_TASK_TIMEOUT_MS}"`
        )
    }
    return {
        valkey: createCrashGuardValkeyPool(config),
        mode,
        maxAttempts,
        keyTtlSeconds,
        maxFlaggedPartitions,
        backgroundTaskTimeoutMs,
    }
}

const TAKE_BACK_MARGIN_MS = 1000

export type ConsumedBatch = { backgroundTask: Promise<unknown> }

/** Takes the messages of the partitions the guard flagged. It throws when they were not set aside. */
export type SetAside = (messages: Message[]) => Promise<void>

// A worker that crashes restarts at the last committed offset, so a crashing batch starts at the
// same offset every time and the start identifies it.
export const batchAttemptsKey = (group: string, partition: number, start: number): string =>
    `cdp:batch-attempts:${group}:${partition}:${start}`

// A crash in the other partitions replays the fetch after a flagged partition was set aside, and the marker
// skips the messages that the set aside already produced. It does not rule out a second copy: when one
// produce fails after others succeeded, run throws before the marker is written and the replay produces
// them all again. That is the at-least-once delivery the worker gives every message.
export const batchSetAsideKey = (group: string, partition: number, start: number): string =>
    `cdp:batch-set-aside:${group}:${partition}:${start}`

// A fetch after a restart can stop short of the offset that crashed. The partition's later fetches then
// start at a new offset, so their counts start over, and this key sets them aside through that offset.
export const batchDivertThroughKey = (group: string, partition: number): string =>
    `cdp:batch-divert-through:${group}:${partition}`

export const batchFlaggedPartitionsKey = (group: string): string => `cdp:batch-flagged-partitions:${group}`

type BatchStart = { partition: number; start: number; last: number; messages: number }

/**
 * highestOffset is the highest offset that any attempt from this start fetched, this one included.
 * divertThrough is the offset through which a set aside of the partition reaches, or -1.
 */
type CountedStart = BatchStart & { attempts: number; highestOffset: number; divertThrough: number }

type Diverted = CountedStart & { upTo: number }

// librdkafka reports a broker outage on a produce as a delivery error that has no isRetriable flag.
const KAFKA_OUTAGE_CODES: ReadonlySet<number> = new Set([
    CODES.ERRORS.ERR__MSG_TIMED_OUT,
    CODES.ERRORS.ERR__TIMED_OUT,
    CODES.ERRORS.ERR__TRANSPORT,
    CODES.ERRORS.ERR__ALL_BROKERS_DOWN,
])

const isDependencyError = (error: unknown): boolean => {
    const { isRetriable, code } = (error ?? {}) as { isRetriable?: unknown; code?: unknown }
    return isRetriable === true || (typeof code === 'number' && KAFKA_OUTAGE_CODES.has(code))
}

const batchStarts = (messages: Message[]): BatchStart[] => {
    const starts = new Map<number, BatchStart>()
    for (const { partition, offset } of messages) {
        const batch = starts.get(partition)
        starts.set(partition, {
            partition,
            start: Math.min(offset, batch?.start ?? offset),
            last: Math.max(offset, batch?.last ?? offset),
            messages: (batch?.messages ?? 0) + 1,
        })
    }
    return [...starts.values()]
}

// One script per key keeps the count, the highest offset and the TTL in a single atomic step, so a key can
// never exist without a TTL. A fetch after a restart can return fewer messages than the fetch that crashed,
// so the highest offset keeps the end of the range that crashed.
const COUNT_ATTEMPT_SCRIPT = `
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
local highest = tonumber(redis.call('HGET', KEYS[1], 'highest_offset'))
local last = tonumber(ARGV[1])
if highest == nil or last > highest then
    highest = last
    redis.call('HSET', KEYS[1], 'highest_offset', ARGV[1])
end
redis.call('EXPIRE', KEYS[1], ARGV[2])
return {attempts, highest}
`

// A key that expired or was cleared stays gone, so a take back cannot leave a key without a TTL.
const UNCOUNT_ATTEMPT_SCRIPT = `
if redis.call('EXISTS', KEYS[1]) == 0 then
    return 0
end
redis.call('HINCRBY', KEYS[1], 'attempts', -1)
redis.call('EXPIRE', KEYS[1], ARGV[1])
return 1
`

// Admits a flagged partition while the group has fewer than ARGV[2] admitted partitions. A partition admitted
// before stays admitted, so a replay never runs messages that were already set aside. Every script here
// touches one key, because CDP Valkey runs in cluster mode and refuses a script whose keys sit in two slots.
const ADMIT_FLAGGED_SCRIPT = `
local admitted = redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1
if not admitted and redis.call('SCARD', KEYS[1]) < tonumber(ARGV[2]) then
    redis.call('SADD', KEYS[1], ARGV[1])
    admitted = true
end
if not admitted then
    return 0
end
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
`

const RAISE_DIVERT_THROUGH_SCRIPT = `
local through = tonumber(redis.call('GET', KEYS[1]))
if through == nil or tonumber(ARGV[1]) > through then
    redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
else
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 1
`

/**
 * Counts how often each partition's batch of a consumer group started without finishing. A count above
 * maxAttempts means a fetch that held the batch killed the worker. A healthy partition that shares that
 * fetch with a poisoned one is counted too, so the flag does not identify which partition or message is
 * at fault. Enforce mode sets aside every flagged partition, healthy or not, through the setAside callback
 * of the worker that owns the consumer group.
 */
export class CrashGuard {
    constructor(
        private settings: CrashGuardSettings,
        private group: string,
        private setAside: SetAside
    ) {}

    public get mode(): CrashGuardSettings['mode'] {
        return this.settings.mode
    }

    /**
     * The job queue calls this for every fetched batch, in place of consuming it directly. The order is:
     * 1. count: add 1 to the attempt count of each partition in the fetch.
     * 2. admit: a partition whose count is above maxAttempts is flagged. It is admitted for a set aside while
     *    fewer than maxFlaggedPartitions partitions of the group were admitted within the key TTL. A flagged
     *    partition past that ceiling runs as without the guard, so the worker stalls on it.
     * 3. In enforce mode, set aside the messages of each admitted partition, and the messages of any other
     *    partition up to the offset that an earlier set aside of it reached, through the setAside callback.
     *    This finishes before anything else runs. If it fails, this throws and no offset is stored.
     * 4. markSetAside: record the highest offset set aside for each partition.
     * 5. consume the other messages.
     * 6. clear: when the background task of the consume finishes, delete the counts of the consumed partitions.
     *
     * A crash at any step leaves the counts in place. The next start of the worker fetches the same offsets
     * and counts them again. A dependency error in the set aside, the consume or its background task calls
     * uncount, and so does a background task that outlives backgroundTaskTimeoutMs, so an outage does not
     * count toward a set aside.
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
        const flagged = counted?.filter((x) => x.attempts > maxAttempts) ?? []
        const admitted = await this.admit(flagged)
        for (const batch of flagged) {
            if (admitted.has(batch.partition)) {
                batchesDiverted.labels(this.group, mode).inc()
                logger.warn(
                    '☠️',
                    mode === 'enforce'
                        ? 'batch crashed the worker repeatedly, setting it aside'
                        : 'batch crashed the worker repeatedly and would be diverted',
                    { group: this.group, mode, ...batch }
                )
            } else {
                setAsideCeilingReached.labels(this.group, mode).inc()
                logger.error('☠️', 'batch crashed the worker repeatedly, but too many partitions are flagged', {
                    group: this.group,
                    mode,
                    maxFlaggedPartitions: this.settings.maxFlaggedPartitions,
                    ...batch,
                })
            }
        }

        const diverted: Diverted[] =
            mode === 'enforce'
                ? (counted ?? []).flatMap((batch) =>
                      admitted.has(batch.partition)
                          ? [{ ...batch, upTo: Infinity }]
                          : batch.divertThrough >= batch.start
                            ? [{ ...batch, upTo: batch.divertThrough }]
                            : []
                  )
                : []
        const upTo = new Map(diverted.map((x) => [x.partition, x.upTo]))
        const isDiverted = (message: Message) => message.offset <= (upTo.get(message.partition) ?? -1)
        const setAsideUpTo = await this.setAsideUpTo(diverted)
        const pending = messages.filter((x) => isDiverted(x) && x.offset > (setAsideUpTo.get(x.partition) ?? -1))
        const uncount = this.uncountOnce(counted)
        if (pending.length > 0) {
            // Consumer v1 stores offsets even when backgroundTask rejects, so only a throw here keeps a failed
            // set aside from being committed.
            await this.uncountOnDependencyError(uncount, this.setAside(pending))
            await this.markSetAside(diverted, pending)
        }
        const { backgroundTask } = await this.uncountOnDependencyError(
            uncount,
            consume(messages.filter((x) => !isDiverted(x)))
        )
        const done = this.uncountOnDependencyError(uncount, this.uncountOnTimeout(uncount, backgroundTask))

        // A partition set aside keeps its key, so a crash before the commit sets the replay aside at once.
        const cleared = counted?.filter((x) => !(mode === 'enforce' && admitted.has(x.partition)))
        return { backgroundTask: cleared ? done.then(() => this.clear(cleared)) : done }
    }

    // A personhog, Postgres or Kafka outage fails every batch at its offset, which would read as poison.
    // Other errors, and crashes that kill the process before this catch, keep their count.
    private async uncountOnDependencyError<T>(uncount: () => Promise<void>, work: Promise<T>): Promise<T> {
        try {
            return await work
        } catch (error) {
            if (isDependencyError(error)) {
                await uncount()
            }
            throw error
        }
    }

    // Consumer v2 restarts the worker when a background task outlives CONSUMER_BACKGROUND_TASK_TIMEOUT_MS,
    // and the restart would count as a crash. A task that slow waits on a dependency, such as a produce that
    // librdkafka retries through a Kafka outage. The task keeps running and nothing rejects, because
    // consumer v1 stores the offsets of a background task even when it rejects.
    private uncountOnTimeout<T>(uncount: () => Promise<void>, task: Promise<T>): Promise<T> {
        const timer = setTimeout(() => {
            logger.warn('☠️', 'background task outlived the crash guard timeout, taking back its attempt', {
                group: this.group,
                timeoutMs: this.settings.backgroundTaskTimeoutMs,
            })
            void uncount()
        }, this.settings.backgroundTaskTimeoutMs)
        return task.finally(() => clearTimeout(timer))
    }

    // A timeout and a later dependency error of the same task must take back one attempt, not two.
    private uncountOnce(counted: CountedStart[] | null): () => Promise<void> {
        let taken: Promise<void> | null = null
        return () => (taken ??= counted ? this.uncount(counted) : Promise.resolve())
    }

    /**
     * Subtracts the attempt that count added, after a dependency error. The batch then fails and
     * replays, but the replay does not move it closer to a set aside. A failure here only logs, because the
     * batch already fails with the original error.
     */
    private async uncount(counted: CountedStart[]): Promise<void> {
        try {
            const results = await this.settings.valkey.usePipeline(
                { name: 'cdp-batch-attempts-uncount' },
                (pipeline) => {
                    for (const key of this.keys(counted)) {
                        pipeline.eval(UNCOUNT_ATTEMPT_SCRIPT, 1, key, this.settings.keyTtlSeconds)
                    }
                }
            )
            const failed = results?.find(([error]) => error)
            if (failed) {
                throw failed[0]
            }
            batchAttemptsUncounted.labels(this.group).inc(counted.length)
        } catch (error) {
            logger.warn('☠️', 'could not take back batch attempts after a dependency error', {
                group: this.group,
                error: String(error),
            })
        }
    }

    /**
     * Admits the flagged partitions that fit under the ceiling and returns them. When Valkey fails, this
     * admits none, so the batch runs and crashes again rather than going aside unchecked.
     */
    private async admit(flagged: CountedStart[]): Promise<Set<number>> {
        const admitted = new Set<number>()
        if (flagged.length === 0) {
            return admitted
        }
        try {
            const { valkey, keyTtlSeconds, maxFlaggedPartitions } = this.settings
            const results = await valkey.usePipeline({ name: 'cdp-batch-flagged-admit' }, (pipeline) => {
                for (const { partition } of flagged) {
                    pipeline.eval(
                        ADMIT_FLAGGED_SCRIPT,
                        1,
                        batchFlaggedPartitionsKey(this.group),
                        partition,
                        maxFlaggedPartitions,
                        keyTtlSeconds
                    )
                }
            })
            flagged.forEach(({ partition }, i) => {
                const [error, reply] = results?.[i] ?? [null, 0]
                if (error) {
                    throw error
                }
                if (reply === 1) {
                    admitted.add(partition)
                }
            })
        } catch (error) {
            logger.warn('☠️', 'could not admit flagged partitions, running them', {
                group: this.group,
                error: String(error),
            })
            admitted.clear()
        }
        return admitted
    }

    /**
     * Reads the set-aside marker of each diverted partition before the set aside. run sets aside only the
     * messages above the marker, so a replay of a fetch that was already set aside handles only the new
     * messages. The marker holds the highest offset set aside, because a replay starts at the same offset but
     * can fetch more. A marker Valkey cannot read counts as missing: a second copy beats a message that was
     * never set aside.
     */
    private async setAsideUpTo(flagged: Diverted[]): Promise<Map<number, number>> {
        const upTo = new Map<number, number>()
        if (flagged.length === 0) {
            return upTo
        }
        try {
            const { valkey, keyTtlSeconds } = this.settings
            const results = await valkey.usePipeline({ name: 'cdp-batch-set-aside-get' }, (pipeline) => {
                for (const { partition, start } of flagged) {
                    // count refreshes the attempts key on every replay, and the marker must live as long.
                    pipeline.getex(batchSetAsideKey(this.group, partition, start), 'EX', keyTtlSeconds)
                }
            })
            flagged.forEach(({ partition }, i) => {
                const [error, marker] = results?.[i] ?? [null, null]
                const offset = Number(marker ?? NaN)
                if (!error && Number.isSafeInteger(offset)) {
                    upTo.set(partition, offset)
                }
            })
        } catch (error) {
            logger.warn('☠️', 'could not read the batch set aside markers, setting the batch aside', {
                group: this.group,
                error: String(error),
            })
        }
        return upTo
    }

    /**
     * Writes the set-aside marker after a set aside succeeded. The marker matters only if the worker crashes
     * after the set aside and before the offsets are stored. A failure here only logs, so the replay sets the
     * same messages aside a second time, which is safer than losing them. For an admitted partition it also
     * raises the divert-through offset to the highest offset that crashed. If that write fails, the later
     * fetches count from zero, as they would without it.
     */
    private async markSetAside(flagged: Diverted[], setAside: Message[]): Promise<void> {
        const upTo = new Map<number, number>()
        for (const { partition, offset } of setAside) {
            upTo.set(partition, Math.max(offset, upTo.get(partition) ?? offset))
        }
        try {
            const { valkey, keyTtlSeconds } = this.settings
            const results = await valkey.usePipeline({ name: 'cdp-batch-set-aside-set' }, (pipeline) => {
                for (const { partition, start } of flagged.filter((x) => upTo.has(x.partition))) {
                    pipeline.set(
                        batchSetAsideKey(this.group, partition, start),
                        upTo.get(partition)!,
                        'EX',
                        keyTtlSeconds
                    )
                }
                for (const { partition, highestOffset } of flagged.filter((x) => x.upTo === Infinity)) {
                    pipeline.eval(
                        RAISE_DIVERT_THROUGH_SCRIPT,
                        1,
                        batchDivertThroughKey(this.group, partition),
                        highestOffset,
                        keyTtlSeconds
                    )
                }
            })
            const failed = results?.find(([error]) => error)
            if (failed) {
                throw failed[0]
            }
        } catch (error) {
            logger.warn('☠️', 'could not mark the batch set aside', { group: this.group, error: String(error) })
        }
    }

    private keys(starts: BatchStart[]): string[] {
        return starts.map(({ partition, start }) => batchAttemptsKey(this.group, partition, start))
    }

    /**
     * Adds 1 to the attempt count of each partition in the fetch, records the highest offset that any attempt
     * fetched, and refreshes the TTL. run calls this
     * first, before any message runs, so a crash anywhere later still leaves the count. When Valkey is
     * unavailable, this returns null and run consumes the whole fetch without a count or a set aside.
     */
    private async count(starts: BatchStart[]): Promise<CountedStart[] | null> {
        try {
            const { valkey, keyTtlSeconds } = this.settings
            const results = await valkey.usePipeline({ name: 'cdp-batch-attempts-count' }, (pipeline) => {
                for (const batch of starts) {
                    pipeline.eval(COUNT_ATTEMPT_SCRIPT, 1, this.keys([batch])[0], batch.last, keyTtlSeconds)
                    pipeline.get(batchDivertThroughKey(this.group, batch.partition))
                }
            })
            const counted = starts.map((batch, i) => {
                const [error, reply] = results![2 * i]
                const [throughError, through] = results![2 * i + 1]
                if (error || throughError) {
                    throw error ?? throughError
                }
                const [attempts, highestOffset] = reply as [number, number]
                const divertThrough = Number(through ?? NaN)
                return {
                    ...batch,
                    attempts,
                    highestOffset,
                    divertThrough: Number.isSafeInteger(divertThrough) ? divertThrough : -1,
                }
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
     * leftover attempt. The delete does not check which pod owns the partition. After a rebalance, a revoked pod
     * whose background task finishes late can delete the count that the new owner just added. That delays a
     * divert by one attempt and does not lose a message.
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
