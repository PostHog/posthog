import { NextFunction, Request, Response } from 'ultimate-express'

import { JWT, PosthogJwtAudience, hasJwtKeys, makeOptionalJwt } from '~/cdp/utils/jwt-utils'
import { logger } from '~/common/utils/logger'

/**
 * Authorization for recording-api routes.
 *
 * Each route requires a team + operation scoped JWT (audience `posthog:recording_api`) minted by
 * an authorized service: the token's `team_id` must match the `:team_id` in the path and its `op`
 * must match the route (read, delete or write).
 */

export type RecordingApiOp = 'read' | 'delete' | 'write'

// jsonwebtoken tolerates up to this many seconds of clock skew between minter and verifier.
const CLOCK_TOLERANCE_SECONDS = 30

export interface RecordingApiAuthOptions {
    // Comma-separated keys (newest first) for zero-downtime rotation. Empty disables JWT auth (dev only).
    jwtSecret: string
    op: RecordingApiOp
}

function getHeader(req: Request, name: string): string | undefined {
    // Node lowercases all incoming header field names, so a single lowercased lookup is sufficient.
    const value = req.headers[name.toLowerCase()]
    return typeof value === 'string' ? value : undefined
}

function getBearerToken(req: Request): string | undefined {
    const header = getHeader(req, 'authorization')
    return header && /^Bearer /i.test(header) ? header.slice('Bearer '.length) : undefined
}

// The team_id from the request URL. This middleware is mounted on a path prefix, where
// ultimate-express does not surface req.params, so the segment is read from the URL directly;
// originalUrl preserves the full path across the mount. Only canonical digits are accepted, so a
// segment like '0123', '1e3' or '0x10' yields NaN and fails the team check instead of depending on
// the route handler coercing it to the same number this does. Leading zeros are rejected too, so
// there is exactly one URL spelling of any given team.
function pathTeamId(req: Request): number {
    const match = /\/api\/projects\/([^/?]+)/.exec(req.originalUrl ?? req.path ?? '')
    return match && /^(0|[1-9]\d*)$/.test(match[1]) ? parseInt(match[1], 10) : NaN
}

/**
 * Fail closed in production: recording routes must have a JWT secret, because without one the
 * middleware below lets every request through. Uses the same key parsing as the verifier so a
 * malformed-but-truthy value (e.g. ',') counts as "no JWT configured".
 */
export function assertRecordingApiAuthConfigured(opts: { isProd: boolean; jwtSecret: string }): void {
    if (opts.isProd && !hasJwtKeys(opts.jwtSecret || '')) {
        throw new Error('recording-api has no auth configured in production: set RECORDING_API_JWT_SECRET')
    }
}

export function createRecordingApiAuthMiddleware(options: RecordingApiAuthOptions) {
    const { jwtSecret, op } = options
    // Build the verifier once. Comma-separated keys give zero-downtime rotation (verify against all);
    // a malformed/empty value yields no keys and disables JWT (null) rather than throwing. `|| ''`
    // guards against a partial runtime config where the field is absent.
    const jwt = makeOptionalJwt(jwtSecret || '')

    return (req: Request, res: Response, next: NextFunction): void => {
        // No JWT secret configured (local dev): allow. Production refuses to boot in this state, see
        // assertRecordingApiAuthConfigured.
        if (!jwt) {
            next()
            return
        }

        const bearer = getBearerToken(req)
        if (bearer) {
            let payload: ReturnType<JWT['verify']>
            try {
                payload = jwt.verify(bearer, PosthogJwtAudience.RECORDING_API, {
                    // Pin HS256 to match the Python minter (encode/decode pin JWT_ALGORITHM);
                    // don't accept other HMAC variants the library would otherwise allow.
                    algorithms: ['HS256'],
                    clockTolerance: CLOCK_TOLERANCE_SECONDS,
                })
            } catch (err) {
                // Log the failure class (e.g. TokenExpiredError, JsonWebTokenError) — never the token —
                // so rotation 401s are diagnosable.
                logger.warn('Recording API JWT verification failed', {
                    reason: err instanceof Error ? err.name : 'unknown',
                    path: req.path,
                })
                payload = undefined
            }
            if (payload && typeof payload === 'object') {
                const claims = payload as { team_id?: unknown; op?: unknown }
                const tokenTeamId = Number(claims.team_id)
                const requestTeamId = pathTeamId(req)
                if (!Number.isInteger(tokenTeamId) || tokenTeamId !== requestTeamId) {
                    logger.warn('Recording API token team mismatch', { path: req.path })
                    res.status(403).json({ error: 'Forbidden: token not scoped to this team' })
                    return
                }
                if (claims.op !== op) {
                    logger.warn('Recording API token operation mismatch', { path: req.path, expected: op })
                    res.status(403).json({ error: 'Forbidden: token not valid for this operation' })
                    return
                }
                next()
                return
            }
        }

        res.status(401).json({ error: 'Unauthorized' })
    }
}
