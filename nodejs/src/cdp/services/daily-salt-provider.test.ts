import { randomBytes } from 'crypto'

import { deriveTeamDailySalt } from './daily-salt-provider'

describe('deriveTeamDailySalt', () => {
    const salt = Buffer.from('0123456789abcdef', 'utf-8') // 16 bytes
    const day = '2025-01-01'

    it('is deterministic for the same salt, team, and day', () => {
        expect(deriveTeamDailySalt(salt, 1, day)).toBe(deriveTeamDailySalt(salt, 1, day))
    })

    it('differs across teams', () => {
        expect(deriveTeamDailySalt(salt, 1, day)).not.toBe(deriveTeamDailySalt(salt, 2, day))
    })

    it('differs across days', () => {
        expect(deriveTeamDailySalt(salt, 1, '2025-01-01')).not.toBe(deriveTeamDailySalt(salt, 1, '2025-01-02'))
    })

    it('differs when the underlying daily salt rotates', () => {
        const otherSalt = randomBytes(16)
        expect(deriveTeamDailySalt(salt, 1, day)).not.toBe(deriveTeamDailySalt(otherSalt, 1, day))
    })

    it('does not leak the raw daily salt (structurally irreversible)', () => {
        const derived = deriveTeamDailySalt(salt, 1, day)
        // The raw salt, in any common encoding, must not appear in the derived value.
        expect(derived).not.toContain(salt.toString('base64'))
        expect(derived).not.toContain(salt.toString('utf-8'))
        expect(derived).not.toContain(salt.toString('hex'))
    })
})
