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
-- periods do not let saved credit grow unbounded across many calls.
local tokensAfter
if currentTokens - cost >= 0 then
  tokensAfter = math.min(currentTokens - cost, poolMax)
else
  tokensAfter = -1
end

redis.call('hset', key, 'pool', tokensAfter)
redis.call('expire', key, expiry)

-- Return both values for partial allowance calculation
return {tokensBefore, tokensAfter}
`

// V3: canonical check-first token bucket. Denied requests don't charge cost,
// so the balance can never go negative. Fixes V2's "wedge under sustained
// traffic" bug at the root: V2 charged on denial and clamped to -1, throwing
// away partial refills. V3 simply doesn't charge if it can't afford the cost,
// so partial refills accumulate cleanly toward the next allowed request.
// Callers derive `isRateLimited` from `tokensBefore < cost` rather than
// looking at the sign of `tokensAfter`.
const LUA_TOKEN_BUCKET_V3 = `
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local poolMax = tonumber(ARGV[3])
local fillRate = tonumber(ARGV[4])
local expiry = ARGV[5]
local before = redis.call('hget', key, 'ts')

if before == false then
  local tokensAfter
  if poolMax >= cost then
    tokensAfter = poolMax - cost
  else
    tokensAfter = poolMax
  end
  redis.call('hset', key, 'ts', now)
  redis.call('hset', key, 'pool', tokensAfter)
  redis.call('expire', key, expiry)
  -- Return as strings: Redis truncates Lua numbers to integers over the wire,
  -- which would destroy fractional balances. Callers must parseFloat.
  return {tostring(poolMax), tostring(tokensAfter)}
end

local timeDiffSeconds = now - before
if timeDiffSeconds > 0 then
  redis.call('hset', key, 'ts', now)
else
  timeDiffSeconds = 0
end

local owedTokens = timeDiffSeconds * fillRate
local currentTokens = redis.call('hget', key, 'pool')
if currentTokens == false then
  currentTokens = poolMax
end

currentTokens = math.min(currentTokens + owedTokens, poolMax)
local tokensBefore = currentTokens

local tokensAfter
if currentTokens >= cost then
  tokensAfter = currentTokens - cost
else
  tokensAfter = currentTokens
end

redis.call('hset', key, 'pool', tokensAfter)
redis.call('expire', key, expiry)

-- Stringify so fractional values survive (Redis ints over the wire otherwise).
return {tostring(tokensBefore), tostring(tokensAfter)}
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

    client.defineCommand('checkRateLimitV3', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET_V3,
    })
}
