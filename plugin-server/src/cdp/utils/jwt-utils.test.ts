import jwtLib from 'jsonwebtoken'

import { JWT, PosthogJwtAudience } from './jwt-utils'

describe('JWT', () => {
    jest.setTimeout(1000)
    let jwtUtil: JWT

    beforeEach(() => {
        jwtUtil = new JWT('testsecret1,testsecret2')
    })

    describe('sign and verify', () => {
        it('should sign and verify a payload', () => {
            const payload = { foo: 'bar', n: 42 }
            const token = jwtUtil.sign(payload, PosthogJwtAudience.SUBSCRIPTION_PREFERENCES)
            expect(typeof token).toBe('string')
            const verified = jwtUtil.verify(token, PosthogJwtAudience.SUBSCRIPTION_PREFERENCES)
            // jwt.verify returns the payload with extra fields (iat, etc)
            expect((verified as any).foo).toBe('bar')
            expect((verified as any).n).toBe(42)
        })

        it('should throw if token is invalid', () => {
            expect(() => jwtUtil.verify('not.a.valid.token', PosthogJwtAudience.SUBSCRIPTION_PREFERENCES)).toThrow(
                'jwt malformed'
            )
        })

        it('should not throw if ignoreVerificationErrors is true', () => {
            expect(() =>
                jwtUtil.verify('not.a.valid.token', PosthogJwtAudience.SUBSCRIPTION_PREFERENCES, {
                    ignoreVerificationErrors: true,
                })
            ).not.toThrow()
            expect(
                jwtUtil.verify('not.a.valid.token', PosthogJwtAudience.SUBSCRIPTION_PREFERENCES, {
                    ignoreVerificationErrors: true,
                })
            ).toBeUndefined()
        })
    })

    it('should throw if ENCRYPTION_SALT_KEYS is empty', () => {
        const emptyEncryptionSaltKeys = ''
        expect(() => new JWT(emptyEncryptionSaltKeys)).toThrow('Encryption keys are not set')
    })

    it('should try all secrets for verification', () => {
        const payload = { foo: 'bar' }
        const token = jwtLib.sign(payload, 'testsecret2', { audience: PosthogJwtAudience.SUBSCRIPTION_PREFERENCES })
        expect((jwtUtil.verify(token, PosthogJwtAudience.SUBSCRIPTION_PREFERENCES) as any).foo).toBe('bar')
    })
})
