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

currentTokens = math.min(currentTokens + owedTokens, poolMax)

-- Store tokens before cost deduction
local tokensBefore = currentTokens

-- Remove the cost and calculate tokens after
local tokensAfter
if currentTokens - cost >= 0 then
  tokensAfter = currentTokens - cost
else
  tokensAfter = -1
end

redis.call('hset', key, 'pool', tokensAfter)
redis.call('expire', key, expiry)

-- Return both values for partial allowance calculation
return {tokensBefore, tokensAfter}
`

/**
 * Combined token-bucket + state/lock read in a single evalsha.
 * Takes 3 keys (tokenKey, stateKey, lockKey) and returns
 * [state, lock, tokensBefore, tokensAfter] — replacing what was
 * previously 3 separate pipeline commands (get state, get lock,
 * checkRateLimitV2) with 1, cutting pipeline size by 66%.
 */
const LUA_TOKEN_BUCKET_WITH_STATE = `
local tokenKey = KEYS[1]
local stateKey = KEYS[2]
local lockKey = KEYS[3]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local poolMax = tonumber(ARGV[3])
local fillRate = tonumber(ARGV[4])
local expiry = ARGV[5]

local state = redis.call('get', stateKey) or ''
local lock = redis.call('get', lockKey) or ''

local before = redis.call('hget', tokenKey, 'ts')

if before == false then
  local tokensBefore = poolMax
  local tokensAfter = poolMax - cost >= 0 and poolMax - cost or -1
  redis.call('hmset', tokenKey, 'ts', now, 'pool', tokensAfter)
  redis.call('expire', tokenKey, expiry)
  return {state, lock, tokensBefore, tokensAfter}
end

local timeDiffSeconds = now - before
local updateTs = false

if timeDiffSeconds > 0 then
  updateTs = true
else
  timeDiffSeconds = 0
end

local owedTokens = timeDiffSeconds * fillRate
local currentTokens = redis.call('hget', tokenKey, 'pool')

if currentTokens == false then
  currentTokens = poolMax
end

currentTokens = math.min(currentTokens + owedTokens, poolMax)

local tokensBefore = currentTokens
local tokensAfter = currentTokens - cost >= 0 and currentTokens - cost or -1

if updateTs then
  redis.call('hmset', tokenKey, 'ts', now, 'pool', tokensAfter)
else
  redis.call('hset', tokenKey, 'pool', tokensAfter)
end
redis.call('expire', tokenKey, expiry)

return {state, lock, tokensBefore, tokensAfter}
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

    client.defineCommand('checkRateLimitWithState', {
        numberOfKeys: 3,
        lua: LUA_TOKEN_BUCKET_WITH_STATE,
    })
}
