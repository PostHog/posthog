import jwt from 'jsonwebtoken'

import { GatewayAuth } from './auth'

const AUDIENCE = 'posthog:integration_gateway'
const SECRET = 'test-secret'

function mint(opts: { secret?: string; audience?: string; expiresIn?: number; claims?: object } = {}): string {
    // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
    return jwt.sign({ team_id: 42, caller: 'cdp', ...(opts.claims ?? {}) }, opts.secret ?? SECRET, {
        audience: opts.audience ?? AUDIENCE,
        expiresIn: opts.expiresIn ?? 300,
    })
}

describe('GatewayAuth', () => {
    it('verifies a valid team-scoped token and yields the caller', () => {
        expect(new GatewayAuth(SECRET).verify(`Bearer ${mint()}`)).toEqual({ teamId: 42, caller: 'cdp' })
    })

    it('accepts a token signed by a fallback secret (rotation)', () => {
        expect(new GatewayAuth('new-secret,old-secret').verify(`Bearer ${mint({ secret: 'old-secret' })}`)).toEqual({
            teamId: 42,
            caller: 'cdp',
        })
    })

    it.each([
        ['wrong audience', (): string => mint({ audience: 'posthog:something_else' })],
        ['wrong secret', (): string => mint({ secret: 'other-secret' })],
        ['expired', (): string => mint({ expiresIn: -10 })],
        // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
        ['missing team_id claim', (): string => jwt.sign({ caller: 'cdp' }, SECRET, { audience: AUDIENCE })],
    ])('rejects a token with %s', (_name, make) => {
        expect(new GatewayAuth(SECRET).verify(`Bearer ${make()}`)).toBeNull()
    })

    it.each([
        ['missing header', undefined],
        ['non-bearer header', 'token-without-bearer'],
        ['empty bearer', 'Bearer '],
        ['garbage token', 'Bearer not-a-jwt'],
    ])('rejects %s', (_name, header) => {
        expect(new GatewayAuth(SECRET).verify(header)).toBeNull()
    })

    it('fails closed when no secret is configured (rejects every token)', () => {
        expect(new GatewayAuth('').verify(`Bearer ${mint()}`)).toBeNull()
    })
})
