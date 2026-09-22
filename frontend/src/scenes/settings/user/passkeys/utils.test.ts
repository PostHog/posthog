import { getPasskeyErrorMessage, isWebAuthnCancellation } from './utils'

describe('passkey error utils', () => {
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

    describe('getPasskeyErrorMessage', () => {
        it.each([
            [
                'the platform error class the browser words for itself',
                new DOMException('The operation failed for an unknown transient reason', 'UnknownError'),
            ],
            ['a nested platform error class', { error: { name: 'NotReadableError' }, message: 'raw browser string' }],
        ])('replaces the raw browser text for %s', (_label, input) => {
            const message = getPasskeyErrorMessage(input)
            expect(message).toContain('Try again')
            expect(message).not.toContain('unknown transient reason')
            expect(message).not.toContain('raw browser string')
        })

        it('falls back to the given default when nothing describes the failure', () => {
            expect(getPasskeyErrorMessage({}, 'Could not add your passkey.')).toEqual('Could not add your passkey.')
        })
    })
})
