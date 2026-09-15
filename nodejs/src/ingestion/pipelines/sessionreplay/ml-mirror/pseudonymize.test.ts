import { PSEUDONYM_IMAGE_CONTENT_KEY, PSEUDONYM_IMAGE_URL_KEY, pseudonymize } from './pseudonymize'

describe('ml-mirror/pseudonymize', () => {
    const secret = 'super-secret'

    it('is deterministic: same input maps to the same value', () => {
        expect(pseudonymize(secret, PSEUDONYM_IMAGE_CONTENT_KEY, '42')).toBe(
            pseudonymize(secret, PSEUDONYM_IMAGE_CONTENT_KEY, '42')
        )
    })

    it('domain-separates image content and URL keys', () => {
        expect(pseudonymize(secret, PSEUDONYM_IMAGE_CONTENT_KEY, '42')).not.toBe(
            pseudonymize(secret, PSEUDONYM_IMAGE_URL_KEY, '42')
        )
    })

    it('depends on the secret: a different secret produces a different value', () => {
        expect(pseudonymize(secret, PSEUDONYM_IMAGE_CONTENT_KEY, '42')).not.toBe(
            pseudonymize('other-secret', PSEUDONYM_IMAGE_CONTENT_KEY, '42')
        )
    })

    it('does not contain the raw value', () => {
        const out = pseudonymize(secret, PSEUDONYM_IMAGE_CONTENT_KEY, 'team-12345')
        expect(out).not.toContain('team-12345')
        expect(out).toMatch(/^[0-9a-f]{32}$/)
    })
})
