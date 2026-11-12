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
    // No per-bucket `key` label: the workflow-email limiter's key embeds team and flow id, which
    // would grow the series count without bound. `limiter` already separates the callers; per-key
    // diagnosis stays available through the structured warn logs below.
    labelNames: ['limiter', 'result'],
})

const claimLatency = new Histogram({
    name: 'cdp_rate_limiter_claim_duration_ms',
    help: 'Latency of a single Valkey claim call (Lua roundtrip).',
    labelNames: ['limiter'],
    buckets: [0.5, 1, 2, 5, 10, 25, 50, 100, 250, 500],
})

// Atomic "claim up to" token-bucket script.
//   KEYS[1]      = bucket hash key (stores `ts`, `pool`, and the `resv` slot cursor)
//   ARGV[1]      = requested tokens (integer)
//   ARGV[2]      = pool capacity (max tokens the bucket can hold)
//   ARGV[3]      = refill rate (tokens per second)
//   ARGV[4]      = TTL seconds — bucket auto-expires when idle so cold-start
//                  gives full capacity rather than a stale negative pool.
//   ARGV[5]      = reserve-on-deny horizon in ms; 0 disables reservation.
//   ARGV[6]      = 1 to make the claim all-or-nothing: a bucket that cannot cover
//                  the whole request grants nothing and consumes nothing, so a
//                  caller retrying a multi-token claim cannot drain the bucket
//                  while never succeeding.
//
// `now` is sourced via `redis.call('TIME')` so all pods share a single
// monotonic clock — NTP drift between workers can't over- or under-refill
// the bucket on this code path.
//
// Returns {granted, retryAfterMs, reserved}.
//
// The reservation (ARGV[5] > 0), in plain terms: when the bucket says no, it also
// hands the caller a time slot, like a ticket at a counter. The bucket remembers
// the last slot it gave out (`resv`). The first denied caller waits only until the
// missing tokens have refilled. Everyone after that gets the next slot, one token
// interval later. So a denied backlog lines itself up over the future instead of
// everyone retrying at once. No slot is given out further than ARGV[5] ahead; past
// that the caller gets ARGV[5] back with reserved=0 and asks again when it wakes.
// A slot is a place in line, not a promise: the caller still claims when it wakes.
const CLAIM_UP_TO_LUA = `
local key = KEYS[1]
local requested = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refillPerSecond = tonumber(ARGV[3])
local ttlSeconds = tonumber(ARGV[4])
local reserveOnDenyMaxMs = tonumber(ARGV[5])
local allOrNothing = tonumber(ARGV[6])

local time = redis.call('TIME')
-- TIME returns {seconds, microseconds}; flatten to epoch ms.
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)

local existing = redis.call('hmget', key, 'ts', 'pool', 'resv')
local rawTs = existing[1]
local rawPool = existing[2]
local rawResv = existing[3]

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
if rawGranted < 0 or (allOrNothing == 1 and available < requested) then
    rawGranted = 0
end
-- Floor to int — the grant flows into a SQL LIMIT, which must be integer, and
-- Redis truncates a Lua float in the reply regardless. The fractional residual
-- stays in the pool so partial refills accumulate across calls instead of being
-- silently dropped. An all-or-nothing caller must therefore request a whole
-- number, or the floored grant reads back as a denial after the bucket paid.
local granted = math.floor(rawGranted)
local tokensAfter = available - granted

redis.call('hset', key, 'ts', now, 'pool', tokensAfter)
redis.call('expire', key, ttlSeconds)

if granted > 0 or reserveOnDenyMaxMs <= 0 or refillPerSecond <= 0 then
    return {granted, 0, 0}
end

-- First in line: wait only for the tokens that are actually missing. A partly
-- refilled bucket is credit the caller already earned, and waiting a full interval
-- on top would throw that credit away (the pool caps at capacity). Behind someone:
-- take the slot after theirs, one full token interval later.
local slotAt
if rawResv ~= false and tonumber(rawResv) > now then
    slotAt = tonumber(rawResv) + (requested / refillPerSecond) * 1000
else
    local deficit = requested - available
    if deficit < 0 then
        deficit = 0
    end
    slotAt = now + (deficit / refillPerSecond) * 1000
end
if slotAt - now > reserveOnDenyMaxMs then
    return {0, reserveOnDenyMaxMs, 0}
end
redis.call('hset', key, 'resv', slotAt)
return {0, math.ceil(slotAt - now), 1}
`

const MARK_CLAIM_SPENT_LUA = `
if redis.call('hexists', KEYS[1], 'attempt:' .. ARGV[1]) == 1 and not redis.call('hget', KEYS[1], 'spent') then
    redis.call('hset', KEYS[1], 'spent', ARGV[1])
    return 1
end
return 0
`

const RELEASE_CLAIM_SPEND_LUA = `
if redis.call('hget', KEYS[1], 'spent') == ARGV[1] then
    redis.call('hdel', KEYS[1], 'spent')
    return 1
end
return 0
`

const CLAIM_ALL_OR_NOTHING_ACROSS_LUA = `
local time = redis.call('TIME')
local now = tonumber(time[1]) * 1000 + math.floor(tonumber(time[2]) / 1000)

local claimKey = KEYS[#KEYS]
local claimAttempt = ARGV[#ARGV - 1]
local claimTtlSeconds = tonumber(ARGV[#ARGV])
if claimTtlSeconds == nil or claimTtlSeconds < 1 or claimTtlSeconds > 2147483647 or claimTtlSeconds % 1 ~= 0 then
    return redis.error_reply('invalid ttl for ' .. claimKey)
end
if claimAttempt == nil or claimAttempt == '' then
    return redis.error_reply('invalid attempt for ' .. claimKey)
end
if redis.call('exists', claimKey) == 1 and not redis.call('hget', claimKey, 'spent') then
    redis.call('hset', claimKey, 'attempt:' .. claimAttempt, 1)
    return 1
end

local after = {}
for i = 1, #KEYS - 1 do
    local key = KEYS[i]
    local base = (i - 1) * 4
    local requested = tonumber(ARGV[base + 1])
    local capacity = tonumber(ARGV[base + 2])
    local refillPerSecond = tonumber(ARGV[base + 3])
    local ttlSeconds = tonumber(ARGV[base + 4])
    if ttlSeconds == nil or ttlSeconds < 1 or ttlSeconds > 2147483647 or ttlSeconds % 1 ~= 0 then
        return redis.error_reply('invalid ttl for ' .. key)
    end

    local existing = redis.call('hmget', key, 'ts', 'pool')
    local available = capacity
    if existing[1] ~= false then
        local elapsedMs = math.max(0, now - tonumber(existing[1]))
        local currentTokens = capacity
        if existing[2] ~= false then
            currentTokens = tonumber(existing[2])
        end
        available = math.min(capacity, currentTokens + (elapsedMs / 1000.0) * refillPerSecond)
    end
    if available < requested then
        return 0
    end
    after[i] = available - requested
end

for i = 1, #KEYS - 1 do
    redis.call('hset', KEYS[i], 'ts', now, 'pool', after[i])
    redis.call('expire', KEYS[i], tonumber(ARGV[(i - 1) * 4 + 4]))
end
redis.call('del', claimKey)
redis.call('hset', claimKey, 'attempt:' .. claimAttempt, 1)
redis.call('expire', claimKey, claimTtlSeconds)
return 1
`

export const CLAIM_DEADLINE_MS = 2_000

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
        return (await this.evalClaim(req, 0)).granted
    }

    /**
     * Like claimOrReserve, but the bucket must cover the whole request or grant nothing. A denial
     * consumes no tokens, so a caller retrying a multi-token claim cannot drain the bucket while
     * never succeeding.
     *
     * `retryAfterMs` is null when the limiter itself failed, which is how a caller tells a reached
     * cap from an unreachable Valkey. A denial reports a horizon only when `reserveOnDenyMs` and
     * `refillPerSecond` are both above 0, so `reserveOnDenyMs` has no default: with 0 a reached
     * cap would also read back as null.
     */
    public async claimAllOrNothing(
        req: ClaimRequest,
        reserveOnDenyMs: number
    ): Promise<{ granted: boolean; retryAfterMs: number | null; reserved: boolean }> {
        const { granted, retryAfterMs, reserved } = await this.evalClaim(req, reserveOnDenyMs, true)
        return { granted: granted >= req.requested, retryAfterMs, reserved }
    }

    public async markClaimSpent(claim: { key: string; attempt: string }): Promise<boolean> {
        return await this.evalClaimMark('markClaimSpent', MARK_CLAIM_SPENT_LUA, claim)
    }

    public async releaseClaimSpend(claim: { key: string; attempt: string }): Promise<boolean> {
        return await this.evalClaimMark('releaseClaimSpend', RELEASE_CLAIM_SPEND_LUA, claim)
    }

    private async evalClaimMark(
        operation: string,
        script: string,
        claim: { key: string; attempt: string }
    ): Promise<boolean> {
        try {
            const result = await this.valkey.useClient(
                {
                    name: `rate-limiter:${this.config.name}:${operation}`,
                    timeout: 1000,
                    deadlineMs: CLAIM_DEADLINE_MS,
                },
                (client) => client.eval(script, 1, claim.key, claim.attempt)
            )
            return result === 1
        } catch (err) {
            logger.warn('🪙', `RateLimiterService(${this.config.name}) ${operation} threw`, {
                key: claim.key,
                error: String(err),
            })
            return false
        }
    }

    public async claimAllOrNothingAcross(
        reqs: ClaimRequest[],
        claim: { key: string; attempt: string; ttlSeconds: number }
    ): Promise<'granted' | 'denied' | 'unavailable'> {
        const endTimer = claimLatency.startTimer({ limiter: this.config.name })
        try {
            const result = await this.valkey.useClient(
                {
                    name: `rate-limiter:${this.config.name}:claimAllOrNothingAcross`,
                    timeout: 1000,
                    deadlineMs: CLAIM_DEADLINE_MS,
                },
                (client) =>
                    client.eval(
                        CLAIM_ALL_OR_NOTHING_ACROSS_LUA,
                        reqs.length + 1,
                        ...reqs.map((req) => req.key),
                        claim.key,
                        ...reqs.flatMap((req) => [
                            String(req.requested),
                            String(req.capacity),
                            String(req.refillPerSecond),
                            String(req.ttlSeconds ?? 3600),
                        ]),
                        claim.attempt,
                        String(claim.ttlSeconds)
                    )
            )
            if (result !== 0 && result !== 1) {
                logger.warn('🪙', `RateLimiterService(${this.config.name}) returned invalid grant`, {
                    keys: reqs.map((req) => req.key),
                    raw: result,
                })
                claimCounter.inc({ limiter: this.config.name, result: 'valkey_error' })
                return 'unavailable'
            }
            claimCounter.inc({ limiter: this.config.name, result: result === 1 ? 'granted_full' : 'denied' })
            return result === 1 ? 'granted' : 'denied'
        } catch (err) {
            logger.warn('🪙', `RateLimiterService(${this.config.name}) claim threw`, {
                keys: reqs.map((req) => req.key),
                error: String(err),
            })
            claimCounter.inc({ limiter: this.config.name, result: 'valkey_error' })
            return 'unavailable'
        } finally {
            endTimer()
        }
    }

    /**
     * Like claimUpTo, but when the bucket says no, the caller also gets a time to come
     * back at. First denial: wait only for the missing tokens. Every denial after that:
     * the next slot, one token interval later. A denied backlog lines itself up over
     * the future instead of everyone retrying at once.
     *
     * Slots only go out up to `reserveOnDenyMs` ahead. Past that, `reserved` is false
     * and `retryAfterMs` is just the horizon: many callers get that same answer, so
     * each one must spread its own wake before parking on it. Only a reserved slot
     * (`reserved` true) is the caller's alone and safe to park on as-is.
     *
     * A slot is a place in line, not a promise. The wake still has to claim.
     * `retryAfterMs` is null on grants and when the limiter itself failed.
     */
    public async claimOrReserve(
        req: ClaimRequest,
        reserveOnDenyMs: number
    ): Promise<{ granted: number; retryAfterMs: number | null; reserved: boolean }> {
        return await this.evalClaim(req, reserveOnDenyMs)
    }

    private async evalClaim(
        req: ClaimRequest,
        reserveOnDenyMs: number,
        allOrNothing: boolean = false
    ): Promise<{ granted: number; retryAfterMs: number | null; reserved: boolean }> {
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
                        String(ttlSeconds),
                        String(reserveOnDenyMs),
                        allOrNothing ? '1' : '0'
                    )
            )

            const [granted, retryAfterMs, reserved] = Array.isArray(result) ? result.map(Number) : [NaN, NaN, 0]
            if (!Number.isFinite(granted) || granted < 0) {
                logger.warn('🪙', `RateLimiterService(${this.config.name}) returned invalid grant`, {
                    key: req.key,
                    raw: result,
                })
                claimCounter.inc({ limiter: this.config.name, result: 'valkey_error' })
                return { granted: 0, retryAfterMs: null, reserved: false }
            }

            const outcome = granted === 0 ? 'denied' : granted < req.requested ? 'granted_partial' : 'granted_full'
            claimCounter.inc({ limiter: this.config.name, result: outcome })
            return {
                granted,
                retryAfterMs: Number.isFinite(retryAfterMs) && retryAfterMs > 0 ? retryAfterMs : null,
                reserved: reserved === 1,
            }
        } catch (err) {
            logger.warn('🪙', `RateLimiterService(${this.config.name}) claim threw`, {
                key: req.key,
                error: String(err),
            })
            claimCounter.inc({ limiter: this.config.name, result: 'valkey_error' })
            return { granted: 0, retryAfterMs: null, reserved: false }
        } finally {
            endTimer()
        }
    }
}
