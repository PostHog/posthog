import { ApiError } from './api-error'

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
