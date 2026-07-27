import { isWebAuthnCancellation } from './utils'

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
