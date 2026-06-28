import { NextFunction, Request, Response } from 'ultimate-express'

import { JWT, PosthogJwtAudience } from '~/cdp/utils/jwt-utils'

import { RecordingApiAuthOptions, assertRecordingApiAuthConfigured, createRecordingApiAuthMiddleware } from './auth'

describe('createRecordingApiAuthMiddleware', () => {
    const JWT_SECRET = 'recording-api-secret-key'
    const LEGACY_SECRET = 'legacy-internal-secret'

    const mintToken = (
        claims: { team_id: number; op: string },
        secret = JWT_SECRET,
        expiresIn: string | number = '5m'
    ) => new JWT(secret).sign(claims, PosthogJwtAudience.RECORDING_API, { expiresIn })

    const mockResponse = () => {
        const res = {} as Response
        res.status = jest.fn().mockReturnValue(res)
        res.json = jest.fn().mockReturnValue(res)
        return res
    }

    const mockRequest = (teamIdParam: string, headers: Record<string, string> = {}) =>
        ({
            headers,
            params: { team_id: teamIdParam },
            path: `/api/projects/${teamIdParam}/recordings/abc/block`,
            method: 'GET',
        }) as unknown as Request

    const run = (opts: Partial<RecordingApiAuthOptions>, req: Request) => {
        const middleware = createRecordingApiAuthMiddleware({
            jwtSecret: JWT_SECRET,
            legacySecret: LEGACY_SECRET,
            allowLegacySecret: false,
            op: 'read',
            ...opts,
        })
        const res = mockResponse()
        const next = jest.fn() as NextFunction
        middleware(req, res, next)
        return { res, next }
    }

    const bearer = (token: string) => ({ authorization: `Bearer ${token}` })

    it('skips authorization when no jwt secret configured (local dev)', () => {
        const { res, next } = run({ jwtSecret: '' }, mockRequest('123'))
        expect(next).toHaveBeenCalled()
        expect(res.status).not.toHaveBeenCalled()
    })

    it('allows a valid read token whose team matches the path', () => {
        const { res, next } = run({ op: 'read' }, mockRequest('123', bearer(mintToken({ team_id: 123, op: 'read' }))))
        expect(next).toHaveBeenCalled()
        expect(res.status).not.toHaveBeenCalled()
    })

    it('allows a valid delete token on the delete route', () => {
        const { res, next } = run(
            { op: 'delete' },
            mockRequest('123', bearer(mintToken({ team_id: 123, op: 'delete' })))
        )
        expect(next).toHaveBeenCalled()
        expect(res.status).not.toHaveBeenCalled()
    })

    it('rejects a token scoped to a different team (IDOR guard)', () => {
        const { res, next } = run({ op: 'read' }, mockRequest('123', bearer(mintToken({ team_id: 456, op: 'read' }))))
        expect(next).not.toHaveBeenCalled()
        expect(res.status).toHaveBeenCalledWith(403)
    })

    it('rejects a read token on the delete route', () => {
        const { res, next } = run({ op: 'delete' }, mockRequest('123', bearer(mintToken({ team_id: 123, op: 'read' }))))
        expect(next).not.toHaveBeenCalled()
        expect(res.status).toHaveBeenCalledWith(403)
    })

    it('rejects a delete token on a read route', () => {
        const { res, next } = run({ op: 'read' }, mockRequest('123', bearer(mintToken({ team_id: 123, op: 'delete' }))))
        expect(next).not.toHaveBeenCalled()
        expect(res.status).toHaveBeenCalledWith(403)
    })

    it.each([
        ['no token', {}],
        ['garbage token', bearer('not-a-jwt')],
        ['token signed with an unknown key', bearer(mintToken({ team_id: 123, op: 'read' }, 'attacker-key'))],
        ['expired token', bearer(mintToken({ team_id: 123, op: 'read' }, JWT_SECRET, -60))],
    ])('rejects request with %s (401)', (_, headers) => {
        const { res, next } = run({ op: 'read' }, mockRequest('123', headers))
        expect(next).not.toHaveBeenCalled()
        expect(res.status).toHaveBeenCalledWith(401)
    })

    it('rejects a token for the wrong audience', () => {
        const wrongAud = new JWT(JWT_SECRET).sign(
            { team_id: 123, op: 'read' },
            PosthogJwtAudience.SUBSCRIPTION_PREFERENCES,
            { expiresIn: '5m' }
        )
        const { res, next } = run({ op: 'read' }, mockRequest('123', bearer(wrongAud)))
        expect(next).not.toHaveBeenCalled()
        expect(res.status).toHaveBeenCalledWith(401)
    })

    describe('legacy secret fallback (transition)', () => {
        it('accepts a valid X-Internal-Api-Secret when allowLegacySecret is true', () => {
            const { res, next } = run(
                { allowLegacySecret: true },
                mockRequest('123', { 'x-internal-api-secret': LEGACY_SECRET })
            )
            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })

        it('rejects the same legacy secret once allowLegacySecret is false', () => {
            const { res, next } = run(
                { allowLegacySecret: false },
                mockRequest('123', { 'x-internal-api-secret': LEGACY_SECRET })
            )
            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
        })

        it('still accepts a valid JWT when legacy is disabled', () => {
            const { res, next } = run(
                { allowLegacySecret: false },
                mockRequest('123', bearer(mintToken({ team_id: 123, op: 'read' })))
            )
            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })

        it('rejects an invalid legacy secret', () => {
            const { res, next } = run(
                { allowLegacySecret: true },
                mockRequest('123', { 'x-internal-api-secret': 'wrong' })
            )
            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
        })
    })

    describe('key rotation (new_key,old_key)', () => {
        it('verifies a token minted under the new (signing) key while both keys are configured', () => {
            const newToken = mintToken({ team_id: 123, op: 'read' }, 'new-key')
            const { res, next } = run(
                { jwtSecret: 'new-key,old-key', op: 'read' },
                mockRequest('123', bearer(newToken))
            )
            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })

        it('verifies a token minted under the old key while both keys are configured', () => {
            const oldToken = mintToken({ team_id: 123, op: 'read' }, 'old-key')
            const { res, next } = run(
                { jwtSecret: 'new-key,old-key', op: 'read' },
                mockRequest('123', bearer(oldToken))
            )
            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })

        it('rejects a token signed by a key outside the configured set', () => {
            const rogue = mintToken({ team_id: 123, op: 'read' }, 'rogue-key')
            const { res, next } = run({ jwtSecret: 'new-key,old-key', op: 'read' }, mockRequest('123', bearer(rogue)))
            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
        })

        it('rejects a token minted under a retired key once it is dropped', () => {
            const oldToken = mintToken({ team_id: 123, op: 'read' }, 'old-key')
            const { res, next } = run({ jwtSecret: 'new-key', op: 'read' }, mockRequest('123', bearer(oldToken)))
            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
        })
    })

    describe('progressive rollout (legacy secret before JWT is enabled)', () => {
        it('requires the legacy secret when no JWT secret is configured', () => {
            const req = mockRequest('123', { 'x-internal-api-secret': LEGACY_SECRET })
            const { res, next } = run({ jwtSecret: '', allowLegacySecret: true }, req)
            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })

        it('rejects a request with no legacy secret when JWT is not yet configured', () => {
            const { res, next } = run({ jwtSecret: '', allowLegacySecret: true }, mockRequest('123'))
            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
        })

        it('skips entirely only when neither JWT nor legacy secret is configured (local dev)', () => {
            const { res, next } = run({ jwtSecret: '', legacySecret: '', allowLegacySecret: true }, mockRequest('123'))
            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })

        it('treats a malformed-but-truthy secret (comma only) as JWT-disabled without crashing', () => {
            // ',' yields zero keys after split/filter; the middleware must not construct a JWT verifier
            // (which throws on empty keys) and should fall back to the legacy secret instead.
            const req = mockRequest('123', { 'x-internal-api-secret': LEGACY_SECRET })
            expect(() => run({ jwtSecret: ',', allowLegacySecret: true }, req)).not.toThrow()
            const { res, next } = run({ jwtSecret: ',', allowLegacySecret: true }, req)
            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })
    })

    describe('cross-language contract (must match the Python minter)', () => {
        it('audience enum value is the shared literal', () => {
            // Pinned to the same string as posthog/jwt.py PosthogJwtAudience.RECORDING_API.
            expect(PosthogJwtAudience.RECORDING_API).toBe('posthog:recording_api')
        })

        it('accepts a token built with the raw audience literal and the claim names Python emits', () => {
            // Sign with the literal audience (not the enum) and the exact claim names the Python helper
            // produces, so a drift in the Node enum value or the claims the middleware reads breaks this.
            const token = new JWT(JWT_SECRET).sign(
                { team_id: 123, op: 'read' },
                'posthog:recording_api' as PosthogJwtAudience,
                {
                    expiresIn: '5m',
                }
            )
            const { res, next } = run({ op: 'read' }, mockRequest('123', bearer(token)))
            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })
    })
})

describe('assertRecordingApiAuthConfigured', () => {
    const base = { isProd: true, jwtSecret: '', allowLegacySecret: true, legacySecret: '' }

    it('throws in production when neither a JWT nor a legacy secret is configured', () => {
        expect(() => assertRecordingApiAuthConfigured(base)).toThrow(/no auth configured in production/)
    })

    it('throws in production when the only key is a malformed comma-only value', () => {
        expect(() => assertRecordingApiAuthConfigured({ ...base, jwtSecret: ',' })).toThrow()
    })

    it('throws in production when legacy is disabled and there is no JWT secret', () => {
        expect(() =>
            assertRecordingApiAuthConfigured({ ...base, allowLegacySecret: false, legacySecret: 'legacy' })
        ).toThrow()
    })

    it('passes in production with a JWT secret', () => {
        expect(() => assertRecordingApiAuthConfigured({ ...base, jwtSecret: 'k' })).not.toThrow()
    })

    it('passes in production with only the legacy secret (pre-rollout)', () => {
        expect(() => assertRecordingApiAuthConfigured({ ...base, legacySecret: 'legacy' })).not.toThrow()
    })

    it('passes outside production even with nothing configured (local dev)', () => {
        expect(() => assertRecordingApiAuthConfigured({ ...base, isProd: false })).not.toThrow()
    })
})
