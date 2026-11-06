import jwt from 'jsonwebtoken'

import { PosthogJwtAudience } from './jwt-utils'
import { ScopedServiceJwt } from './scoped-service-jwt'

const AUDIENCE = PosthogJwtAudience.WORKFLOWS_RESCHEDULE_PARKED
const TEST_KEY = 'test-key'
const NEW_KEY = 'new-key'
const OLD_KEY = 'old-key'
const CONTRACT_KEY = 'contract-key'

// Raw jsonwebtoken signer for forging tokens outside ScopedServiceJwt. The key flows through a
// parameter (mirroring auth.test.ts's mintToken) so semgrep's hardcoded-credential constant
// propagation doesn't flag the test fixture keys as real secrets.
const signRaw = (claims: object, key: string, options: jwt.SignOptions): string => jwt.sign(claims, key, options)

describe('ScopedServiceJwt', () => {
    describe('provisioning', () => {
        it.each([
            ['empty string', ''],
            ['commas only', ',,'],
            ['whitespace only', ' , '],
        ])('is disabled and refuses to mint or verify when keys are %s', (_name, keys) => {
            const scoped = new ScopedServiceJwt(AUDIENCE, keys)
            expect(scoped.enabled).toBe(false)
            expect(() => scoped.mint({ team_id: 1 })).toThrow(/no signing key configured/)
            expect(() => scoped.verify('any-token')).toThrow(/no signing key configured/)
        })
    })

    describe('mint and verify', () => {
        it('round-trips claims and enforces the audience', () => {
            const scoped = new ScopedServiceJwt(AUDIENCE, TEST_KEY)

            const claims = scoped.verify(scoped.mint({ team_id: 42, ticket_id: 'abc' }))

            expect(claims.team_id).toBe(42)
            expect(claims.ticket_id).toBe('abc')
            expect(claims.aud).toBe(AUDIENCE)

            const otherAudience = new ScopedServiceJwt(PosthogJwtAudience.SUBSCRIPTION_PREFERENCES, TEST_KEY)
            expect(() => otherAudience.verify(scoped.mint({ team_id: 42 }))).toThrow(/audience/)
        })

        it('signs with the newest key while still verifying tokens from the old key', () => {
            const oldOnly = new ScopedServiceJwt(AUDIENCE, OLD_KEY)
            const newOnly = new ScopedServiceJwt(AUDIENCE, NEW_KEY)
            const rotated = new ScopedServiceJwt(AUDIENCE, `${NEW_KEY},${OLD_KEY}`)

            expect(rotated.verify(oldOnly.mint({ team_id: 1 })).team_id).toBe(1)
            // A token minted post-rotation must be signed with the new key, or dropping the
            // old key from the list would invalidate fresh tokens.
            expect(newOnly.verify(rotated.mint({ team_id: 1 })).team_id).toBe(1)
        })

        it('trims whitespace around keys to match the Python side', () => {
            const scoped = new ScopedServiceJwt(AUDIENCE, ` ${NEW_KEY} , ${OLD_KEY} `)
            expect(new ScopedServiceJwt(AUDIENCE, NEW_KEY).verify(scoped.mint({ team_id: 1 })).team_id).toBe(1)
        })

        it('rejects a token signed with a different HMAC algorithm even under the right key', () => {
            const scoped = new ScopedServiceJwt(AUDIENCE, TEST_KEY)
            const forged = signRaw({ team_id: 1 }, TEST_KEY, {
                algorithm: 'HS512',
                audience: AUDIENCE,
                expiresIn: '5m',
            })
            expect(() => scoped.verify(forged)).toThrow(/algorithm/)
        })

        it('applies the shared 5 minute default ttl', () => {
            const scoped = new ScopedServiceJwt(AUDIENCE, TEST_KEY)
            const claims = scoped.verify(scoped.mint({ team_id: 1 }))
            expect(claims.exp! - claims.iat!).toBe(5 * 60)
        })
    })

    describe('cross-language contract (must match posthog/scoped_service_jwt.py)', () => {
        it('accepts a token built the way the Python minter builds them', () => {
            // Signed with the raw audience literal and the claim names the Python side emits
            // (HS256, flat claims, team_id), so drift in either side's contract breaks this.
            const token = signRaw({ team_id: 123 }, CONTRACT_KEY, {
                algorithm: 'HS256',
                audience: 'posthog:workflows:reschedule_parked',
                expiresIn: '5m',
            })

            const claims = new ScopedServiceJwt(AUDIENCE, CONTRACT_KEY).verify(token)
            expect(claims.team_id).toBe(123)
        })
    })
})
