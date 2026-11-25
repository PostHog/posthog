import { MAX_CACHED_QUERIES, cachedResult, runCachedQuery } from './queryCache'
import type { QueryResult, RunQuery } from './vizTypes'

const KEY = JSON.stringify({ language: 'hogql', query: 'select 1' })
const RESULT: QueryResult = { frames: [{ fields: [] }] }

describe('queryCache', () => {
    it('runs a query once, even when a tile mounts again while it is in flight or after it finished', async () => {
        const runQuery = jest.fn<ReturnType<RunQuery>, Parameters<RunQuery>>().mockResolvedValue(RESULT)

        const first = runCachedQuery(runQuery, KEY)
        const second = runCachedQuery(runQuery, KEY)
        await expect(first).resolves.toBe(RESULT)
        await expect(second).resolves.toBe(RESULT)
        await runCachedQuery(runQuery, KEY)

        expect(runQuery).toHaveBeenCalledTimes(1)
        expect(cachedResult(runQuery, KEY)).toBe(RESULT)
    })

    it('runs a failed query again on the next mount', async () => {
        const runQuery = jest
            .fn<ReturnType<RunQuery>, Parameters<RunQuery>>()
            .mockRejectedValueOnce(new Error('timed out'))
            .mockResolvedValue(RESULT)

        await expect(runCachedQuery(runQuery, KEY)).rejects.toThrow('timed out')

        await expect(runCachedQuery(runQuery, KEY)).resolves.toBe(RESULT)
        expect(runQuery).toHaveBeenCalledTimes(2)
    })

    it('drops the least recently used result once the cache is full', async () => {
        const runQuery = jest.fn<ReturnType<RunQuery>, Parameters<RunQuery>>().mockResolvedValue(RESULT)
        const keyFor = (n: number): string => JSON.stringify({ language: 'hogql', query: `select ${n}` })

        for (let n = 0; n < MAX_CACHED_QUERIES; n++) {
            await runCachedQuery(runQuery, keyFor(n))
        }
        await runCachedQuery(runQuery, keyFor(0))
        await runCachedQuery(runQuery, keyFor(MAX_CACHED_QUERIES))

        expect(cachedResult(runQuery, keyFor(0))).toBe(RESULT)
        expect(cachedResult(runQuery, keyFor(1))).toBeUndefined()
    })
})
