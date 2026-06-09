import { PostgresRouter } from '~/utils/db/postgres'

import { SamplingRulesCache } from './sampling-rules-cache'

const RULE_ROW = {
    id: 'r1',
    rule_type: 'rate_limit',
    scope_service: null,
    scope_path_pattern: null,
    scope_attribute_filters: [],
    config: { kb_per_second: 1, burst_kb: 10 },
    version: '1',
}

function cacheWith(query: jest.Mock): SamplingRulesCache {
    return new SamplingRulesCache({ query } as unknown as PostgresRouter)
}

describe('SamplingRulesCache', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('compiles rules fetched from postgres', async () => {
        const cache = cacheWith(jest.fn().mockResolvedValue({ rows: [RULE_ROW] }))
        const ruleSet = await cache.getCompiledRuleSet(1)
        expect(ruleSet.rules).toHaveLength(1)
        expect(ruleSet.hasRateLimitRules).toBe(true)
    })

    it('fails open to passthrough (empty) when the fetch throws and nothing is cached', async () => {
        const cache = cacheWith(jest.fn().mockRejectedValue(new Error('getaddrinfo ENOTFOUND pgbouncer-cloud-read')))
        // Must not throw — a read-replica outage cannot be allowed to DLQ log ingestion.
        const ruleSet = await cache.getCompiledRuleSet(1)
        expect(ruleSet).toEqual({ rules: [], hasRateLimitRules: false })
    })

    it('serves the last-good ruleset when a later fetch throws', async () => {
        const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(0)
        const query = jest
            .fn()
            .mockResolvedValueOnce({ rows: [RULE_ROW] })
            .mockRejectedValueOnce(new Error('ENOTFOUND pgbouncer-cloud-read'))
        const cache = cacheWith(query)

        const first = await cache.getCompiledRuleSet(1)
        expect(first.hasRateLimitRules).toBe(true)

        // Expire the cache window so the next call refetches — and that fetch fails.
        nowSpy.mockReturnValue(31_000)
        const second = await cache.getCompiledRuleSet(1)
        expect(second.hasRateLimitRules).toBe(true) // stale served, not empty
        expect(query).toHaveBeenCalledTimes(2)
    })

    it('backs off to one retry per refresh window after an error (no per-message refetch)', async () => {
        const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(0)
        const query = jest.fn().mockRejectedValue(new Error('boom'))
        const cache = cacheWith(query)

        await cache.getCompiledRuleSet(1) // fails open, caches empty + stamps fetchedAtMs
        nowSpy.mockReturnValue(5_000) // still within the 30s window
        await cache.getCompiledRuleSet(1) // cache hit — must not hit the failing query again
        expect(query).toHaveBeenCalledTimes(1)
    })

    it('fails open when the fetch hangs past the timeout', async () => {
        jest.useFakeTimers()
        const cache = cacheWith(jest.fn().mockReturnValue(new Promise(() => {}))) // never resolves
        const promise = cache.getCompiledRuleSet(1)
        await jest.advanceTimersByTimeAsync(5_001)
        await expect(promise).resolves.toEqual({ rules: [], hasRateLimitRules: false })
    })
})
