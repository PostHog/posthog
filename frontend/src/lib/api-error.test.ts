import { ApiError, isTransientServerError } from './api-error'

describe('api-error', () => {
    describe('ApiError.fromResponse', () => {
        it.each([
            ['error', { error: 'error message' }, 'error message'],
            ['detail', { detail: 'detail message' }, 'detail message'],
            ['message', { message: 'message value' }, 'message value'],
        ])('uses the %s field as the error message', async (_, body, expected) => {
            const response = new Response(JSON.stringify(body), { status: 400 })

            const error = await ApiError.fromResponse(response, 'fallback')

            expect(error).toMatchObject({ message: expected, status: 400, data: body })
        })

        it('uses the fallback for a response without a recognized message', async () => {
            const response = new Response('Bad gateway', { status: 502 })

            const error = await ApiError.fromResponse(response, 'Request failed')

            expect(error).toMatchObject({ message: 'Request failed', status: 502, data: null })
        })

        it('preserves response metadata and prioritizes error messages consistently', async () => {
            const body = {
                error: 'primary message',
                detail: 'DRF detail',
                message: 'secondary message',
                code: 'permission_denied',
            }

            const error = await ApiError.fromResponse(new Response(JSON.stringify(body), { status: 403 }))

            expect(error).toMatchObject({
                message: 'primary message',
                detail: 'DRF detail',
                code: 'permission_denied',
                status: 403,
                data: body,
            })
        })

        it('uses the default ApiError message for an empty response without a fallback', async () => {
            const error = await ApiError.fromResponse(new Response(null, { status: 404 }))

            expect(error).toMatchObject({ message: 'API request failed with status: 404', status: 404, data: null })
        })

        it('propagates an aborted response body read', async () => {
            const abortError = new DOMException('Aborted', 'AbortError')
            const response = {
                json: jest.fn().mockRejectedValue(abortError),
            } as unknown as Response

            await expect(ApiError.fromResponse(response)).rejects.toBe(abortError)
        })
    })

    describe('isTransientServerError', () => {
        it.each([
            // The empty-bodied gateway timeout that the insight-save flows must swallow rather than rethrow.
            ['a 503 with no body (detail null)', new ApiError(undefined, 503), true],
            ['a 502 bad gateway', new ApiError(undefined, 502), true],
            ['a 504 gateway timeout', new ApiError(undefined, 504), true],
            ['a 500 application error', new ApiError('boom', 500), false],
            ['a 599', new ApiError(undefined, 599), false],
            ['a 400 validation error', new ApiError('bad', 400), false],
            ['a 403', new ApiError('nope', 403), false],
            ['a 429 rate limit', new ApiError('slow down', 429), false],
            ['an ApiError with no status', new ApiError('mystery'), false],
        ])('classifies %s', (_, error, expected) => {
            expect(isTransientServerError(error)).toBe(expected)
        })

        it.each([
            ['a plain Error', new Error('network down')],
            ['null', null],
            ['a bare object shaped like an error', { status: 503 }],
        ])('does not classify %s as transient', (_, error) => {
            expect(isTransientServerError(error)).toBe(false)
        })
    })
})
