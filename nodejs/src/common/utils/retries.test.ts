import { retryIfRetriable } from '~/common/utils/retries'

describe('retryIfRetriable jitter', () => {
    it('is deterministic when no jitter factor is given (existing callers unaffected)', async () => {
        const sleeps: number[] = []
        jest.spyOn(global, 'setTimeout').mockImplementation(((fn: () => void, ms?: number) => {
            sleeps.push(ms ?? 0)
            fn()
            return 0 as unknown as NodeJS.Timeout
        }) as typeof setTimeout)
        let attempts = 0
        const fn = () => {
            attempts++
            if (attempts < 3) {
                return Promise.reject(Object.assign(new Error('x'), { isRetriable: true }))
            }
            return Promise.resolve('ok')
        }
        await retryIfRetriable(fn, 5, 100)
        expect(sleeps).toEqual([100, 200]) // deterministic backoff, no jitter
        jest.restoreAllMocks()
    })

    it('jitters the sleep when a factor is set', async () => {
        const sleeps: number[] = []
        jest.spyOn(global, 'setTimeout').mockImplementation(((fn: () => void, ms?: number) => {
            sleeps.push(ms ?? 0)
            fn()
            return 0 as unknown as NodeJS.Timeout
        }) as typeof setTimeout)
        jest.spyOn(Math, 'random').mockReturnValue(0) // worst case: full-jitter floor
        let attempts = 0
        const fn = () => {
            attempts++
            if (attempts < 2) {
                return Promise.reject(Object.assign(new Error('x'), { isRetriable: true }))
            }
            return Promise.resolve('ok')
        }
        await retryIfRetriable(fn, 5, 100, 1) // full jitter
        expect(sleeps[0]).toBe(0) // 100 * (1 - 1 + 0*1) = 0
        jest.restoreAllMocks()
    })
})
