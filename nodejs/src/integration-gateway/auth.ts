import { JWT, PosthogJwtAudience } from '~/cdp/utils/jwt-utils'

export interface AuthedCaller {
    teamId: number
    caller: string
}

/**
 * Verifies the scoped JWT a caller presents and yields the authenticated caller.
 *
 * Fails closed: no configured secret, no `Authorization: Bearer` header, wrong audience, expired,
 * or bad signature => null (the handler returns 401). Tries every configured secret (primary then
 * fallbacks) via the shared `JWT` helper, mirroring Django's rotation loop.
 */
export class GatewayAuth {
    private jwt: JWT | null

    constructor(commaSeparatedSecrets: string) {
        const secrets = commaSeparatedSecrets
            .split(',')
            .map((s) => s.trim())
            .filter((s) => s.length > 0)
        // Fail closed when unconfigured — construct no verifier, so every request is rejected.
        this.jwt = secrets.length > 0 ? new JWT(secrets.join(',')) : null
    }

    verify(authorizationHeader: string | undefined): AuthedCaller | null {
        if (!this.jwt || !authorizationHeader || !authorizationHeader.startsWith('Bearer ')) {
            return null
        }
        const token = authorizationHeader.slice('Bearer '.length).trim()
        if (!token) {
            return null
        }
        const payload = this.jwt.verify(token, PosthogJwtAudience.INTEGRATION_GATEWAY, {
            ignoreVerificationErrors: true,
        })
        if (!payload || typeof payload === 'string') {
            return null
        }
        const teamId = (payload as Record<string, unknown>).team_id
        const caller = (payload as Record<string, unknown>).caller
        if (typeof teamId !== 'number' || typeof caller !== 'string') {
            return null
        }
        return { teamId, caller }
    }
}
