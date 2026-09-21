import { DEFAULT_JITTER_FACTOR, retryIfRetriable } from '~/common/utils/retries'

describe('retryIfRetriable jitter', () => {
    function captureSleeps(): number[] {
        const sleeps: number[] = []
        jest.spyOn(global, 'setTimeout').mockImplementation(((fn: () => void, ms?: number) => {
            sleeps.push(ms ?? 0)
            fn()
            return 0 as unknown as NodeJS.Timeout
        }) as typeof setTimeout)
        return sleeps
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

    afterEach(() => jest.restoreAllMocks())

    it('jitters each sleep down by up to the default factor', async () => {
        const sleeps = captureSleeps()
        jest.spyOn(Math, 'random').mockReturnValue(0) // worst case: the full downward jitter
        await retryIfRetriable(failThenSucceed(2), 5, 100)
        // 100 and 200 backoff, each scaled by (1 - DEFAULT_JITTER_FACTOR).
        expect(sleeps).toEqual([100 * (1 - DEFAULT_JITTER_FACTOR), 200 * (1 - DEFAULT_JITTER_FACTOR)])
    })

    it('is deterministic when jitter is explicitly disabled', async () => {
        const sleeps = captureSleeps()
        await retryIfRetriable(failThenSucceed(2), 5, 100, 0)
        expect(sleeps).toEqual([100, 200])
    })

    it('applies a stronger jitter factor when asked', async () => {
        const sleeps = captureSleeps()
        jest.spyOn(Math, 'random').mockReturnValue(0)
        await retryIfRetriable(failThenSucceed(1), 5, 100, 1) // full jitter -> floor is 0
        expect(sleeps[0]).toBe(0)
    })
})
