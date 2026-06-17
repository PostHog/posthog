import { retryWithBackoff } from 'lib/utils/async'

describe('async utils', () => {
    describe('retryWithBackoff()', () => {
        it('returns result on first successful attempt', async () => {
            const fn = jest.fn().mockResolvedValue('success')
            const result = await retryWithBackoff(fn, { initialDelayMs: 0 })
            expect(result).toBe('success')
            expect(fn).toHaveBeenCalledTimes(1)
        })

        it('retries on failure and succeeds', async () => {
            const fn = jest
                .fn()
                .mockRejectedValueOnce(new Error('fail 1'))
                .mockRejectedValueOnce(new Error('fail 2'))
                .mockResolvedValue('success')

            const result = await retryWithBackoff(fn, { maxAttempts: 3, initialDelayMs: 0 })
            expect(result).toBe('success')
            expect(fn).toHaveBeenCalledTimes(3)
        })

        it('throws last error after all attempts exhausted', async () => {
            const errors = [new Error('fail 1'), new Error('fail 2'), new Error('fail 3')]
            let callCount = 0
            const fn = jest.fn().mockImplementation(() => Promise.reject(errors[callCount++]))

            await expect(retryWithBackoff(fn, { maxAttempts: 3, initialDelayMs: 0 })).rejects.toThrow('fail 3')
            expect(fn).toHaveBeenCalledTimes(3)
        })

        it('re-throws AbortError immediately without retrying', async () => {
            const fn = jest.fn().mockImplementation(() => {
                const error = new DOMException('Aborted', 'AbortError')
                return Promise.reject(error)
            })

            await expect(retryWithBackoff(fn, { maxAttempts: 3, initialDelayMs: 0 })).rejects.toThrow('Aborted')
            expect(fn).toHaveBeenCalledTimes(1)
        })

        it('throws immediately if signal is already aborted', async () => {
            const controller = new AbortController()
            controller.abort()

            const fn = jest.fn().mockResolvedValue('success')
            await expect(retryWithBackoff(fn, { signal: controller.signal })).rejects.toThrow('Aborted')
            expect(fn).not.toHaveBeenCalled()
        })

        it('applies exponential backoff between retries', async () => {
            jest.useFakeTimers()
            try {
                let callCount = 0
                const fn = jest.fn().mockImplementation(() => {
                    callCount++
                    if (callCount < 3) {
                        return Promise.reject(new Error('fail'))
                    }
                    return Promise.resolve('success')
                })

                const promise = retryWithBackoff(fn, {
                    maxAttempts: 3,
                    initialDelayMs: 1000,
                    backoffMultiplier: 2,
                })

                // First call happens immediately
                await Promise.resolve()
                expect(fn).toHaveBeenCalledTimes(1)

                // After 1000ms (initialDelayMs * 2^0), second attempt
                await jest.advanceTimersByTimeAsync(1000)
                expect(fn).toHaveBeenCalledTimes(2)

                // After 2000ms (initialDelayMs * 2^1), third attempt
                await jest.advanceTimersByTimeAsync(2000)
                expect(fn).toHaveBeenCalledTimes(3)

                await expect(promise).resolves.toBe('success')
            } finally {
                jest.useRealTimers()
            }
        })

        it('uses default options when none provided', async () => {
            const errors = [new Error('fail'), new Error('fail'), new Error('fail')]
            let callCount = 0
            const fn = jest.fn().mockImplementation(() => Promise.reject(errors[callCount++]))

            await expect(retryWithBackoff(fn, { initialDelayMs: 0 })).rejects.toThrow('fail')
            expect(fn).toHaveBeenCalledTimes(3) // default maxAttempts is 3
        })

        it('handles maxAttempts of 1 (no retries)', async () => {
            const fn = jest.fn().mockImplementation(() => Promise.reject(new Error('fail')))

            await expect(retryWithBackoff(fn, { maxAttempts: 1, initialDelayMs: 0 })).rejects.toThrow('fail')
            expect(fn).toHaveBeenCalledTimes(1)
        })

        it('does not retry when shouldRetry returns false', async () => {
            const error = new Error('non-retryable')
            const fn = jest.fn().mockImplementation(() => Promise.reject(error))

            await expect(
                retryWithBackoff(fn, {
                    maxAttempts: 3,
                    initialDelayMs: 0,
                    shouldRetry: () => false,
                })
            ).rejects.toThrow('non-retryable')
            expect(fn).toHaveBeenCalledTimes(1)
        })

        it('retries when shouldRetry returns true', async () => {
            let callCount = 0
            const fn = jest.fn().mockImplementation(() => {
                callCount++
                if (callCount < 3) {
                    return Promise.reject(new Error('retryable'))
                }
                return Promise.resolve('success')
            })

            const result = await retryWithBackoff(fn, {
                maxAttempts: 3,
                initialDelayMs: 0,
                shouldRetry: () => true,
            })
            expect(result).toBe('success')
            expect(fn).toHaveBeenCalledTimes(3)
        })

        it('stops retrying when shouldRetry returns false for specific error', async () => {
            const errors = [new Error('retry-me'), new Error('stop-here'), new Error('never-reached')]
            let callCount = 0
            const fn = jest.fn().mockImplementation(() => Promise.reject(errors[callCount++]))

            await expect(
                retryWithBackoff(fn, {
                    maxAttempts: 3,
                    initialDelayMs: 0,
                    shouldRetry: (e) => e instanceof Error && e.message !== 'stop-here',
                })
            ).rejects.toThrow('stop-here')
            expect(fn).toHaveBeenCalledTimes(2)
        })

        it('receives the error in shouldRetry callback', async () => {
            const testError = new Error('test-error')
            const fn = jest.fn().mockImplementation(() => Promise.reject(testError))
            const shouldRetry = jest.fn().mockReturnValue(false)

            await expect(retryWithBackoff(fn, { maxAttempts: 3, initialDelayMs: 0, shouldRetry })).rejects.toThrow(
                'test-error'
            )
            expect(shouldRetry).toHaveBeenCalledWith(testError)
        })
    })
})
