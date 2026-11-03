import crypto from 'crypto'
import { NextFunction, Request, Response } from 'ultimate-express'

import { JWT, PosthogJwtAudience, hasJwtKeys, makeOptionalJwt } from '~/cdp/utils/jwt-utils'
import { INTERNAL_SERVICE_CALL_HEADER_NAME } from '~/common/api/middleware/internal-api-auth'
import { logger } from '~/common/utils/logger'

import { RecordingApiRole } from './types'

/**
 * Authorization for recording-api routes.
 *
 * Each route requires a team + operation scoped JWT (audience `posthog:recording_api`) minted by
 * an authorized service: the token's `team_id` must match the `:team_id` in the path and its `op`
 * must match the route (read, delete or write). During migration the legacy `X-Internal-Api-Secret` is
 * accepted as a fallback while `allowLegacySecret` is true; the final cutover flips that flag off.
 */

export type RecordingApiOp = 'read' | 'delete' | 'write'

// jsonwebtoken tolerates up to this many seconds of clock skew between minter and verifier.
const CLOCK_TOLERANCE_SECONDS = 30

export interface RecordingApiAuthOptions {
    // Comma-separated keys (newest first) for zero-downtime rotation. Empty disables JWT auth (dev only).
    jwtSecret: string
    legacySecret: string
    allowLegacySecret: boolean
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

// Pinned to HS256 to match the Python minter, and logged by failure class only, never the token.
function verifyBearer(
    jwt: JWT,
    token: string,
    audience: PosthogJwtAudience,
    options: { maxAge?: string } = {}
): Record<string, unknown> | undefined {
    try {
        const payload = jwt.verify(token, audience, {
            algorithms: ['HS256'],
            clockTolerance: CLOCK_TOLERANCE_SECONDS,
            ...options,
        })
        return payload && typeof payload === 'object' ? (payload as Record<string, unknown>) : undefined
    } catch (err) {
        logger.warn('Recording API JWT verification failed', {
            audience,
            reason: err instanceof Error ? err.name : 'unknown',
        })
        return undefined
    }
}

function timingSafeEqual(a: string, b: string): boolean {
    // Trim so a secret mounted from a file with a trailing newline still matches a sender that
    // trimmed it (mirrors the shared internal-api-auth middleware's newline handling).
    const ab = Buffer.from(a.trim())
    const bb = Buffer.from(b.trim())
    return ab.length === bb.length && crypto.timingSafeEqual(ab, bb)
}

/**
 * Fail closed in production: recording routes must have at least one auth mechanism active. Before the
 * JWT scheme is rolled out the legacy X-Internal-Api-Secret protects prod; once RECORDING_API_JWT_SECRET
 * is set, the JWT does. Only refuse to boot if neither is configured. Uses the same key parsing as the
 * verifier so a malformed-but-truthy value (e.g. ',') counts as "no JWT configured".
 */
export function assertRecordingApiAuthConfigured(opts: {
    isProd: boolean
    jwtSecret: string
    allowLegacySecret: boolean
    legacySecret: string
}): void {
    const hasJwtSecret = hasJwtKeys(opts.jwtSecret || '')
    const hasLegacySecret = opts.allowLegacySecret && !!opts.legacySecret
    if (opts.isProd && !hasJwtSecret && !hasLegacySecret) {
        throw new Error(
            'recording-api has no auth configured in production: set RECORDING_API_JWT_SECRET, ' +
                'or keep RECORDING_API_ALLOW_LEGACY_SECRET enabled with INTERNAL_API_SECRET set'
        )
    }
}

/**
 * Each role must hold exactly the auth it serves. A process serving the browser route needs the blocks secret in
 * production, since no other secret is accepted there. A public process holds no service secret, so it skips the
 * internal check that would otherwise demand one.
 */
export function assertRecordingApiRoleAuthConfigured(opts: {
    role: RecordingApiRole
    isProd: boolean
    blocksJwtSecret: string
    jwtSecret: string
    allowLegacySecret: boolean
    legacySecret: string
}): void {
    if (opts.role !== 'internal' && opts.isProd && !hasJwtKeys(opts.blocksJwtSecret || '')) {
        throw new Error('recording-api serving browser blocks needs RECORDING_API_BLOCKS_JWT_SECRET in production')
    }
    if (opts.role !== 'public') {
        assertRecordingApiAuthConfigured(opts)
    }
}

// The browser block route checks its own browser token, so only a process serving it exempts it from the shared secret.
export function internalApiAuthExcludedPathPrefixes(role: RecordingApiRole): string[] {
    return ['/api/projects/', ...(role === 'internal' ? [] : ['/replay-blocks/'])]
}

export function createRecordingApiAuthMiddleware(options: RecordingApiAuthOptions) {
    const { jwtSecret, legacySecret, allowLegacySecret, op } = options
    // Build the verifier once. Comma-separated keys give zero-downtime rotation (verify against all);
    // a malformed/empty value yields no keys and disables JWT (null) rather than throwing. `|| ''`
    // guards against a partial runtime config where the field is absent.
    const jwt = makeOptionalJwt(jwtSecret || '')
    const legacyEnabled = allowLegacySecret && !!legacySecret

    return (req: Request, res: Response, next: NextFunction): void => {
        // Nothing configured at all (local dev): allow. In every other case some auth is required —
        // before the JWT scheme is enabled in an environment, the legacy secret still protects it.
        if (!jwt && !legacyEnabled) {
            next()
            return
        }

        if (jwt) {
            const bearer = getBearerToken(req)
            if (bearer) {
                // An invalid token falls through to the legacy secret (transition) or a 401.
                const claims = verifyBearer(jwt, bearer, PosthogJwtAudience.RECORDING_API)
                if (claims) {
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
                // Bearer present but invalid — fall through to the legacy secret (transition) or reject.
            }
        }

        if (legacyEnabled) {
            const provided = getHeader(req, INTERNAL_SERVICE_CALL_HEADER_NAME)
            if (provided && timingSafeEqual(provided, legacySecret)) {
                next()
                return
            }
        }

        res.status(401).json({ error: 'Unauthorized' })
    }
}

// A browser block token older than this is refused whatever its exp, so a leaked one stops working soon.
const REPLAY_BLOCKS_TOKEN_MAX_AGE = '2h'

// The browser block route accepts only browser tokens, a separate audience from the service tokens above.
// There is no legacy fallback and no dev bypass: without a secret, every request is refused.
export function createReplayBlocksAuthMiddleware(jwtSecret: string) {
    const jwt = makeOptionalJwt(jwtSecret)

    return (req: Request, res: Response, next: NextFunction): void => {
        // Only a served block may be cached, so every other answer on this route says no-store.
        res.set('Cache-Control', 'no-store')
        const bearer = getBearerToken(req)
        const claims =
            jwt && bearer
                ? verifyBearer(jwt, bearer, PosthogJwtAudience.REPLAY_BLOCKS, { maxAge: REPLAY_BLOCKS_TOKEN_MAX_AGE })
                : undefined
        if (!claims || typeof claims.exp !== 'number') {
            res.status(401).json({ error: 'Unauthorized' })
            return
        }
        // String equality also requires the canonical path spelling, so /01/ never shares a cache entry with /1/.
        if (
            !Number.isInteger(claims.team_id) ||
            String(claims.team_id) !== req.params.team_id ||
            claims.session_id !== req.params.session_id ||
            // The viewer is in the URL so each viewer's blocks are separate browser cache entries: after an account
            // switch the new viewer's URLs never match the previous viewer's cached blocks.
            typeof claims.sub !== 'string' ||
            !claims.sub ||
            claims.sub !== req.params.viewer
        ) {
            res.status(403).json({ error: 'Forbidden: token not scoped to this recording' })
            return
        }
        res.locals.replayBlocksCaller = claims.sub
        res.locals.replayBlocksTier = claims.tier
        next()
    }
}
