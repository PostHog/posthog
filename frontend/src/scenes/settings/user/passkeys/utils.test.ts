import { ApiError, NetworkError } from 'lib/api-error'

import { getPasskeyErrorMessage, isTransientPasskeyServerError, isWebAuthnCancellation } from './utils'

describe('isWebAuthnCancellation', () => {
    it.each([
        ['plain NotAllowedError', { name: 'NotAllowedError' }, true],
        ['plain AbortError', { name: 'AbortError' }, true],
        ['DOMException-like NotAllowedError', new DOMException('cancelled', 'NotAllowedError'), true],
        ['nested SimpleWebAuthn-style cancellation', { error: { name: 'NotAllowedError' } }, true],
        ['nested SimpleWebAuthn-style abort', { error: { name: 'AbortError' } }, true],
        ['unrelated error name', { name: 'InvalidStateError' }, false],
        ['nested unrelated error name', { error: { name: 'InvalidStateError' } }, false],
        ['plain Error', new Error('boom'), false],
        ['string', 'NotAllowedError', false],
        ['null', null, false],
        ['undefined', undefined, false],
    ])('returns the right answer for %s', (_label, input, expected) => {
        expect(isWebAuthnCancellation(input)).toBe(expected)
    })
})

describe('isTransientPasskeyServerError', () => {
    it.each([
        ['503 ApiError', new ApiError('boom', 503), true],
        ['500 ApiError', new ApiError('boom', 500), true],
        ['status-less ApiError (network failure)', new NetworkError('network'), true],
        ['400 ApiError', new ApiError('boom', 400), false],
        ['403 ApiError', new ApiError('boom', 403), false],
        ['plain object that looks like a 503', { status: 503 }, false],
        ['plain Error', new Error('boom'), false],
        ['string', 'boom', false],
        ['null', null, false],
    ])('returns the right answer for %s', (_label, input, expected) => {
        expect(isTransientPasskeyServerError(input)).toBe(expected)
    })
})

describe('getPasskeyErrorMessage', () => {
    it('never surfaces the raw fallback message when the server sent no detail', () => {
        const error = new ApiError('Non-OK response [POST /api/webauthn/login/begin/] (status 503)', 503)
        expect(getPasskeyErrorMessage(error)).toBe('Passkey authentication failed. Please try again.')
    })

    it('prefers a server-provided detail', () => {
        expect(getPasskeyErrorMessage({ detail: 'This passkey is not registered.' })).toBe(
            'This passkey is not registered.'
        )
    })

    // The webauthn endpoints return their messages as `{ error: ... }`, so ApiError keeps the text
    // on `data.error`/`data.message` with `detail` null. A detail-only lookup would drop it and
    // show the generic message, telling e.g. an SSO-only user to retry an action that cannot succeed.
    it.each([
        ['error field', { error: 'You can only login with SSO for this account.' }],
        ['message field', { message: 'An account with this email already exists.' }],
    ])('surfaces the server text from a webauthn `{ %s }` response body', (_label, body) => {
        const expected = Object.values(body)[0]
        const error = new ApiError(expected, 400, undefined, body)
        expect(getPasskeyErrorMessage(error)).toBe(expected)
    })
})
