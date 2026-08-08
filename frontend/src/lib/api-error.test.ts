import { ApiError, describeApiError, isNetworkError } from './api-error'

describe('describeApiError', () => {
    it('names the offending field for a DRF field-level validation error', async () => {
        const body = {
            type: 'validation_error',
            detail: 'Ensure this field has no more than 400 characters.',
            attr: 'name',
        }
        const error = await ApiError.fromResponse(new Response(JSON.stringify(body), { status: 400 }))

        // Regression: the bare `detail` alone gives no hint which field failed.
        expect(describeApiError(error, 'Could not save insight')).toEqual(
            'Name: Ensure this field has no more than 400 characters.'
        )
    })

    it('returns the detail alone when the error names no field', async () => {
        const error = await ApiError.fromResponse(
            new Response(JSON.stringify({ detail: 'Something went wrong.' }), { status: 400 })
        )

        expect(describeApiError(error, 'fallback')).toEqual('Something went wrong.')
    })

    it('falls back when the error carries no detail', () => {
        expect(describeApiError(new ApiError(undefined, undefined), 'Could not save insight')).toEqual(
            'Could not save insight'
        )
    })
})

describe('isNetworkError', () => {
    it('is true for an ApiError with no status (request never reached the server)', () => {
        expect(isNetworkError(new ApiError('Failed to fetch', undefined))).toBe(true)
    })

    it('is false for an ApiError carrying an HTTP status', () => {
        expect(isNetworkError(new ApiError('Bad request', 400))).toBe(false)
    })

    it('is false for a plain Error, so a thrown bug is not mislabeled as offline', () => {
        expect(isNetworkError(new Error('boom'))).toBe(false)
    })
})

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
