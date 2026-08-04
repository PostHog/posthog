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
})
