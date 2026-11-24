import { MAX_CACHED_QUERIES, cachedFrames, runCachedQuery } from './queryCache'
import type { DataFrame, RunQuery } from './vizTypes'

const KEY = JSON.stringify({ language: 'hogql', query: 'select 1' })
const FRAMES = [{ fields: [] }] as unknown as DataFrame[]

describe('queryCache', () => {
    it('runs a query once, even when a tile mounts again while it is in flight or after it finished', async () => {
        const runQuery = jest.fn<ReturnType<RunQuery>, Parameters<RunQuery>>().mockResolvedValue(FRAMES)

        const first = runCachedQuery(runQuery, KEY)
        const second = runCachedQuery(runQuery, KEY)
        await expect(first).resolves.toBe(FRAMES)
        await expect(second).resolves.toBe(FRAMES)
        await runCachedQuery(runQuery, KEY)

        expect(runQuery).toHaveBeenCalledTimes(1)
        expect(cachedFrames(runQuery, KEY)).toBe(FRAMES)
    })

    it('runs a failed query again on the next mount', async () => {
        const runQuery = jest
            .fn<ReturnType<RunQuery>, Parameters<RunQuery>>()
            .mockRejectedValueOnce(new Error('timed out'))
            .mockResolvedValue(FRAMES)

        await expect(runCachedQuery(runQuery, KEY)).rejects.toThrow('timed out')

        await expect(runCachedQuery(runQuery, KEY)).resolves.toBe(FRAMES)
        expect(runQuery).toHaveBeenCalledTimes(2)
    })

    it('drops the least recently used result once the cache is full', async () => {
        const runQuery = jest.fn<ReturnType<RunQuery>, Parameters<RunQuery>>().mockResolvedValue(FRAMES)
        const keyFor = (n: number): string => JSON.stringify({ language: 'hogql', query: `select ${n}` })

        for (let n = 0; n < MAX_CACHED_QUERIES; n++) {
            await runCachedQuery(runQuery, keyFor(n))
        }
        await runCachedQuery(runQuery, keyFor(0))
        await runCachedQuery(runQuery, keyFor(MAX_CACHED_QUERIES))

        expect(cachedFrames(runQuery, keyFor(0))).toBe(FRAMES)
        expect(cachedFrames(runQuery, keyFor(1))).toBeUndefined()
    })
})
