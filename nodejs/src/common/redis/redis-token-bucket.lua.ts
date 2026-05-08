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

// V3: fixes the "wedged at -1 under sustained traffic" bug in V2 (see
// keyed-rate-limiter.service.test.ts). Two changes vs V2:
//   1. Real negative balance is preserved instead of clamped to -1, so a partial
//      refill that didn't quite cover the cost still accumulates across calls.
//   2. The negative side is floored at -poolMax (symmetric with the positive cap)
//      so a single oversized cost can't wedge recovery for hours.
const LUA_TOKEN_BUCKET_V3 = `
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local poolMax = tonumber(ARGV[3])
local fillRate = tonumber(ARGV[4])
local expiry = ARGV[5]
local before = redis.call('hget', key, 'ts')

if before == false then
  local tokensAfter = math.max(poolMax - cost, -poolMax)
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

currentTokens = currentTokens + owedTokens
local tokensBefore = currentTokens

-- Symmetric clamp: cap the positive side at poolMax (otherwise idle gaps
-- compound credit forever), floor the negative side at -poolMax (otherwise
-- one giant cost makes recovery take eternity). Crucially, we do NOT clamp
-- to -1 on overdraft — that's what wedged V2 under sustained traffic.
local tokensAfter = math.max(math.min(currentTokens - cost, poolMax), -poolMax)

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
