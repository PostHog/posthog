import { Redis } from 'ioredis'

// V3 optimizations vs V2 (script CPU was ~95% of Redis cost in prod):
//   1. ts + pool fetched in one HMGET (was two HGETs).
//   2. ts + pool written in one multi-field HSET (was two HSETs).
//   3. EXPIRE only on key creation + ~1% probabilistic refresh on hits
//      (was unconditional on every call).
// Public output (tokensBefore, tokensAfter) and stored-field semantics are
// identical to V2; only the TTL refresh strategy differs.
const LUA_TOKEN_BUCKET_V3 = `
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local poolMax = tonumber(ARGV[3])
local fillRate = tonumber(ARGV[4])
local expiry = tonumber(ARGV[5])

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
  tokensBefore = math.min(currentTokens + (timeDiffSeconds * fillRate), poolMax)
end

local tokensAfter
if tokensBefore - cost >= 0 then
  tokensAfter = tokensBefore - cost
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

-- Always set TTL on creation, otherwise refresh ~1% of the time. Cuts EXPIRE
-- dispatch rate ~99x. Safe because each caller's expiry is much larger than
-- the typical inter-call gap on hot keys, and cold keys are allowed to drop.
if before == false or math.random() < 0.01 then
  redis.call('expire', key, expiry)
end

return {tokensBefore, tokensAfter}
`

export const defineLuaTokenBucketV3 = (client: Redis) => {
    client.defineCommand('checkRateLimitV3', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET_V3,
    })
}
