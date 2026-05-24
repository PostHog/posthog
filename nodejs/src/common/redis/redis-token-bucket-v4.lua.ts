import { Redis } from 'ioredis'

// V4 token-bucket — parametrized by overdraftEnabled + minCost.
//
// Behavior matrix (cost vs available tokensBefore):
//   1. cost <= tokensBefore                   → granted=cost,                           pool=tokensBefore-cost (capped)
//   2. cost  > tokensBefore, overdraft=false  → granted=0,                              pool=tokensBefore (capped) — V2-style preserve
//   3. cost  > tokensBefore, overdraft=true   → granted=floor(max(0,tokensBefore)/minCost)*minCost, pool=tokensBefore-granted
//
// `minCost` is the smallest spend unit the caller cares about. In overdraft mode we
// only drain whole multiples of minCost so the fractional remainder stays in the pool
// — under sustained overload the refill accumulates cross-call until enough has built
// up to grant one minCost worth, instead of being lost on every call.
//
// Return shape: {tokensBefore, tokensAfter, granted}. tokensAfter = -1 whenever
// granted < cost (signals partial-or-no grant for callers using <0 as denial).
const LUA_TOKEN_BUCKET_V4 = `
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local poolMax = tonumber(ARGV[3])
local fillRate = tonumber(ARGV[4])
local expiry = tonumber(ARGV[5])
local overdraftEnabled = tonumber(ARGV[6]) == 1
local minCost = tonumber(ARGV[7])

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
  tokensBefore = currentTokens + (timeDiffSeconds * fillRate)
end

local granted
local poolToStore
if tokensBefore - cost >= 0 then
  granted = cost
  poolToStore = math.min(tokensBefore - cost, poolMax)
elseif overdraftEnabled then
  local available = math.max(0, tokensBefore)
  granted = math.floor(available / minCost) * minCost
  poolToStore = math.min(tokensBefore - granted, poolMax)
else
  granted = 0
  poolToStore = math.min(tokensBefore, poolMax)
end

local tokensAfter
if granted >= cost then
  tokensAfter = poolToStore
else
  tokensAfter = -1
end

local tsToWrite
if before ~= false and now < before then
  tsToWrite = before
else
  tsToWrite = now
end

redis.call('hset', key, 'ts', tsToWrite, 'pool', poolToStore)

if before == false or redis.call('pttl', key) < (expiry * 500) then
  redis.call('expire', key, expiry * 2)
end

return {tokensBefore, tokensAfter, granted}
`

export const defineLuaTokenBucketV4 = (client: Redis) => {
    client.defineCommand('checkRateLimitV4', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET_V4,
    })
}
