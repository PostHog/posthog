import { ApiError } from 'lib/api-error'

describe('ApiError', () => {
    it('keeps string fields from the response body', () => {
        const error = new ApiError('failed', 400, undefined, {
            detail: 'Enter a valid email address.',
            code: 'invalid',
            attr: 'email',
            statusText: 'Bad Request',
            link: 'https://example.com',
        })

        expect(error.detail).toBe('Enter a valid email address.')
        expect(error.code).toBe('invalid')
        expect(error.attr).toBe('email')
        expect(error.statusText).toBe('Bad Request')
        expect(error.link).toBe('https://example.com')
    })

    it.each([
        ['nested field errors', { email: ['Enter a valid email address.'] }],
        ['a list', ['Enter a valid email address.']],
        ['a number', 42],
    ])('drops a non-string detail (%s) so it cannot reach a React child', (_name, detail) => {
        const error = new ApiError('failed', 400, undefined, { detail })

        expect(error.detail).toBeNull()
        expect(error.data.detail).toEqual(detail)
    })
})
