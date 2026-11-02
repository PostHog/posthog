import { Code, ConnectError } from '@connectrpc/connect'

import { withRetry } from './grpc-retry'

jest.mock('~/common/utils/logger')

describe('withRetry', () => {
    it('returns the result on first success', async () => {
        const result = await withRetry(() => Promise.resolve('ok'), 'test-client', 'test-method')
        expect(result).toBe('ok')
    })

    it('retries on transient error and returns result on success', async () => {
        let callCount = 0
        const result = await withRetry(
            () => {
                callCount++
                if (callCount === 1) {
                    throw new ConnectError('transient', Code.Unavailable)
                }
                return Promise.resolve('recovered')
            },
            'test-client',
            'test-method'
        )

        expect(result).toBe('recovered')
        expect(callCount).toBe(2)
    })

    it.each([
        ['Unavailable', Code.Unavailable],
        ['DeadlineExceeded', Code.DeadlineExceeded],
        ['ResourceExhausted', Code.ResourceExhausted],
        ['Aborted', Code.Aborted],
        ['Internal', Code.Internal],
        ['Unknown', Code.Unknown],
        ['Canceled', Code.Canceled],
    ])('retries on %s', async (_name, code) => {
        let callCount = 0
        await withRetry(
            () => {
                callCount++
                if (callCount <= 1) {
                    throw new ConnectError('transient', code)
                }
                return Promise.resolve('ok')
            },
            'test-client',
            'test-method'
        )
        expect(callCount).toBe(2)
    })

    it.each([
        ['InvalidArgument', Code.InvalidArgument],
        ['NotFound', Code.NotFound],
        ['AlreadyExists', Code.AlreadyExists],
        ['PermissionDenied', Code.PermissionDenied],
        ['Unauthenticated', Code.Unauthenticated],
        ['Unimplemented', Code.Unimplemented],
        ['FailedPrecondition', Code.FailedPrecondition],
        ['OutOfRange', Code.OutOfRange],
        ['DataLoss', Code.DataLoss],
    ])('does not retry on %s', async (_name, code) => {
        let callCount = 0
        const error: unknown = await withRetry(
            () => {
                callCount++
                throw new ConnectError('non-retryable', code)
            },
            'test-client',
            'test-method'
        ).catch((e: unknown) => e)
        expect(error).toBeInstanceOf(ConnectError)
        // Not tagged retriable: outer retry layers must not absorb these.
        expect(error).not.toHaveProperty('isRetriable')
        expect(callCount).toBe(1)
    })

    it('does not retry non-ConnectError errors', async () => {
        let callCount = 0
        const error: unknown = await withRetry(
            () => {
                callCount++
                throw new Error('plain error')
            },
            'test-client',
            'test-method'
        ).catch((e: unknown) => e)
        expect(error).toBeInstanceOf(Error)
        expect(error).not.toHaveProperty('isRetriable')
        expect(callCount).toBe(1)
    })

    it('throws after max retries exhausted, tagged retriable for outer retry layers', async () => {
        let callCount = 0
        await expect(
            withRetry(
                () => {
                    callCount++
                    throw new ConnectError('unavailable', Code.Unavailable)
                },
                'test-client',
                'test-method'
            )
        ).rejects.toMatchObject({ code: Code.Unavailable, isRetriable: true })
        // 1 initial + 2 retries = 3 total (default maxRetries=2)
        expect(callCount).toBe(3)
    })

    it.each([
        ['Unavailable', Code.Unavailable, 50],
        ['ResourceExhausted', Code.ResourceExhausted, 250],
    ])('waits the %s backoff before the first retry', async (_name, code, firstDelayMs) => {
        jest.useFakeTimers()
        const random = jest.spyOn(Math, 'random').mockReturnValue(0)
        try {
            let callCount = 0
            const result = withRetry(
                () => {
                    callCount++
                    if (callCount === 1) {
                        throw new ConnectError('transient', code)
                    }
                    return Promise.resolve('ok')
                },
                'test-client',
                'test-method'
            )
            await jest.advanceTimersByTimeAsync(firstDelayMs - 1)
            expect(callCount).toBe(1)
            await jest.advanceTimersByTimeAsync(1)
            await expect(result).resolves.toBe('ok')
            expect(callCount).toBe(2)
        } finally {
            random.mockRestore()
            jest.useRealTimers()
        }
    })

    it('respects custom maxRetries', async () => {
        let callCount = 0
        await expect(
            withRetry(
                () => {
                    callCount++
                    throw new ConnectError('unavailable', Code.Unavailable)
                },
                'test-client',
                'test-method',
                4
            )
        ).rejects.toThrow(ConnectError)
        // 1 initial + 4 retries = 5 total
        expect(callCount).toBe(5)
    })
})
