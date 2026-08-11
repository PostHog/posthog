import { PostgresRouter } from '~/common/utils/db/postgres'

import { RetentionRulesCache } from './retention-rules-cache'

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
