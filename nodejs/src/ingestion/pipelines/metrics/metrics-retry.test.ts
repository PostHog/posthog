import { DependencyUnavailableError } from '~/common/utils/db/error'

import { retryAfterFirstFailure } from './metrics-retry'

describe('retryAfterFirstFailure', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    const retriable = (): Error => new DependencyUnavailableError('down', 'Kafka', new Error('down'))

    it('waits the full backoff before each retry, including the first', async () => {
        const fn = jest
            .fn()
            .mockRejectedValueOnce(retriable())
            .mockRejectedValueOnce(retriable())
            .mockResolvedValue('ok')
        const result = retryAfterFirstFailure(fn, { tries: 3, sleepMs: 100, jitter: 0 })

        await jest.advanceTimersByTimeAsync(99)
        expect(fn).toHaveBeenCalledTimes(1)
        await jest.advanceTimersByTimeAsync(1)
        expect(fn).toHaveBeenCalledTimes(2)
        await jest.advanceTimersByTimeAsync(199)
        expect(fn).toHaveBeenCalledTimes(2)
        await jest.advanceTimersByTimeAsync(1)
        await expect(result).resolves.toBe('ok')
        expect(fn).toHaveBeenCalledTimes(3)
    })

    it.each([
        ['a plain error', new Error('boom')],
        ['a non-retriable error', Object.assign(new Error('too large'), { isRetriable: false })],
    ])('does not retry %s', async (_, error) => {
        const fn = jest.fn().mockRejectedValue(error)
        await expect(retryAfterFirstFailure(fn, { tries: 3, sleepMs: 100 })).rejects.toBe(error)
        expect(fn).toHaveBeenCalledTimes(1)
    })

    it('throws the last error when the tries run out', async () => {
        const error = retriable()
        const fn = jest.fn().mockRejectedValue(error)
        const result = retryAfterFirstFailure(fn, { tries: 3, sleepMs: 100, jitter: 0 })
        const settled = expect(result).rejects.toBe(error)
        await jest.runAllTimersAsync()
        await settled
        expect(fn).toHaveBeenCalledTimes(3)
    })
})
