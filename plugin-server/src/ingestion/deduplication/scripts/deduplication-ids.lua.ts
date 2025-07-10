// deduplication-ids.lua.ts

const deduplicationIdsScript = `
-- ARGV[1]: TTL in seconds
-- KEYS: list of event IDs

local ttl = tonumber(ARGV[1])
local duplicates = {}

for i, key in ipairs(KEYS) do
    local success = redis.call('SET', key, '1', 'NX', 'EX', ttl)
    if not success then
        redis.call('EXPIRE', key, ttl)
        table.insert(duplicates, key)
    end
end

return duplicates
`

export default deduplicationIdsScript
