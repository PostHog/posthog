import { Redis } from 'ioredis'

// Per-issue guarded token-bucket script. Error-tracking-exclusive.
//
// Combines the v3 token-bucket body with two guard primitives that defend
// against attackers fuzzing exception payloads to mint unbounded unique
// per-issue Redis keys:
//
//   1. A per-team, per-window counter of new bucket-key creations.
//      When it crosses `threshold`, we SET a per-team fallback flag.
//   2. A per-team fallback flag. While set, every event for the team
//      short-circuits this script (no INCR, no bucket creation).
//
// KEYS:
//   [1] fallback_flag_key   per-team: marks "team is in fallback right now"
//   [2] counter_key         per-team-per-window: new bucket keys created
//   [3] bucket_key          per-sig: the token bucket (v3-compatible layout)
//
// ARGV:
//   [1] now (seconds)       caller-supplied timestamp, for lag-aware limiting
//   [2] cost
//   [3] poolMax
//   [4] fillRate
//   [5] bucketExpiry        token-bucket TTL (matches v3 semantics: stored at expiry*2)
//   [6] threshold           max new bucket keys per window before tripping
//   [7] windowTtlSeconds    counter key TTL (window length)
//   [8] fallbackTtlSeconds  fallback flag TTL (cooldown)
//
// Returns: { tokensBefore, tokensAfter, statusCode }
//   statusCode: 0=allowed, 1=limited, 2=tripped, 3=fallback
//
// For statusCode 2/3 the token-bucket body is skipped — the bucket key is
// not written, so this is the hard cap on attacker-controlled key creation.
const LUA_TOKEN_BUCKET_GUARDED = `
local fallback_key = KEYS[1]
local counter_key = KEYS[2]
local key = KEYS[3]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local poolMax = tonumber(ARGV[3])
local fillRate = tonumber(ARGV[4])
local expiry = tonumber(ARGV[5])
local threshold = tonumber(ARGV[6])
local window_ttl = tonumber(ARGV[7])
local fallback_ttl = tonumber(ARGV[8])

if redis.call('exists', fallback_key) == 1 then
  return {0, 0, 3}
end

local is_new = (redis.call('exists', key) == 0)
if is_new then
  local count = redis.call('incr', counter_key)
  if count == 1 then
    redis.call('expire', counter_key, window_ttl)
  end
  if count > threshold then
    redis.call('set', fallback_key, '1', 'ex', fallback_ttl)
    return {0, 0, 2}
  end
end

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
  tokensBefore = currentTokens + (timeDiffSeconds * fillRate)
end

local tokensAfter
local poolToStore
if tokensBefore - cost >= 0 then
  tokensAfter = math.min(tokensBefore - cost, poolMax)
  poolToStore = tokensAfter
else
  tokensAfter = -1
  local available = math.max(0, tokensBefore)
  poolToStore = math.min(tokensBefore - math.floor(available), poolMax)
end

local tsToWrite
if before ~= false and now < before then
  tsToWrite = before
else
  tsToWrite = now
end

redis.call('hset', key, 'ts', tsToWrite, 'pool', poolToStore)

if before == false or redis.call('pttl', key) < (expiry * 500) then
  redis.call('expire', key, expiry * 2)
end

local status_code
if tokensAfter == -1 then
  status_code = 1
else
  status_code = 0
end

return {tokensBefore, tokensAfter, status_code}
`

export const defineLuaTokenBucketGuarded = (client: Redis): void => {
    client.defineCommand('checkGuardedRateLimit', {
        numberOfKeys: 3,
        lua: LUA_TOKEN_BUCKET_GUARDED,
    })
}
