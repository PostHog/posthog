import { Redis } from 'ioredis'

// V4 single-key token-bucket script.
//
// Same fast path as V3 (HMGET + multi-field HSET + conditional EXPIRE),
// but restores the V2 denial-path fix that V3 dropped: on denial we still
// return tokensAfter = -1 (caller-side `tokens <= 0` contract is unchanged)
// but persist the un-deducted balance so partial refills accumulate across
// calls. Without this, sub-2 fractional fillRates wedge at -1 forever under
// sustained 1 req/s traffic (e.g. per-issue limits like 100 per 15 min).
//
// Public output (tokensBefore, tokensAfter) is identical to V3. Only the
// stored `pool` field differs on denied calls.
const LUA_TOKEN_BUCKET_V4 = `
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
  -- tokensBefore is the uncapped accrued credit. A catch-up call after a long
  -- silent period can therefore spend more than poolMax in one go. The cap is
  -- applied below on tokensAfter so the *stored* pool can never exceed poolMax.
  tokensBefore = currentTokens + (timeDiffSeconds * fillRate)
end

-- On denial we still return tokensAfter = -1 (preserves the caller-side
-- tokensAfter <= 0 contract) but persist the un-deducted balance so partial
-- refills accumulate across calls. Matches the V2 fix; V3 dropped this and
-- wedges at -1 forever under sustained sub-2 fractional fillRate traffic.
local tokensAfter
local poolToStore
if tokensBefore - cost >= 0 then
  tokensAfter = math.min(tokensBefore - cost, poolMax)
  poolToStore = tokensAfter
else
  tokensAfter = -1
  poolToStore = math.min(tokensBefore, poolMax)
end

-- Don't regress ts when now < before; otherwise advance to now.
local tsToWrite
if before ~= false and now < before then
  tsToWrite = before
else
  tsToWrite = now
end

redis.call('hset', key, 'ts', tsToWrite, 'pool', poolToStore)

-- Set TTL ceiling at (expiry * 2) on creation, then refresh when remaining
-- TTL drops below expiry/2. PTTL returns -1 (no TTL) and -2 (missing key)
-- which are both < any positive threshold, so the refresh fires defensively
-- if the TTL is ever lost.
if before == false or redis.call('pttl', key) < (expiry * 500) then
  redis.call('expire', key, expiry * 2)
end

return {tokensBefore, tokensAfter}
`

export const defineLuaTokenBucketV4 = (client: Redis) => {
    client.defineCommand('checkRateLimitV4', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET_V4,
    })
}
