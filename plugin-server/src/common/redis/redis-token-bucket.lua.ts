import { Redis } from 'ioredis'

const LUA_TOKEN_BUCKET = `
local key = KEYS[1]
local now = ARGV[1]
local cost = ARGV[2]
local poolMax = ARGV[3]
local fillRate = ARGV[4]
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

export const defineLuaTokenBucket = (client: Redis) => {
    client.defineCommand('checkRateLimit', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET,
    })
}
