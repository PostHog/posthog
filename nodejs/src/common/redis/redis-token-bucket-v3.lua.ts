import { Redis } from 'ioredis'
import { Counter, Histogram } from 'prom-client'

import { calculateSlot } from './cluster-slot'
import type { RedisClient } from './redis-v2'

// Prom metrics for the multi-key dispatch — track how well slot-grouping works
// in production. Cluster mode (Valkey Serverless) requires multi-key scripts to
// have all keys in the same slot, so we group inputs by slot before dispatch.
//   buckets_total / groups_total = avg amortization ratio over time
//     = "how many token-bucket ops we packed into one Lua-interpreter setup"
//   slot_fanout histogram shows the distribution of distinct-slot counts per
//   call — useful for spotting scenarios where keys are spread thinly.
const tokenBucketMultiBucketTotal = new Counter({
    name: 'redis_token_bucket_multi_bucket_total',
    help: 'Total token-bucket operations dispatched via checkRateLimitV3Many',
    labelNames: ['caller'],
})
const tokenBucketMultiGroupTotal = new Counter({
    name: 'redis_token_bucket_multi_group_total',
    help: 'Total Lua script dispatches across all checkRateLimitV3Many calls. bucket_total / group_total = avg buckets per Lua call.',
    labelNames: ['caller'],
})
const tokenBucketMultiSlotFanout = new Histogram({
    name: 'redis_token_bucket_multi_slot_fanout',
    help: 'Distinct cluster slots touched per checkRateLimitV3Many invocation. 1 = best amortization; closer to bucket count = worst.',
    labelNames: ['caller'],
    buckets: [1, 2, 4, 8, 16, 32, 64, 128, 256],
})

// V3 multi-key token-bucket script.
//
// Optimizations vs V2 (script CPU was ~95% of Redis cost in prod):
//   1. ts + pool fetched in one HMGET (was two HGETs).
//   2. ts + pool written in one multi-field HSET (was two HSETs).
//   3. EXPIRE writes (expiry * 2) instead of expiry, and only on creation or
//      when the remaining TTL drops below expiry/2 (was unconditional on
//      every call). Cap is one EXPIRE per (expiry * 1.5) window per key.
//      The 2x ceiling gives a 2x safety margin over V2: a key only expires
//      after 2 * expiry of no calls (vs 1 * expiry in V2). PTTL adds ~0.2 μs
//      per call; we save ~95% of EXPIRE dispatches. Stale keys live 2x
//      longer in exchange.
//   4. Multi-key — applies the per-bucket logic to N independent buckets in
//      ONE script invocation, amortizing the ~7 μs Lua-interpreter overhead
//      across all of them. Keys are KEYS[1..N], ARGV is laid out 5 fields per
//      bucket in the same order: now1, cost1, poolMax1, fillRate1, expiry1,
//      now2, cost2, ...
//
// Public output (tokensBefore, tokensAfter) and stored-field semantics are
// identical to V2; only the TTL ceiling, refresh cadence, and call-shape differ.
const LUA_TOKEN_BUCKET_V3_MANY = `
local results = {}
for i = 1, #KEYS do
  local key = KEYS[i]
  local argBase = (i - 1) * 5
  local now = tonumber(ARGV[argBase + 1])
  local cost = tonumber(ARGV[argBase + 2])
  local poolMax = tonumber(ARGV[argBase + 3])
  local fillRate = tonumber(ARGV[argBase + 4])
  local expiry = tonumber(ARGV[argBase + 5])

  local existing = redis.call('hmget', key, 'ts', 'pool')
  local rawBefore = existing[1]
  local rawPool = existing[2]

  local tokensBefore
  local before
  if rawBefore == false then
    before = false
    tokensBefore = poolMax
  else
    before = tonumber(rawBefore)
    local timeDiffSeconds = now - before
    if timeDiffSeconds < 0 then
      timeDiffSeconds = 0
    end
    local currentTokens
    if rawPool == false then
      currentTokens = poolMax
    else
      currentTokens = tonumber(rawPool)
    end
    -- tokensBefore is the uncapped accrued credit. A catch-up call after a long
    -- silent period can therefore spend more than poolMax in one go. The cap is
    -- applied below on tokensAfter so the *stored* pool can never exceed poolMax.
    tokensBefore = currentTokens + (timeDiffSeconds * fillRate)
  end

  local tokensAfter
  if tokensBefore - cost >= 0 then
    tokensAfter = math.min(tokensBefore - cost, poolMax)
  else
    tokensAfter = -1
  end

  -- Don't regress ts when now < before; otherwise advance to now.
  local tsToWrite
  if before ~= false and now < before then
    tsToWrite = before
  else
    tsToWrite = now
  end

  redis.call('hset', key, 'ts', tsToWrite, 'pool', tokensAfter)

  -- Set TTL ceiling at (expiry * 2) on creation, then refresh when remaining
  -- TTL drops below expiry/2. PTTL returns -1 (no TTL) and -2 (missing key)
  -- which are both < any positive threshold, so the refresh fires defensively
  -- if the TTL is ever lost.
  if before == false or redis.call('pttl', key) < (expiry * 500) then
    redis.call('expire', key, expiry * 2)
  end

  results[i] = {tokensBefore, tokensAfter}
end
return results
`

export const defineLuaTokenBucketV3 = (client: Redis) => {
    // numberOfKeys is dynamic — first call argument carries the keys count.
    client.defineCommand('checkRateLimitV3Many', {
        lua: LUA_TOKEN_BUCKET_V3_MANY,
    })
}

export type RateLimitBucket = {
    key: string
    now: number
    cost: number
    poolMax: number
    fillRate: number
    expiry: number
}

/**
 * Typed wrapper for the multi-key V3 token bucket script.
 *
 * Buckets are grouped by their Redis cluster slot before dispatch — keys in
 * the same slot share a single Lua call (full multi-key amortization), while
 * different slots get their own concurrent call. This satisfies Redis Cluster
 * / Valkey Serverless's "all keys in one slot" rule for multi-key scripts
 * without forcing every key onto one shard via hash tags.
 *
 * Result order matches input order regardless of slot grouping.
 */
export async function checkRateLimitV3Many(
    client: RedisClient,
    buckets: RateLimitBucket[],
    caller: string
): Promise<Array<[number, number]>> {
    if (buckets.length === 0) {
        return []
    }

    // Group by cluster slot, preserving original index for result reassembly.
    type Item = { bucket: RateLimitBucket; index: number }
    const groups = new Map<number, Item[]>()
    buckets.forEach((bucket, index) => {
        const slot = calculateSlot(bucket.key)
        const existing = groups.get(slot)
        if (existing) {
            existing.push({ bucket, index })
        } else {
            groups.set(slot, [{ bucket, index }])
        }
    })

    tokenBucketMultiBucketTotal.inc({ caller }, buckets.length)
    tokenBucketMultiGroupTotal.inc({ caller }, groups.size)
    tokenBucketMultiSlotFanout.observe({ caller }, groups.size)

    const results: Array<[number, number]> = new Array(buckets.length)
    await Promise.all(
        [...groups.values()].map(async (group) => {
            const argv: Array<string | number> = [group.length]
            for (const { bucket } of group) {
                argv.push(bucket.key)
            }
            for (const { bucket } of group) {
                argv.push(bucket.now, bucket.cost, bucket.poolMax, bucket.fillRate, bucket.expiry)
            }
            const tuples = await client.checkRateLimitV3Many(...argv)
            group.forEach(({ index }, i) => {
                results[index] = tuples[i]
            })
        })
    )
    return results
}
