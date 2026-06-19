import { Redis } from 'ioredis'

// v3 token-bucket + per-team new-key counter + per-team cooldown flag.
// Caps how many unique bucket keys a team can mint per window.
//
// KEYS: [1] cooldown_flag, [2] counter (per-window), [3] bucket
// ARGV: now, cost, poolMax, fillRate, bucketExpiry, threshold, windowTtl, cooldownTtl
// Returns: { tokensBefore, tokensAfter, statusCode } where statusCode is 0=allowed | 1=limited | 2=tripped | 3=cooldown.
// On tripped/cooldown the bucket is not written.
const LUA_TOKEN_BUCKET_GUARDED = `
local cooldown_key = KEYS[1]
local counter_key = KEYS[2]
local key = KEYS[3]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local poolMax = tonumber(ARGV[3])
local fillRate = tonumber(ARGV[4])
local expiry = tonumber(ARGV[5])
local threshold = tonumber(ARGV[6])
local window_ttl = tonumber(ARGV[7])
local cooldown_ttl = tonumber(ARGV[8])

if redis.call('exists', cooldown_key) == 1 then
  return {0, 0, 3}
end

local is_new = (redis.call('exists', key) == 0)
if is_new then
  local count = redis.call('incr', counter_key)
  if count == 1 then
    redis.call('expire', counter_key, window_ttl)
  end
  if count > threshold then
    redis.call('set', cooldown_key, '1', 'ex', cooldown_ttl)
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
