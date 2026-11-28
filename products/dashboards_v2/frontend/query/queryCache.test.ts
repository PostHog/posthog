import { MAX_CACHED_QUERIES, cachedResult, runCachedQuery } from './queryCache'
import type { QueryResult, RunQuery } from './queryTypes'

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
        expect(cachedResult(runQuery, KEY)).toEqual({ result: RESULT, stale: false })
    })

    it('runs a query again after a refresh, and once for every tile showing it', async () => {
        const fresh: QueryResult = { frames: [{ fields: [] }] }
        const runQuery = jest
            .fn<ReturnType<RunQuery>, Parameters<RunQuery>>()
            .mockResolvedValueOnce(RESULT)
            .mockResolvedValue(fresh)

        await runCachedQuery(runQuery, KEY)
        const first = runCachedQuery(runQuery, KEY, 1)
        const second = runCachedQuery(runQuery, KEY, 1)

        await expect(first).resolves.toBe(fresh)
        await expect(second).resolves.toBe(fresh)
        expect(runQuery).toHaveBeenCalledTimes(2)
        expect(cachedResult(runQuery, KEY, 1)).toEqual({ result: fresh, stale: false })
    })

    it('marks a result from before a refresh as stale until the query runs again', async () => {
        const runQuery = jest.fn<ReturnType<RunQuery>, Parameters<RunQuery>>().mockResolvedValue(RESULT)

        await runCachedQuery(runQuery, KEY)

        expect(cachedResult(runQuery, KEY, 1)).toEqual({ result: RESULT, stale: true })
    })

    it('waits for a query still in flight instead of running it again on a refresh', async () => {
        let finish: (result: QueryResult) => void = () => {}
        const runQuery = jest
            .fn<ReturnType<RunQuery>, Parameters<RunQuery>>()
            .mockReturnValue(new Promise((resolve) => (finish = resolve)))

        const first = runCachedQuery(runQuery, KEY)
        const afterRefresh = runCachedQuery(runQuery, KEY, 1)
        finish(RESULT)

        await expect(first).resolves.toBe(RESULT)
        await expect(afterRefresh).resolves.toBe(RESULT)
        expect(runQuery).toHaveBeenCalledTimes(1)
    })

    it('aborts a query in flight once no tile waits for it, and runs it again on the next mount', async () => {
        const runQuery = jest
            .fn<ReturnType<RunQuery>, Parameters<RunQuery>>()
            .mockImplementation(
                (_request, signal) =>
                    new Promise((_resolve, reject) =>
                        signal?.addEventListener('abort', () => reject(new Error('aborted')))
                    )
            )
        const [first, second] = [new AbortController(), new AbortController()]
        void runCachedQuery(runQuery, KEY, 0, first.signal).catch(() => {})
        void runCachedQuery(runQuery, KEY, 0, second.signal).catch(() => {})
        await Promise.resolve()
        const runnerSignal = runQuery.mock.calls[0][1]!

        first.abort()
        await Promise.resolve()
        expect(runnerSignal.aborted).toBe(false)
        second.abort()
        await Promise.resolve()
        expect(runnerSignal.aborted).toBe(true)

        void runCachedQuery(runQuery, KEY).catch(() => {})
        await Promise.resolve()
        expect(runQuery).toHaveBeenCalledTimes(2)
    })

    it('aborts a query in flight once no tile waits for it, even after the cache evicted it', async () => {
        const runQuery = jest.fn<ReturnType<RunQuery>, Parameters<RunQuery>>().mockReturnValue(new Promise(() => {}))
        const keyFor = (n: number): string => JSON.stringify({ language: 'hogql', query: `select ${n}` })
        const gone = new AbortController()
        void runCachedQuery(runQuery, keyFor(0), 0, gone.signal)
        for (let n = 1; n <= MAX_CACHED_QUERIES; n++) {
            void runCachedQuery(runQuery, keyFor(n))
        }
        await Promise.resolve()

        gone.abort()
        await Promise.resolve()

        expect(runQuery.mock.calls[0][1]?.aborted).toBe(true)
    })

    it('keeps a query in flight when its tile asks again in the same task, such as on a refresh', async () => {
        const runQuery = jest.fn<ReturnType<RunQuery>, Parameters<RunQuery>>().mockReturnValue(new Promise(() => {}))
        const before = new AbortController()
        void runCachedQuery(runQuery, KEY, 0, before.signal)
        await Promise.resolve()

        before.abort()
        void runCachedQuery(runQuery, KEY, 1, new AbortController().signal)
        await Promise.resolve()

        expect(runQuery.mock.calls[0][1]?.aborted).toBe(false)
        expect(runQuery).toHaveBeenCalledTimes(1)
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

        expect(cachedResult(runQuery, keyFor(0))?.result).toBe(RESULT)
        expect(cachedResult(runQuery, keyFor(1))).toBeUndefined()
    })
})
