import { Counter, Histogram } from 'prom-client'

import { RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

/**
 * Distributed token-bucket rate limiter for "claim up to N" semantics, backed
 * by a dedicated Valkey instance.
 *
 * Differs from KeyedRateLimiterService: that limiter is binary (you get all of
 * `cost` or none) and grouped per-key for per-function rate limits. This one is
 * "best-effort" — you ask for up to N tokens and get back however many were
 * available (0..N), so the email worker can size its dequeue batch to the
 * available SES budget instead of asking for all-or-nothing.
 *
 * Single Lua script per call → atomic across pods. Multiple workers polling
 * concurrently never overshoot the bucket capacity.
 */

const claimCounter = new Counter({
    name: 'cdp_rate_limiter_claim_total',
    help: 'Token-bucket claim outcomes from the SES rate limiter Valkey.',
    labelNames: ['limiter', 'key', 'result'],
})

const claimLatency = new Histogram({
    name: 'cdp_rate_limiter_claim_duration_ms',
    help: 'Latency of a single Valkey claim call (Lua roundtrip).',
    labelNames: ['limiter'],
    buckets: [0.5, 1, 2, 5, 10, 25, 50, 100, 250, 500],
})

// Atomic "claim up to" token-bucket script.
//   KEYS[1]      = bucket hash key (stores `ts` and `pool`)
//   ARGV[1]      = requested tokens (integer)
//   ARGV[2]      = pool capacity (max tokens the bucket can hold)
//   ARGV[3]      = refill rate (tokens per second)
//   ARGV[4]      = TTL seconds — bucket auto-expires when idle so cold-start
//                  gives full capacity rather than a stale negative pool.
//
// `now` is sourced via `redis.call('TIME')` so all pods share a single
// monotonic clock — NTP drift between workers can't over- or under-refill
// the bucket on this code path.
//
// Returns the number of tokens granted (0..requested).
const CLAIM_UP_TO_LUA = `
local key = KEYS[1]
local requested = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refillPerSecond = tonumber(ARGV[3])
local ttlSeconds = tonumber(ARGV[4])

local time = redis.call('TIME')
-- TIME returns {seconds, microseconds}; flatten to epoch ms.
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)

local existing = redis.call('hmget', key, 'ts', 'pool')
local rawTs = existing[1]
local rawPool = existing[2]

local available
if rawTs == false then
    available = capacity
else
    local lastTs = tonumber(rawTs)
    local elapsedMs = now - lastTs
    if elapsedMs < 0 then
        elapsedMs = 0
    end
    local currentTokens
    if rawPool == false then
        currentTokens = capacity
    else
        currentTokens = tonumber(rawPool)
    end
    available = math.min(capacity, currentTokens + (elapsedMs / 1000.0) * refillPerSecond)
end

local rawGranted = math.min(available, requested)
if rawGranted < 0 then
    rawGranted = 0
end
-- Floor to int — the grant flows into a SQL LIMIT, which must be integer.
-- The fractional residual stays in the pool so partial refills accumulate
-- across calls instead of being silently dropped.
local granted = math.floor(rawGranted)
local tokensAfter = available - granted

redis.call('hset', key, 'ts', now, 'pool', tokensAfter)
redis.call('expire', key, ttlSeconds)

return granted
`

export interface RateLimiterConfig {
    /** Logical name for metrics/logging only (e.g. 'ses'). */
    name: string
}

export interface ClaimRequest {
    key: string
    requested: number
    capacity: number
    refillPerSecond: number
    /** Bucket TTL in seconds — long enough that an idle bucket can cold-start at full capacity. */
    ttlSeconds?: number
}

export class RateLimiterService {
    constructor(
        private readonly valkey: RedisV2,
        private readonly config: RateLimiterConfig
    ) {}

    /**
     * Synchronous startup check — throws if Valkey is unreachable. Pod fails its
     * health probe, k8s restarts. By design: if the rate limiter can't be reached
     * we must not send (would risk SES throttling), and the simplest enforcement
     * is to not start the worker at all.
     */
    public async ping(): Promise<void> {
        const result = await this.valkey.useClient(
            { name: `rate-limiter:${this.config.name}:ping`, timeout: 5000 },
            (client) => client.ping()
        )
        if (result !== 'PONG') {
            throw new Error(`RateLimiterService(${this.config.name}): Valkey PING did not return PONG`)
        }
    }

    /**
     * Atomically claim up to `requested` tokens from the bucket. Returns the
     * number actually granted (0..requested). Multiple callers can race against
     * the same key — the Lua script serializes them, so the sum of grants across
     * concurrent callers can never exceed available bucket capacity.
     *
     * Runtime errors (Valkey down, command timeout) return 0 — fail-closed.
     * A startup PING already established reachability; mid-run errors trigger
     * the worker's empty-batch sleep instead of crashing.
     */
    public async claimUpTo(req: ClaimRequest): Promise<number> {
        const endTimer = claimLatency.startTimer({ limiter: this.config.name })
        const ttlSeconds = req.ttlSeconds ?? 3600
        try {
            // useClient throws on error (failOpen unset), so the catch block
            // handles Valkey reachability — no need for a null-result branch.
            const result = await this.valkey.useClient(
                { name: `rate-limiter:${this.config.name}:claimUpTo`, timeout: 1000 },
                (client) =>
                    client.eval(
                        CLAIM_UP_TO_LUA,
                        1,
                        req.key,
                        String(req.requested),
                        String(req.capacity),
                        String(req.refillPerSecond),
                        String(ttlSeconds)
                    )
            )

            const granted = Number(result)
            if (!Number.isFinite(granted) || granted < 0) {
                logger.warn('🪙', `RateLimiterService(${this.config.name}) returned invalid grant`, {
                    key: req.key,
                    raw: result,
                })
                claimCounter.inc({ limiter: this.config.name, key: req.key, result: 'valkey_error' })
                return 0
            }

            const outcome = granted === 0 ? 'denied' : granted < req.requested ? 'granted_partial' : 'granted_full'
            claimCounter.inc({ limiter: this.config.name, key: req.key, result: outcome })
            return granted
        } catch (err) {
            logger.warn('🪙', `RateLimiterService(${this.config.name}) claim threw`, {
                key: req.key,
                error: String(err),
            })
            claimCounter.inc({ limiter: this.config.name, key: req.key, result: 'valkey_error' })
            return 0
        } finally {
            endTimer()
        }
    }
}
