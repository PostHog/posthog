import { ApiError, isExpectedAuthorizationError } from './api-error'

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

    describe('isExpectedAuthorizationError', () => {
        it.each([
            ['a 2FA setup block', 403, 'two_factor_setup_required', true],
            ['a 2FA verification block', 403, 'two_factor_verification_required', true],
            ['a re-authentication block', 403, 'sensitive_action_required_reauth', true],
            ['a verified-domain block', 403, 'verified_domain_required', true],
            ['an access-denied response', 403, 'permission_denied', true],
            // A 400 carrying an authorization code is form validation, e.g. inviting an
            // outside-domain email — a real failure the user needs reported.
            ['verified-domain form validation', 400, 'verified_domain_required', false],
            // Read-only mode has its own `before_send` filter and must not be swallowed here.
            ['a read-only block', 403, 'read_only_blocked', false],
            ['a 403 with no code', 403, null, false],
        ])('returns the right verdict for %s', (_, status, code, expected) => {
            expect(isExpectedAuthorizationError({ status, code })).toBe(expected)
        })
    })
})
