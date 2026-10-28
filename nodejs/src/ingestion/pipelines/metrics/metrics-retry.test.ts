import { DependencyUnavailableError, MessageSizeTooLarge } from '~/common/utils/db/error'
import { pipelineRetryAttemptsHistogram } from '~/ingestion/framework/metrics'

import { retryAfterFirstFailure } from './metrics-retry'

describe('retryAfterFirstFailure', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        pipelineRetryAttemptsHistogram.reset()
    })
    afterEach(() => jest.useRealTimers())

    const retriable = (): Error => new DependencyUnavailableError('down', 'Kafka', new Error('down'))
    const retryCount = async (outcome: string): Promise<number> => {
        const { values } = await pipelineRetryAttemptsHistogram.get()
        const count = values.find(
            (v) => v.metricName?.endsWith('_count') && v.labels.name === 'test' && v.labels.outcome === outcome
        )
        return count?.value ?? 0
    }

    it('waits the full backoff before each retry, including the first', async () => {
        const fn = jest
            .fn()
            .mockRejectedValueOnce(retriable())
            .mockRejectedValueOnce(retriable())
            .mockResolvedValue('ok')
        const result = retryAfterFirstFailure(fn, { name: 'test', tries: 3, sleepMs: 100, jitter: 0 })

        await jest.advanceTimersByTimeAsync(99)
        expect(fn).toHaveBeenCalledTimes(1)
        await jest.advanceTimersByTimeAsync(1)
        expect(fn).toHaveBeenCalledTimes(2)
        await jest.advanceTimersByTimeAsync(199)
        expect(fn).toHaveBeenCalledTimes(2)
        await jest.advanceTimersByTimeAsync(1)
        await expect(result).resolves.toBe('ok')
        expect(fn).toHaveBeenCalledTimes(3)
        expect(await retryCount('completed')).toBe(1)
    })

    it('retries an error without an isRetriable flag, as librdkafka produce errors are', async () => {
        const fn = jest.fn().mockRejectedValueOnce(new Error('Local: Queue full')).mockResolvedValue('ok')
        const result = retryAfterFirstFailure(fn, { name: 'test', tries: 3, sleepMs: 100 })
        await jest.runAllTimersAsync()
        await expect(result).resolves.toBe('ok')
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('does not retry an error marked non-retriable', async () => {
        const error = new MessageSizeTooLarge('too large', new Error('too large'))
        const fn = jest.fn().mockRejectedValue(error)
        await expect(retryAfterFirstFailure(fn, { name: 'test', tries: 3, sleepMs: 100 })).rejects.toBe(error)
        expect(fn).toHaveBeenCalledTimes(1)
        expect(await retryCount('non_retriable')).toBe(1)
    })

    it('stops at a non-retriable error after a retriable one', async () => {
        const error = new MessageSizeTooLarge('too large', new Error('too large'))
        const fn = jest.fn().mockRejectedValueOnce(retriable()).mockRejectedValue(error)
        const settled = expect(retryAfterFirstFailure(fn, { name: 'test', tries: 5, sleepMs: 100 })).rejects.toBe(error)
        await jest.runAllTimersAsync()
        await settled
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('counts the soft deadline from the first attempt', async () => {
        const error = retriable()
        const fn = jest.fn(async () => {
            await new Promise((resolve) => setTimeout(resolve, 1_000))
            throw error
        })
        const settled = expect(
            retryAfterFirstFailure(fn, { name: 'test', tries: 5, sleepMs: 100, softDeadlineMs: 500 })
        ).rejects.toBe(error)
        await jest.runAllTimersAsync()
        await settled
        expect(fn).toHaveBeenCalledTimes(1)
    })

    it('throws the last error when the tries run out and records nothing for a first-try success', async () => {
        await retryAfterFirstFailure(() => Promise.resolve('ok'), { name: 'test', tries: 3 })
        expect(await retryCount('completed')).toBe(0)

        const error = retriable()
        const fn = jest.fn().mockRejectedValue(error)
        const settled = expect(retryAfterFirstFailure(fn, { name: 'test', tries: 3, sleepMs: 100 })).rejects.toBe(error)
        await jest.runAllTimersAsync()
        await settled
        expect(fn).toHaveBeenCalledTimes(3)
        expect(await retryCount('exhausted')).toBe(1)
    })
})
