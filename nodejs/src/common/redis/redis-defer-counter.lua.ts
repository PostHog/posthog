import { Redis } from 'ioredis'

// Atomic per-flow deferred backlog tracker. Returns [accepted, scheduledAtMs] where
// accepted=1 means the invocation entered the backlog and should run at scheduledAtMs,
// and accepted=0 means the cap is full and the caller should hard-drop.
const LUA_DEFER_COUNTER = `
local key = KEYS[1]
local nowMs = tonumber(ARGV[1])
local refillRate = tonumber(ARGV[2])
local maxDeferred = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local member = ARGV[5]
local graceMs = tonumber(ARGV[6])

-- refillRate=0 would produce infinite scheduled times; treat as full so the caller drops.
if refillRate <= 0 then
  return {0, 0}
end

-- Grace window absorbs Cyclotron worker lag so the cap still holds when workers are behind.
redis.call('zremrangebyscore', key, '-inf', nowMs - graceMs)

-- Idempotent under retries (e.g. Kafka redelivery): if the same invocation is already
-- scheduled, return its existing score instead of bumping it to a later slot.
local existing = redis.call('zscore', key, member)
if existing then
  redis.call('expire', key, ttl)
  return {1, tonumber(existing)}
end

local pending = redis.call('zcard', key)

if pending >= maxDeferred then
  -- Refresh TTL on the rejection path too; a sustained cap-hit would otherwise let the
  -- key expire and silently reset the backlog while prior deferrals are still pending.
  redis.call('expire', key, ttl)
  return {0, 0}
end

local position = pending + 1
local scheduledAtMs = nowMs + math.floor(1000 * position / refillRate)

redis.call('zadd', key, scheduledAtMs, member)
redis.call('expire', key, ttl)

return {1, scheduledAtMs}
`

export const defineLuaDeferCounter = (client: Redis) => {
    client.defineCommand('deferInvocation', {
        numberOfKeys: 1,
        lua: LUA_DEFER_COUNTER,
    })
}
