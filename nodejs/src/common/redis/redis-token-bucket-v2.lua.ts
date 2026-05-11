import { Redis } from 'ioredis'

const LUA_TOKEN_BUCKET_V2 = `
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local poolMax = tonumber(ARGV[3])
local fillRate = tonumber(ARGV[4])
local expiry = ARGV[5]
local before = redis.call('hget', key, 'ts')

-- If we don't have a timestamp then we set it to now and fill up the bucket
if before == false then
  local tokensBefore = poolMax
  local tokensAfter
  local poolToStore
  if poolMax - cost >= 0 then
    tokensAfter = poolMax - cost
    poolToStore = tokensAfter
  else
    -- Don't deduct cost we couldn't afford. Public return stays -1 so
    -- callers' tokensAfter <= 0 denial check is unchanged, but we store the
    -- full bucket so an impossible-cost first call doesn't burn the credit.
    tokensAfter = -1
    poolToStore = poolMax
  end
  redis.call('hset', key, 'ts', now)
  redis.call('hset', key, 'pool', poolToStore)
  redis.call('expire', key, expiry)
  return {tokensBefore, tokensAfter}
end

-- We update the timestamp if it has changed
local timeDiffSeconds = now - before

if timeDiffSeconds > 0 then
  redis.call('hset', key, 'ts', now)
else
  timeDiffSeconds = 0
end

-- Calculate how much should be refilled in the bucket and add it
local owedTokens = timeDiffSeconds * fillRate
local currentTokens = redis.call('hget', key, 'pool')

if currentTokens == false then
  currentTokens = poolMax
end

currentTokens = currentTokens + owedTokens

-- Store tokens before cost deduction
local tokensBefore = currentTokens

-- Remove the cost and calculate tokens after; cap stored pool at poolMax so silent
-- periods do not let saved credit grow unbounded across many calls. On denial we
-- still return -1 (preserves caller-side tokensAfter <= 0 contract) but persist the
-- un-deducted balance so partial refills accumulate across calls — without this,
-- sub-2 fractional fillRates wedge at -1 forever under sustained 1 req/s traffic.
local tokensAfter
local poolToStore
if currentTokens - cost >= 0 then
  tokensAfter = math.min(currentTokens - cost, poolMax)
  poolToStore = tokensAfter
else
  tokensAfter = -1
  poolToStore = math.min(currentTokens, poolMax)
end

redis.call('hset', key, 'pool', poolToStore)
redis.call('expire', key, expiry)

-- Return both values for partial allowance calculation
return {tokensBefore, tokensAfter}
`

export const defineLuaTokenBucketV2 = (client: Redis) => {
    client.defineCommand('checkRateLimitV2', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET_V2,
    })
}
