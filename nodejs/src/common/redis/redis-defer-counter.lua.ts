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

local pending = redis.call('zcard', key)

if pending >= maxDeferred then
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
