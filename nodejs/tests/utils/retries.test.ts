import { logger } from '../../src/utils/logger'
import { getNextRetryMs, retryIfRetriable } from '../../src/utils/retries'

jest.mock('../../src/utils/utils', () => ({
    sleep: jest.fn().mockResolvedValue(undefined),
}))

describe('retryIfRetriable', () => {
    it('does not retry when error.isRetriable is false', async () => {
        const error = new Error('non-retriable') as any
        error.isRetriable = false
        const fn = jest.fn().mockRejectedValue(error)

        await expect(retryIfRetriable(fn, 3, 0)).rejects.toThrow('non-retriable')
        expect(fn).toHaveBeenCalledTimes(1)
    })

    it('retries when error.isRetriable is true', async () => {
        const error = new Error('retriable') as any
        error.isRetriable = true
        const fn = jest.fn().mockRejectedValueOnce(error).mockResolvedValue('ok')

        const result = await retryIfRetriable(fn, 3, 0)
        expect(result).toBe('ok')
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('retries kafka ERR_UNKNOWN (code -1) even when isRetriable is false', async () => {
        const error = new Error('Unknown broker error') as any
        error.isRetriable = false
        error.code = -1
        const fn = jest.fn().mockRejectedValueOnce(error).mockResolvedValue('ok')

        const result = await retryIfRetriable(fn)
        expect(result).toBe('ok')
        // 1 initial attempt + 1 retry in kafka unknown path
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('retries kafka ERR_UNKNOWN (code -1) when isRetriable is not set', async () => {
        const error = new Error('Unknown broker error') as any
        error.code = -1
        const fn = jest.fn().mockRejectedValueOnce(error).mockResolvedValue('ok')

        const result = await retryIfRetriable(fn)
        expect(result).toBe('ok')
        expect(fn).toHaveBeenCalledTimes(2)
    })

    it('throws kafka ERR_UNKNOWN (code -1) after exhausting 5 retries', async () => {
        const error = new Error('Unknown broker error') as any
        error.isRetriable = false
        error.code = -1
        const fn = jest.fn().mockRejectedValue(error)

        await expect(retryIfRetriable(fn)).rejects.toThrow('Unknown broker error')
        // 1 initial attempt in retryIfRetriable + 5 retries in kafka unknown error path
        expect(fn).toHaveBeenCalledTimes(6)
    })

    it('logs on each kafka ERR_UNKNOWN (code -1) retry', async () => {
        const warnSpy = jest.spyOn(logger, 'warn')
        const error = new Error('Unknown broker error') as any
        error.isRetriable = false
        error.code = -1
        const fn = jest.fn().mockRejectedValue(error)

        await expect(retryIfRetriable(fn)).rejects.toThrow('Unknown broker error')
        const kafkaRetryCalls = warnSpy.mock.calls.filter(
            (call) => typeof call[1] === 'string' && call[1].includes('Kafka ERR_UNKNOWN')
        )
        // 5 retries logged (attempts 1/5 through 5/5)
        expect(kafkaRetryCalls).toHaveLength(5)
        warnSpy.mockRestore()
    })
})

describe('getNextRetryMs', () => {
    it('returns the correct number of milliseconds with a multiplier of 1', () => {
        expect(getNextRetryMs(500, 1, 1)).toBe(500)
        expect(getNextRetryMs(500, 1, 2)).toBe(500)
        expect(getNextRetryMs(500, 1, 3)).toBe(500)
        expect(getNextRetryMs(500, 1, 4)).toBe(500)
        expect(getNextRetryMs(500, 1, 5)).toBe(500)
    })

    it('returns the correct number of milliseconds with a multiplier of 2', () => {
        expect(getNextRetryMs(4000, 2, 1)).toBe(4000)
        expect(getNextRetryMs(4000, 2, 2)).toBe(8000)
        expect(getNextRetryMs(4000, 2, 3)).toBe(16000)
        expect(getNextRetryMs(4000, 2, 4)).toBe(32000)
        expect(getNextRetryMs(4000, 2, 5)).toBe(64000)
    })

    it('throws on attempt below 0', () => {
        expect(() => getNextRetryMs(4000, 2, 0)).toThrow('Attempts are indexed starting with 1')
        expect(() => getNextRetryMs(4000, 2, -1)).toThrow('Attempts are indexed starting with 1')
    })
})
