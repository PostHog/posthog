import { Redis } from 'ioredis'

// Partial-admission token-bucket script.
//
// Unlike V2/V3 (which make one all-or-nothing decision on a single `cost`), this
// script is told the per-record costs of a batch and admits the longest record
// prefix that fits the current budget. Crucially it debits *exactly* what it
// admits and carries the rest forward (capped at poolMax) — so unspent budget is
// never destroyed and never double-counted. This is what V2 and V3 each got wrong
// for the logs drop-rule limiter:
//   - V2 preserved the full balance on overdraft → never debited under sustained
//     overload → admitted ~poolMax every call (way too much).
//   - V3 floor-drained the balance on overdraft → destroyed accrued budget every
//     call → a record larger than one call's refill could never be admitted (way
//     too little / total starvation).
// The caller does an identical prefix walk over the same costs, so both sides
// agree on which records are kept.
//
// ARGV: now(s, may be fractional), poolMax, fillRate, expiry(s), totalCost, costs...
const LUA_TOKEN_BUCKET_PARTIAL = `
local key = KEYS[1]
local now = tonumber(ARGV[1])
local poolMax = tonumber(ARGV[2])
local fillRate = tonumber(ARGV[3])
local expiry = tonumber(ARGV[4])
local totalCost = tonumber(ARGV[5])

local existing = redis.call('hmget', key, 'ts', 'pool')
local rawBefore = existing[1]
local rawPool = existing[2]

local before
local tokensBefore
if rawBefore == false then
  before = false
  tokensBefore = poolMax
else
  before = tonumber(rawBefore)
  local timeDiff = now - before
  if timeDiff < 0 then timeDiff = 0 end
  local currentTokens
  if rawPool == false then currentTokens = poolMax else currentTokens = tonumber(rawPool) end
  -- Carry-forward bucket: accrue refill but never beyond the burst pool.
  tokensBefore = currentTokens + timeDiff * fillRate
  if tokensBefore > poolMax then tokensBefore = poolMax end
end

local budget = math.floor(tokensBefore)
if budget < 0 then budget = 0 end

local spent
local keptCount
local n = #ARGV - 5
if budget >= totalCost then
  -- Whole batch fits — no need to walk individual records.
  spent = totalCost
  keptCount = n
else
  -- Admit the longest record prefix whose cumulative cost fits the budget, then
  -- stop. Records past the first one that doesn't fit are dropped and their
  -- budget is carried forward (below), not destroyed. The early break keeps the
  -- loop O(admitted prefix) rather than O(batch) in the hot rate-limited path.
  spent = 0
  keptCount = 0
  for i = 6, #ARGV do
    local c = tonumber(ARGV[i])
    if spent + c <= budget then
      spent = spent + c
      keptCount = keptCount + 1
    else
      break
    end
  end
end

local poolToStore = tokensBefore - spent
if poolToStore < 0 then poolToStore = 0 end
if poolToStore > poolMax then poolToStore = poolMax end

-- Don't regress ts when now < before; otherwise advance to now.
local tsToWrite
if before ~= false and now < before then
  tsToWrite = before
else
  tsToWrite = now
end
redis.call('hset', key, 'ts', tsToWrite, 'pool', poolToStore)

-- Match V3's TTL strategy: ceiling at (expiry * 2), refreshed only on creation
-- or once the remaining TTL drops below expiry/2.
if before == false or redis.call('pttl', key) < (expiry * 500) then
  redis.call('expire', key, expiry * 2)
end

return {keptCount, spent}
`

export const defineLuaTokenBucketPartial = (client: Redis) => {
    client.defineCommand('checkRateLimitPartial', {
        numberOfKeys: 1,
        lua: LUA_TOKEN_BUCKET_PARTIAL,
    })
}
