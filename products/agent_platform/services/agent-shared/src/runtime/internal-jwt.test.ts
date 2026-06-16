import {
    InMemoryJtiReplayCache,
    INTERNAL_JWT_AUDIENCE,
    InternalJwtVerifyError,
    mintInternalJwt,
    verifyInternalJwt,
} from './internal-jwt'

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

    it('mints a unique jti on every token', async () => {
        const a = await mintInternalJwt({ audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC, signingKey: SIGNING_KEY })
        const b = await mintInternalJwt({ audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC, signingKey: SIGNING_KEY })
        const pa = await verifyInternalJwt({
            token: a,
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey: SIGNING_KEY,
        })
        const pb = await verifyInternalJwt({
            token: b,
            audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
            signingKey: SIGNING_KEY,
        })
        expect(pa.jti).toBeTruthy()
        expect(pa.jti).not.toBe(pb.jti)
    })

    it('rejects a replayed token when a replay cache is supplied', async () => {
        const replayCache = new InMemoryJtiReplayCache()
        const token = await mintInternalJwt({ audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC, signingKey: SIGNING_KEY })
        const opts = { token, audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC, signingKey: SIGNING_KEY, replayCache }
        // First use succeeds...
        await expect(verifyInternalJwt(opts)).resolves.toMatchObject({ aud: 'agent-janitor.rpc' })
        // ...a replay of the same token is rejected.
        await expect(verifyInternalJwt(opts)).rejects.toBeInstanceOf(InternalJwtVerifyError)
    })

    it('does not reject distinct tokens sharing a replay cache', async () => {
        const replayCache = new InMemoryJtiReplayCache()
        const t1 = await mintInternalJwt({ audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC, signingKey: SIGNING_KEY })
        const t2 = await mintInternalJwt({ audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC, signingKey: SIGNING_KEY })
        await expect(
            verifyInternalJwt({
                token: t1,
                audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
                signingKey: SIGNING_KEY,
                replayCache,
            })
        ).resolves.toBeTruthy()
        await expect(
            verifyInternalJwt({
                token: t2,
                audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
                signingKey: SIGNING_KEY,
                replayCache,
            })
        ).resolves.toBeTruthy()
    })
})
