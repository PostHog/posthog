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
        await expect(
            withRetry(
                () => {
                    callCount++
                    throw new ConnectError('non-retryable', code)
                },
                'test-client',
                'test-method'
            )
        ).rejects.toThrow(ConnectError)
        expect(callCount).toBe(1)
    })

    it('does not retry non-ConnectError errors', async () => {
        let callCount = 0
        await expect(
            withRetry(
                () => {
                    callCount++
                    throw new Error('plain error')
                },
                'test-client',
                'test-method'
            )
        ).rejects.toThrow('plain error')
        expect(callCount).toBe(1)
    })

    it('throws after max retries exhausted', async () => {
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
        ).rejects.toThrow(ConnectError)
        // 1 initial + 2 retries = 3 total (default maxRetries=2)
        expect(callCount).toBe(3)
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
