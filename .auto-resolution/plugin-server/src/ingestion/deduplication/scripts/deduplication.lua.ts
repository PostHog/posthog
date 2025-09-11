// deduplication.lua.ts

const deduplicationScript = `
local ttl = tonumber(ARGV[1])
local duplicates = 0
for i, key in ipairs(KEYS) do
    local success = redis.call('SET', key, '1', 'NX', 'EX', ttl)
    if not success then
        redis.call('EXPIRE', key, ttl)
        duplicates = duplicates + 1
    end
end
return duplicates
`

export default deduplicationScript
