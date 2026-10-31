import { NextFunction, Request, Response } from 'ultimate-express'

import { JWT, PosthogJwtAudience } from '~/cdp/utils/jwt-utils'

import { RecordingApiAuthOptions, assertRecordingApiAuthConfigured, createRecordingApiAuthMiddleware } from './auth'

describe('createRecordingApiAuthMiddleware', () => {
    const JWT_SECRET = 'recording-api-secret-key'

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

    // Mirrors what the middleware actually receives: it is mounted on the '/api/projects' prefix, so
    // ultimate-express strips the mount from req.path and exposes no req.params, leaving originalUrl
    // as the only source of team_id.
    const mockRequest = (teamIdSegment: string, headers: Record<string, string> = {}) =>
        ({
            headers,
            originalUrl: `/api/projects/${teamIdSegment}/recordings/abc/block`,
            path: `/${teamIdSegment}/recordings/abc/block`,
            method: 'GET',
        }) as unknown as Request

    const run = (opts: Partial<RecordingApiAuthOptions>, req: Request) => {
        const middleware = createRecordingApiAuthMiddleware({
            jwtSecret: JWT_SECRET,
            op: 'read',
            ...opts,
        })
        const res = mockResponse()
        const next = jest.fn() as NextFunction
        middleware(req, res, next)
        return { res, next }
    }

    const bearer = (token: string) => ({ authorization: `Bearer ${token}` })

    // ',' is truthy but yields zero keys, so it must disable JWT rather than build a verifier that throws.
    it.each([[''], [',']])('skips authorization when jwt secret %p has no keys (local dev)', (jwtSecret) => {
        const { res, next } = run({ jwtSecret }, mockRequest('123'))
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

    // A non-canonical segment must never authorize, because the route handler is free to parse it
    // differently than this middleware does. Each case is paired with the team_id it would coerce to,
    // so a lenient Number() parse here would wrongly match the token and let the request through.
    it.each([
        ['0123', 123],
        ['1e3', 1000],
        ['0x10', 16],
        ['+123', 123],
        ['123.0', 123],
    ])('rejects non-canonical team segment %p even though it coerces to %p', (segment, coercedTeamId) => {
        const { res, next } = run(
            { op: 'read' },
            mockRequest(segment, bearer(mintToken({ team_id: coercedTeamId as number, op: 'read' })))
        )
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
    const base = { isProd: true, jwtSecret: '' }

    it('throws in production when no JWT secret is configured', () => {
        expect(() => assertRecordingApiAuthConfigured(base)).toThrow(/no auth configured in production/)
    })

    it('throws in production when the only key is a malformed comma-only value', () => {
        expect(() => assertRecordingApiAuthConfigured({ ...base, jwtSecret: ',' })).toThrow()
    })

    it('passes in production with a JWT secret', () => {
        expect(() => assertRecordingApiAuthConfigured({ ...base, jwtSecret: 'k' })).not.toThrow()
    })

    it('passes outside production even with nothing configured (local dev)', () => {
        expect(() => assertRecordingApiAuthConfigured({ ...base, isProd: false })).not.toThrow()
    })
})
