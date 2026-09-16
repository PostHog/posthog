import { PostgresRouter } from '~/common/utils/db/postgres'

import { LogsSourcesCache } from './logs-sources-cache'

describe('LogsSourcesCache', () => {
    let query: jest.Mock
    let cache: LogsSourcesCache
    let nowMs: number

    const rows = (...sources: [string, boolean][]): { rows: { id: string; enabled: boolean }[] } => ({
        rows: sources.map(([id, enabled]) => ({ id, enabled })),
    })

    beforeEach(() => {
        query = jest.fn()
        cache = new LogsSourcesCache({ query } as unknown as PostgresRouter)
        nowMs = 1_700_000_000_000
        jest.spyOn(Date, 'now').mockImplementation(() => nowMs)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('answers from the sources fetched for the team and caches them', async () => {
        query.mockResolvedValueOnce(rows(['src-on', true], ['src-off', false]))

        expect(await cache.getSourceState(1, 'src-on')).toBe('enabled')
        expect(await cache.getSourceState(1, 'src-off')).toBe('disabled')
        expect(await cache.getSourceState(1, 'src-missing')).toBe('unknown')
        expect(query).toHaveBeenCalledTimes(1)
    })

    it('shares one fetch between concurrent lookups for the same team', async () => {
        query.mockResolvedValueOnce(rows(['src-1', true]))

        const states = await Promise.all([
            cache.getSourceState(1, 'src-1'),
            cache.getSourceState(1, 'src-1'),
            cache.getSourceState(1, 'src-2'),
        ])

        expect(states).toEqual(['enabled', 'enabled', 'unknown'])
        expect(query).toHaveBeenCalledTimes(1)
    })

    it('refetches for an id missing from the cached set once the short refresh window passes', async () => {
        query.mockResolvedValueOnce(rows(['src-1', true]))
        await cache.getSourceState(1, 'src-1')

        nowMs += 4_000
        query.mockResolvedValueOnce(rows(['src-1', true], ['src-2', true]))
        expect(await cache.getSourceState(1, 'src-2')).toBe('unknown')
        expect(query).toHaveBeenCalledTimes(1)

        nowMs += 2_000
        expect(await cache.getSourceState(1, 'src-2')).toBe('enabled')
        expect(query).toHaveBeenCalledTimes(2)
    })

    it('fails open when the fetch throws and nothing is cached', async () => {
        query.mockRejectedValueOnce(new Error('pg down'))
        expect(await cache.getSourceState(1, 'src-1')).toBe('enabled')
    })

    it('serves the last-known set when a later refresh throws', async () => {
        query.mockResolvedValueOnce(rows(['src-1', true], ['src-off', false]))
        await cache.getSourceState(1, 'src-1')

        nowMs += 60_000
        query.mockRejectedValueOnce(new Error('pg down'))
        expect(await cache.getSourceState(1, 'src-off')).toBe('disabled')
    })
})
