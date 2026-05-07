import { Redis } from 'ioredis'

const LUA_TOKEN_BUCKET = `
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
  if poolMax - cost >= 0 then
    tokensAfter = poolMax - cost
  else
    tokensAfter = -1
  end
  redis.call('hset', key, 'ts', now)
  redis.call('hset', key, 'pool', tokensAfter)
  redis.call('expire', key, expiry)
  return {tokensBefore, tokensAfter}
end

local timeDiffSeconds = now - before
if timeDiffSeconds < 0 then
  timeDiffSeconds = 0
end

-- Calculate how much should be refilled in the bucket and add it.
-- tonumber() + fallback handles both a missing pool field and any stored
-- value coming back as a string.
local owedTokens = timeDiffSeconds * fillRate
local currentTokens = tonumber(redis.call('hget', key, 'pool')) or poolMax

currentTokens = currentTokens + owedTokens

-- Store tokens before cost deduction
local tokensBefore = currentTokens

-- Remove the cost and calculate tokens after; cap stored pool at poolMax so silent
-- periods do not let saved credit grow unbounded across many calls.
local tokensAfter
if currentTokens - cost >= 0 then
  tokensAfter = math.min(currentTokens - cost, poolMax)
  -- Only commit ts/pool on a successful consumption. When rate-limited we
  -- leave both fields untouched so the refill credit (timeDiffSeconds) keeps
  -- accumulating across subsequent calls — otherwise continuous traffic that
  -- can't afford the cost would reset ts on every call and pin the bucket
  -- at -1 forever.
  redis.call('hset', key, 'ts', now)
  redis.call('hset', key, 'pool', tokensAfter)
else
  tokensAfter = -1
end

redis.call('expire', key, expiry)

-- Return both values for partial allowance calculation
return {tokensBefore, tokensAfter}
`

export const defineLuaTokenBucket = (client: Redis) => {
    // NOTE: We removed the original command and both checks point at the new one
    // Once deployed, we can follow up to use the non-v2 caller
    client.defineCommand('checkRateLimit', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET,
    })

    client.defineCommand('checkRateLimitV2', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET,
    })
}
