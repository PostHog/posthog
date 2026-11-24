import { PostgresRouter } from '~/common/utils/db/postgres'

import { SamplingRulesCache } from './sampling-rules-cache'

describe('SamplingRulesCache', () => {
    let query: jest.Mock
    let cache: SamplingRulesCache

    const row = (id: string, ruleType: string) => ({
        id,
        rule_type: ruleType,
        scope_service: null,
        scope_path_pattern: null,
        scope_attribute_filters: [],
        config: ruleType === 'path_drop' ? { patterns: ['/healthz'] } : { actions: { INFO: { type: 'drop' } } },
        version: '1',
    })

    beforeEach(() => {
        query = jest.fn()
        cache = new SamplingRulesCache({ query } as unknown as PostgresRouter)
    })

    it('reads only the requested source and caches each source apart', async () => {
        query.mockResolvedValueOnce({ rows: [row('span-rule', 'path_drop')] })
        const spanRules = await cache.getCompiledRuleSet(1, 'spans')
        expect(query.mock.calls[0][2]).toEqual([1, 'spans'])

        // Same team, other source: the cached span rules must not be served to the logs consumer.
        query.mockResolvedValueOnce({ rows: [row('log-rule', 'path_drop')] })
        const logRules = await cache.getCompiledRuleSet(1)
        expect(query.mock.calls[1][2]).toEqual([1, 'logs'])

        expect(spanRules.rules.map((r) => r.id)).toEqual(['span-rule'])
        expect(logRules.rules.map((r) => r.id)).toEqual(['log-rule'])
    })

    it('never compiles a severity rule for spans, because a span has no severity to rank', async () => {
        query.mockResolvedValueOnce({ rows: [row('severity', 'severity_sampling'), row('path', 'path_drop')] })

        const compiled = await cache.getCompiledRuleSet(1, 'spans')

        expect(compiled.rules.map((r) => r.id)).toEqual(['path'])
    })

    it('fails open to no rules when the fetch throws and nothing is cached', async () => {
        query.mockRejectedValueOnce(new Error('statement timeout'))

        const compiled = await cache.getCompiledRuleSet(1, 'spans')

        expect(compiled.rules).toEqual([])
    })

    it('waits a cooldown after a failed fetch before it queries again', async () => {
        const start = Date.now()
        const now = jest.spyOn(Date, 'now').mockReturnValue(start)
        query.mockRejectedValueOnce(new Error('statement timeout'))
        await cache.getCompiledRuleSet(1, 'spans')

        now.mockReturnValue(start + 1_000)
        await cache.getCompiledRuleSet(1, 'spans')
        expect(query).toHaveBeenCalledTimes(1)

        now.mockReturnValue(start + 10_000)
        query.mockResolvedValueOnce({ rows: [row('path', 'path_drop')] })
        const recovered = await cache.getCompiledRuleSet(1, 'spans')
        expect(query).toHaveBeenCalledTimes(2)
        expect(recovered.rules.map((r) => r.id)).toEqual(['path'])
    })

    it('serves the last-known rules when a later refresh throws', async () => {
        query.mockResolvedValueOnce({ rows: [row('path', 'path_drop')] })
        await cache.getCompiledRuleSet(1, 'spans')

        jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 60_000)
        query.mockRejectedValueOnce(new Error('statement timeout'))
        const stale = await cache.getCompiledRuleSet(1, 'spans')

        expect(query).toHaveBeenCalledTimes(2)
        expect(stale.rules.map((r) => r.id)).toEqual(['path'])
    })
})
