import { createHash } from 'crypto'
import { Counter, Histogram } from 'prom-client'

import type { CommonConfig } from '~/common/config'
import { RedisClient, RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'

// Covers a caller's timeout and retry. After this a pending key expires, so a crash between the
// reservation and the queue write can cost a duplicate, but never a send the caller thinks happened.
const PENDING_TTL_SECONDS = 60
const QUEUED_TTL_SECONDS = 24 * 60 * 60
// A hung Valkey must not hold the caller's request open. Each route decides what an unavailable store means.
const VALKEY_TIMEOUT_MS = 1000
// Deletes the key only while it still holds this request's reservation, so a late release never frees
// a key that another request reserved after this one expired.
const RELEASE_SCRIPT = `local v = redis.call('GET', KEYS[1]) if v and cjson.decode(v).invocationId == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0`
// Records the queued run when the key is absent or still holds this request's reservation. The key is
// absent when the queue write took longer than the pending TTL, and the run is queued all the same.
const MARK_QUEUED_SCRIPT = `local v = redis.call('GET', KEYS[1]) if (not v) or cjson.decode(v).invocationId == ARGV[2] then redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3]) return 1 end return 0`
const MARK_QUEUED_ATTEMPTS = 2

const idempotencyOperationsTotal = new Counter({
    name: 'cdp_hogflow_idempotency_operations_total',
    help: 'Idempotency key store operations by route scope, operation and outcome. A reserve outcome of unavailable means the request ran without deduplication or was refused, by route.',
    labelNames: ['scope', 'operation', 'outcome'],
})

const idempotencyValkeyDurationSeconds = new Histogram({
    name: 'cdp_hogflow_idempotency_valkey_duration_seconds',
    help: 'Duration of idempotency key store calls to Valkey, by route scope and operation. Calls stop at the 1 second timeout.',
    labelNames: ['scope', 'operation'],
    buckets: [0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1],
})

type IdempotencyOperation = 'reserve' | 'mark_queued' | 'release'

const withTimeout = async <T>(promise: Promise<T>, timeoutMs: number): Promise<T> => {
    let timeoutId: NodeJS.Timeout | undefined
    try {
        return await Promise.race([
            promise,
            new Promise<never>((_, reject) => {
                timeoutId = setTimeout(() => reject(new Error(`timed out after ${timeoutMs}ms`)), timeoutMs)
            }),
        ])
    } finally {
        clearTimeout(timeoutId)
    }
}

export type IdempotencyValkeyConfig = Pick<
    CdpConfig,
    | 'CDP_IDEMPOTENCY_VALKEY_HOST'
    | 'CDP_IDEMPOTENCY_VALKEY_PORT'
    | 'CDP_IDEMPOTENCY_VALKEY_PASSWORD'
    | 'CDP_IDEMPOTENCY_VALKEY_TLS'
> &
    Pick<CommonConfig, 'REDIS_POOL_MIN_SIZE' | 'REDIS_POOL_MAX_SIZE'>

/**
 * Creates a connection to the Valkey that holds caller-supplied idempotency keys. Returns null when
 * the host is unset, and the store then reports itself unavailable.
 */
export function createIdempotencyValkeyPool(config: IdempotencyValkeyConfig): RedisV2 | null {
    const name = 'workflows-idempotency'
    if (!config.CDP_IDEMPOTENCY_VALKEY_HOST) {
        logger.info('🔑', `[${name}] no idempotency Valkey host configured, so the idempotency store is unavailable`)
        return null
    }

    return createRedisV2PoolFromConfig({
        connection: {
            url: config.CDP_IDEMPOTENCY_VALKEY_HOST,
            options: {
                port: config.CDP_IDEMPOTENCY_VALKEY_PORT,
                password: config.CDP_IDEMPOTENCY_VALKEY_PASSWORD,
                tls: config.CDP_IDEMPOTENCY_VALKEY_TLS ? {} : undefined,
                // The caller's timeout only stops the wait. This one aborts the command, so a hung
                // Valkey cannot keep every pool connection borrowed.
                commandTimeout: VALKEY_TIMEOUT_MS,
            },
            name,
            // The store is optional, so its outage must not stop cdp-api.
            exitOnRepeatedErrors: false,
        },
        // No connection at boot, so cdp-api starts without the store.
        poolMinSize: 0,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        acquireTimeoutMillis: VALKEY_TIMEOUT_MS,
    })
}

const sortKeys = (value: unknown): unknown => {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value !== null && typeof value === 'object') {
        return Object.fromEntries(
            Object.keys(value)
                .sort()
                .map((key) => [key, sortKeys((value as Record<string, unknown>)[key])])
        )
    }
    return value
}

export type IdempotencyReservation =
    | { status: 'reserved' }
    // The key already queued a run for the same request.
    | { status: 'replayed'; invocationId: string }
    // The first request with the key has not finished queueing yet.
    | { status: 'in_flight' }
    // The key was used for a different request.
    | { status: 'conflict' }
    | { status: 'unavailable' }

type StoredKey = { fingerprint: string; invocationId: string; queued: boolean }

/**
 * Caller-supplied idempotency keys, scoped to a team. A key reserves a run before it is queued, and
 * holds the run's id for 24 hours once it is. A queue failure releases the key, so the caller's
 * retry can queue the run.
 */
export class IdempotencyKeys {
    constructor(
        private valkey: RedisV2 | null,
        private scope: string
    ) {}

    static fingerprint(request: unknown): string {
        // Callers may rebuild the same request with its object keys in another order on a retry.
        return createHash('sha256')
            .update(JSON.stringify(sortKeys(request)))
            .digest('hex')
    }

    async reserve(
        teamId: number,
        key: string,
        fingerprint: string,
        invocationId: string
    ): Promise<IdempotencyReservation> {
        const reservation = await this.reserveInStore(teamId, key, fingerprint, invocationId)
        this.count('reserve', reservation.status)
        return reservation
    }

    private async reserveInStore(
        teamId: number,
        key: string,
        fingerprint: string,
        invocationId: string
    ): Promise<IdempotencyReservation> {
        const valkey = this.valkey
        if (!valkey) {
            return { status: 'unavailable' }
        }
        const value: StoredKey = { fingerprint, invocationId, queued: false }
        let existing: string | null
        try {
            // SET ... NX GET sets the key when absent and returns the existing value when present.
            // ioredis 4.x types only describe 'OK' | null, so cast to the GET payload.
            existing = await this.timed('reserve', () =>
                valkey.useClient(
                    { name: 'idempotency-reserve' },
                    (client: RedisClient) =>
                        client.set(this.redisKey(teamId, key), JSON.stringify(value), [
                            'EX',
                            String(PENDING_TTL_SECONDS),
                            'NX',
                            'GET',
                        ]) as Promise<string | null>
                )
            )
        } catch (error) {
            logger.error('🔑', 'idempotency key reservation failed', { scope: this.scope, error: String(error) })
            return { status: 'unavailable' }
        }
        if (existing === null) {
            return { status: 'reserved' }
        }
        const stored = parseJSON(existing) as StoredKey
        if (stored.fingerprint !== fingerprint) {
            return { status: 'conflict' }
        }
        return stored.queued ? { status: 'replayed', invocationId: stored.invocationId } : { status: 'in_flight' }
    }

    async markQueued(teamId: number, key: string, fingerprint: string, invocationId: string): Promise<void> {
        const value: StoredKey = { fingerprint, invocationId, queued: true }
        for (let attempt = 1; attempt <= MARK_QUEUED_ATTEMPTS; attempt++) {
            try {
                const written = await this.timed(
                    'mark_queued',
                    () =>
                        this.valkey?.useClient({ name: 'idempotency-mark-queued' }, (client) =>
                            client.eval(
                                MARK_QUEUED_SCRIPT,
                                1,
                                this.redisKey(teamId, key),
                                JSON.stringify(value),
                                invocationId,
                                QUEUED_TTL_SECONDS
                            )
                        ) ?? Promise.resolve(null)
                )
                if (written === 0) {
                    logger.warn('🔑', 'idempotency key held by another request, run not recorded', {
                        scope: this.scope,
                    })
                }
                this.count('mark_queued', written === 0 ? 'not_owned' : 'written')
                return
            } catch (error) {
                // The run is already queued, so the request still succeeds. Without this record a retry
                // after the pending TTL queues the run again.
                logger.error('🔑', 'idempotency key completion failed', {
                    scope: this.scope,
                    attempt,
                    error: String(error),
                })
            }
        }
        this.count('mark_queued', 'failed')
    }

    async release(teamId: number, key: string, invocationId: string): Promise<void> {
        try {
            const released = await this.timed(
                'release',
                () =>
                    this.valkey?.useClient({ name: 'idempotency-release' }, (client) =>
                        client.eval(RELEASE_SCRIPT, 1, this.redisKey(teamId, key), invocationId)
                    ) ?? Promise.resolve(null)
            )
            this.count('release', released === 1 ? 'released' : 'not_owned')
        } catch (error) {
            logger.error('🔑', 'idempotency key release failed', { scope: this.scope, error: String(error) })
            this.count('release', 'failed')
        }
    }

    private count(operation: IdempotencyOperation, outcome: string): void {
        idempotencyOperationsTotal.inc({ scope: this.scope, operation, outcome })
    }

    private async timed<T>(operation: IdempotencyOperation, call: () => Promise<T>): Promise<T> {
        const stopTimer = idempotencyValkeyDurationSeconds.startTimer({ scope: this.scope, operation })
        try {
            return await withTimeout(call(), VALKEY_TIMEOUT_MS)
        } finally {
            stopTimer()
        }
    }

    private redisKey(teamId: number, key: string): string {
        // Hashed so a long or unusual caller key can't shape the Valkey key.
        const keyHash = createHash('sha256').update(key).digest('hex')
        return `@posthog/idempotency/${this.scope}/${teamId}/${keyHash}`
    }
}
