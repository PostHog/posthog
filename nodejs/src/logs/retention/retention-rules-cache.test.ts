import { PostgresRouter } from '~/common/utils/db/postgres'

import {
    RetentionRulesCache,
    logsRetentionRulesDroppedCounter,
    tracesRetentionRulesDroppedCounter,
} from './retention-rules-cache'

async function droppedCount(counter: typeof logsRetentionRulesDroppedCounter, teamId: string): Promise<number> {
    const metric = await counter.get()
    return metric.values.find((v) => v.labels.team_id === teamId)?.value ?? 0
}

describe('RetentionRulesCache', () => {
    let query: jest.Mock
    let cache: RetentionRulesCache

    const rows = (retentionDays: number): { rows: { id: string; config: unknown; version: string }[] } => ({
        rows: [{ id: 'r1', config: { retention_days: retentionDays }, version: '1' }],
    })

    beforeEach(() => {
        query = jest.fn()
        cache = new RetentionRulesCache({ query } as unknown as PostgresRouter)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('compiles rules fetched from Postgres', async () => {
        query.mockResolvedValueOnce(rows(30))
        const compiled = await cache.getCompiledRuleSet(1)
        expect(compiled.rules).toEqual([{ id: 'r1', filterGroup: null, retentionDays: 30 }])
    })

    it.each([
        ['logs', logsRetentionRulesDroppedCounter, tracesRetentionRulesDroppedCounter],
        ['spans', tracesRetentionRulesDroppedCounter, logsRetentionRulesDroppedCounter],
    ] as const)('counts %s rules discarded at compile on that source metric only', async (source, counter, other) => {
        // 45 is not a valid retention tier, so compile discards the row: the rule is enabled and
        // fetched but never stamped — the counter is the only signal of that silent drop.
        query.mockResolvedValueOnce(rows(45))
        const before = await droppedCount(counter, '7')
        const otherBefore = await droppedCount(other, '7')
        const compiled = await cache.getCompiledRuleSet(7, source)
        expect(compiled.rules).toEqual([])
        expect((await droppedCount(counter, '7')) - before).toBe(1)
        expect(await droppedCount(other, '7')).toBe(otherBefore)
    })

    it("reads each source's own table and caches each source apart", async () => {
        query.mockResolvedValueOnce(rows(30))
        await cache.getCompiledRuleSet(1, 'spans')
        expect(query.mock.calls[0][1]).toContain('FROM tracing_tracesretentionrule')

        // Same team, other source: the cached span rules must not be served for logs.
        query.mockResolvedValueOnce(rows(90))
        const logRules = await cache.getCompiledRuleSet(1, 'logs')
        expect(query.mock.calls[1][1]).toContain('FROM logs_logsretentionrule')
        expect(logRules.rules).toEqual([{ id: 'r1', filterGroup: null, retentionDays: 90 }])
    })

    it('defaults to the log source', async () => {
        query.mockResolvedValueOnce(rows(30))
        await cache.getCompiledRuleSet(1)
        expect(query.mock.calls[0][1]).toContain('FROM logs_logsretentionrule')
    })

    it('fails open to no rules when the fetch throws and nothing is cached', async () => {
        query.mockRejectedValueOnce(new Error('pg down'))
        const compiled = await cache.getCompiledRuleSet(1)
        expect(compiled.rules).toEqual([])
    })

    it('serves the last-known rules when a later refresh throws', async () => {
        query.mockResolvedValueOnce(rows(30))
        await cache.getCompiledRuleSet(1)

        jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 60_000)
        query.mockRejectedValueOnce(new Error('pg down'))
        const stale = await cache.getCompiledRuleSet(1)
        expect(stale.rules).toEqual([{ id: 'r1', filterGroup: null, retentionDays: 30 }])
    })
})
