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
        ['Canceled', Code.Canceled],
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
                    throw new ConnectError('internal', Code.Internal)
                },
                'test-client',
                'test-method'
            )
        ).rejects.toMatchObject({ code: Code.Internal, isRetriable: true })
        // 1 initial + 2 retries = 3 total (default maxRetries=2)
        expect(callCount).toBe(3)
    })

    it('respects custom maxRetries', async () => {
        let callCount = 0
        await expect(
            withRetry(
                () => {
                    callCount++
                    throw new ConnectError('internal', Code.Internal)
                },
                'test-client',
                'test-method',
                4
            )
        ).rejects.toThrow(ConnectError)
        // 1 initial + 4 retries = 5 total
        expect(callCount).toBe(5)
    })

    // A rolling restart of the proxy in front of personhog returns Unavailable or
    // Unknown for several seconds; the wider transport budget rides it out so the
    // blip does not surface as an unhandled exception.
    it.each([
        ['Unavailable', Code.Unavailable],
        ['Unknown', Code.Unknown],
    ])('retries %s with the wider transport budget', async (_name, code) => {
        jest.useFakeTimers()
        try {
            let callCount = 0
            const settled = withRetry(
                () => {
                    callCount++
                    throw new ConnectError('transport blip', code)
                },
                'test-client',
                'test-method'
            ).catch((e: unknown) => e)
            await jest.runAllTimersAsync()
            const error = await settled
            expect(error).toMatchObject({ code, isRetriable: true })
            // 1 initial + 7 transport retries = 8 total (transportMaxRetries=7)
            expect(callCount).toBe(8)
        } finally {
            jest.useRealTimers()
        }
    })
})
