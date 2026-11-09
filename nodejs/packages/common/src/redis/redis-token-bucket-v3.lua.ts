import { Redis } from 'ioredis'

// V3 single-key token-bucket script.
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
//
// Public return matches V2 (tokensAfter=-1 on denial). Stored-pool on overdraft
// differs: V3 floor-drains the available tokens and keeps the fractional remainder
// so refill accumulates cross-batch (V2 preserved the full pre-overdraft balance).
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
  -- tokensBefore is the uncapped accrued credit. A catch-up call after a long
  -- silent period can therefore spend more than poolMax in one go. The cap is
  -- applied below on tokensAfter so the *stored* pool can never exceed poolMax.
  tokensBefore = currentTokens + (timeDiffSeconds * fillRate)
end

-- On overdraft, drain floor(max(0, tokensBefore)) and keep the fractional remainder
-- in the pool. Assumes per-input cost is an integer (≥1) — the fraction can never
-- satisfy one input, so we let it accumulate cross-batch instead of getting wiped
-- each call (which would starve everything under sustained overload).
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

export const defineLuaTokenBucketV3 = (client: Redis) => {
    client.defineCommand('checkRateLimitV3', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET_V3,
    })
}
