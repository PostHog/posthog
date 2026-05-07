import { Redis } from 'ioredis'

// V3 optimizations vs V2 (script CPU was ~95% of Redis cost in prod):
//   1. ts + pool fetched in one HMGET (was two HGETs).
//   2. ts + pool written in one multi-field HSET (was two HSETs).
//   3. EXPIRE only on key creation; subsequent calls refresh only when the
//      remaining TTL drops below expiry/2 (was unconditional on every call).
//      Deterministic — adds one PTTL per call (~0.2 μs) but caps EXPIREs at
//      one per expiry/2 window per key. Safe even for low-traffic keys: the
//      key cannot expire while it's still being hit, because PTTL falling
//      below the threshold guarantees a refresh.
// Public output (tokensBefore, tokensAfter) and stored-field semantics are
// identical to V2; only the TTL refresh cadence differs.
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

-- Always set TTL on creation; otherwise only refresh when remaining TTL has
-- dropped below expiry/2. PTTL returns ms; expiry is seconds, so the threshold
-- is (expiry * 500). PTTL also returns -1 (no TTL) and -2 (missing key) which
-- are both < any positive threshold, so the refresh fires defensively if the
-- TTL is ever lost.
if before == false or redis.call('pttl', key) < (expiry * 500) then
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
