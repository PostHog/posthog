import { INTERNAL_JWT_AUDIENCE, InternalJwtVerifyError, mintInternalJwt, verifyInternalJwt } from './internal-jwt'

describe('internal-jwt', () => {
    const SIGNING_KEY = 'shared-key-shared-key-shared-key'

    it('round-trips a token with matching audience + key', async () => {
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey: SIGNING_KEY,
            claims: { sub: 'django' },
        })
        const payload = await verifyInternalJwt({
            token,
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey: SIGNING_KEY,
        })
        expect(payload.sub).toBe('django')
        expect(payload.aud).toBe('agent-janitor.rpc')
    })

    it('rejects a token minted for a different audience (cross-service replay)', async () => {
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.INGRESS_PREVIEW,
            signingKey: SIGNING_KEY,
        })
        await expect(
            verifyInternalJwt({
                token,
                audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
                signingKey: SIGNING_KEY,
            })
        ).rejects.toBeInstanceOf(InternalJwtVerifyError)
    })

    it('rejects a token signed with a different key', async () => {
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey: 'attacker-key',
        })
        await expect(
            verifyInternalJwt({
                token,
                audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
                signingKey: SIGNING_KEY,
            })
        ).rejects.toBeInstanceOf(InternalJwtVerifyError)
    })

    it('rejects an expired token', async () => {
        const token = await mintInternalJwt({
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey: SIGNING_KEY,
            ttlSec: -10,
        })
        await expect(
            verifyInternalJwt({
                token,
                audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
                signingKey: SIGNING_KEY,
            })
        ).rejects.toBeInstanceOf(InternalJwtVerifyError)
    })
})
