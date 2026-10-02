import { DEFAULT_JITTER_FACTOR, retryIfRetriable } from '~/common/utils/retries'

describe('retryIfRetriable backoff', () => {
    /** Fake clock the sleeps drive, so elapsed time is deterministic. */
    let now = 0

    function captureSleeps(): number[] {
        const sleeps: number[] = []
        jest.spyOn(Date, 'now').mockImplementation(() => now)
        jest.spyOn(global, 'setTimeout').mockImplementation(((fn: () => void, ms?: number) => {
            sleeps.push(ms ?? 0)
            now += ms ?? 0
            fn()
            return 0 as unknown as NodeJS.Timeout
        }) as typeof setTimeout)
        return sleeps
    }

    function alwaysFails(durationMs = 0): () => Promise<never> {
        return () => {
            now += durationMs
            return Promise.reject(Object.assign(new Error('x'), { isRetriable: true }))
        }
    }

    function failThenSucceed(failures: number): () => Promise<string> {
        let attempts = 0
        return () => {
            attempts++
            if (attempts <= failures) {
                return Promise.reject(Object.assign(new Error('x'), { isRetriable: true }))
            }
            return Promise.resolve('ok')
        }
    }

    beforeEach(() => (now = 0))
    afterEach(() => jest.restoreAllMocks())

    it('jitters each sleep down by up to the default factor', async () => {
        const sleeps = captureSleeps()
        jest.spyOn(Math, 'random').mockReturnValue(0) // worst case: the full downward jitter
        await retryIfRetriable(failThenSucceed(2), { tries: 5, sleepMs: 100 })
        // 100 and 200 backoff, each scaled by (1 - DEFAULT_JITTER_FACTOR).
        expect(sleeps).toEqual([100 * (1 - DEFAULT_JITTER_FACTOR), 200 * (1 - DEFAULT_JITTER_FACTOR)])
    })

    it('is deterministic when jitter is explicitly disabled', async () => {
        const sleeps = captureSleeps()
        await retryIfRetriable(failThenSucceed(2), { tries: 5, sleepMs: 100, jitter: 0 })
        expect(sleeps).toEqual([100, 200])
    })

    it('applies a stronger jitter factor when asked', async () => {
        const sleeps = captureSleeps()
        jest.spyOn(Math, 'random').mockReturnValue(0)
        await retryIfRetriable(failThenSucceed(1), { tries: 5, sleepMs: 100, jitter: 1 }) // full jitter -> floor is 0
        expect(sleeps[0]).toBe(0)
    })

    it('grows each backoff by a custom factor', async () => {
        const sleeps = captureSleeps()
        await retryIfRetriable(failThenSucceed(3), { tries: 5, sleepMs: 100, jitter: 0, backoffFactor: 4 })
        expect(sleeps).toEqual([100, 400, 1600])
    })

    it('caps each backoff at maxSleepMs', async () => {
        const sleeps = captureSleeps()
        await retryIfRetriable(failThenSucceed(3), {
            tries: 5,
            sleepMs: 100,
            jitter: 0,
            backoffFactor: 4,
            maxSleepMs: 500,
        })
        expect(sleeps).toEqual([100, 400, 500])
    })

    it('gives up early once a slow failure spends the soft deadline', async () => {
        const sleeps = captureSleeps()
        const fn = jest.fn(alwaysFails(4000))
        await expect(retryIfRetriable(fn, { tries: 5, sleepMs: 100, jitter: 0, softDeadlineMs: 5000 })).rejects.toThrow(
            'x'
        )
        expect(fn).toHaveBeenCalledTimes(2)
        expect(sleeps).toEqual([100])
    })

    it('lets fast failures use every try within the soft deadline', async () => {
        const sleeps = captureSleeps()
        const fn = jest.fn(alwaysFails())
        await expect(
            retryIfRetriable(fn, { tries: 5, sleepMs: 100, jitter: 0, backoffFactor: 4, softDeadlineMs: 10000 })
        ).rejects.toThrow('x')
        expect(fn).toHaveBeenCalledTimes(5)
        expect(sleeps).toEqual([100, 400, 1600, 6400])
    })

    it('does not start an attempt after a sleep crosses the soft deadline', async () => {
        const sleeps = captureSleeps()
        const fn = jest.fn(alwaysFails(3000))
        await expect(
            retryIfRetriable(fn, { tries: 5, sleepMs: 100, jitter: 0, backoffFactor: 4, softDeadlineMs: 10000 })
        ).rejects.toThrow('x')
        expect(fn).toHaveBeenCalledTimes(3)
        expect(sleeps).toEqual([100, 400, 1600])
    })
})
