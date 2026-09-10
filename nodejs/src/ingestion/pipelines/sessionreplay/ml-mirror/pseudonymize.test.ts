import { PSEUDONYM_SESSION, PSEUDONYM_TEAM, pseudonymize } from './pseudonymize'

describe('ml-mirror/pseudonymize', () => {
    const secret = 'super-secret'

    it('is deterministic: same input maps to the same value', () => {
        expect(pseudonymize(secret, PSEUDONYM_TEAM, '42')).toBe(pseudonymize(secret, PSEUDONYM_TEAM, '42'))
    })

    it('domain-separates namespaces so a team id and session id with the same value differ', () => {
        expect(pseudonymize(secret, PSEUDONYM_TEAM, '42')).not.toBe(pseudonymize(secret, PSEUDONYM_SESSION, '42'))
    })

    it('depends on the secret: a different secret produces a different value', () => {
        expect(pseudonymize(secret, PSEUDONYM_TEAM, '42')).not.toBe(pseudonymize('other-secret', PSEUDONYM_TEAM, '42'))
    })

    it('does not contain the raw value', () => {
        const out = pseudonymize(secret, PSEUDONYM_TEAM, 'team-12345')
        expect(out).not.toContain('team-12345')
        expect(out).toMatch(/^[0-9a-f]{32}$/)
    })
})
