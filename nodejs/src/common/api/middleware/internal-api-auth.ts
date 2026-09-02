import crypto from 'crypto'
import { NextFunction, Request, Response } from 'ultimate-express'

import { logger } from '~/common/utils/logger'

/**
 * Internal API authentication middleware.
 *
 * NOTE: This provides defense-in-depth authentication for internal service-to-service
 * calls (e.g., Django -> Node.js CDP API). The primary protection comes from Contour
 * routing configuration at the infrastructure level, which restricts access to internal
 * endpoints. This middleware adds an additional layer of verification using a shared secret.
 *
 * Do not gate new endpoints on this shared secret — prefer a scoped JWT (see recording-api/auth.ts)
 * or a dedicated per-purpose secret. See .agents/security.md ("Secrets & key management").
 */

export const INTERNAL_SERVICE_CALL_HEADER_NAME = 'X-Internal-Api-Secret'

// Paths that don't require authentication (public endpoints and health checks)
const PUBLIC_PATH_PREFIXES = ['/public/', '/_health', '/_ready', '/_metrics', '/metrics']

// Routes that authenticate with their own scoped JWT instead of the shared internal secret, so
// their callers never need INTERNAL_API_SECRET (the goal of retiring it). Each entry must be a
// full-path pattern anchored to exactly one route whose handler enforces its own auth — never
// add a pattern here without one. Suffix matching is not safe for this list: some routes take a
// caller-controlled trailing segment (e.g. batch_invocations' :parent_run_id), so a bare suffix
// like '/cancel' would let a crafted id inherit the exemption and reach a handler that never
// checks a token.
const SCOPED_AUTH_PATH_PATTERNS = [
    // CdpApi.postHogFlowRescheduleParked, verified against WORKFLOWS_RESCHEDULE_JWT_SECRET.
    /^\/api\/projects\/[^/]+\/hog_flows\/[^/]+\/reschedule_parked$/,
    // CdpApi.postHogFlowCancelInvocations, verified against WORKFLOWS_CANCEL_JWT_SECRET, audience-pinned.
    /^\/api\/projects\/[^/]+\/hog_flows\/[^/]+\/invocations\/cancel$/,
    // CdpApi.postHogFlowCancelBatchJob, verified against WORKFLOWS_CANCEL_JWT_SECRET, audience-pinned.
    /^\/api\/projects\/[^/]+\/hog_flows\/[^/]+\/batch_jobs\/[^/]+\/cancel$/,
]

export interface InternalApiAuthOptions {
    secret: string
    // Previous secrets still accepted for verification during zero-downtime rotation.
    fallbacks?: string[]
    excludedPathPrefixes?: string[]
}

export function createInternalApiAuthMiddleware(options: InternalApiAuthOptions) {
    const { secret, fallbacks = [], excludedPathPrefixes = [] } = options
    const allExcludedPrefixes = [...PUBLIC_PATH_PREFIXES, ...excludedPathPrefixes]
    // Accept the primary plus any still-trusted fallbacks (zero-downtime rotation). Trim so a
    // mounted secret's trailing newline can't cause a spurious mismatch between sender and receiver.
    const acceptedSecrets = [secret, ...fallbacks].map((s) => s.trim()).filter(Boolean)

    return (req: Request, res: Response, next: NextFunction): void => {
        // Skip auth if no secret is configured (defense-in-depth only — Contour fronts these endpoints).
        if (acceptedSecrets.length === 0) {
            next()
            return
        }

        // Health/metrics/public endpoints never require auth.
        if (allExcludedPrefixes.some((prefix) => req.path.startsWith(prefix))) {
            next()
            return
        }

        // Scoped-JWT routes enforce their own auth in the handler.
        if (SCOPED_AUTH_PATH_PATTERNS.some((pattern) => pattern.test(req.path))) {
            next()
            return
        }

        const providedSecret =
            req.headers[INTERNAL_SERVICE_CALL_HEADER_NAME] ||
            req.headers[INTERNAL_SERVICE_CALL_HEADER_NAME.toLowerCase()] ||
            req.headers[INTERNAL_SERVICE_CALL_HEADER_NAME.toUpperCase()]

        if (!providedSecret || typeof providedSecret !== 'string') {
            logger.warn('Internal API request missing authentication header', {
                path: req.path,
                method: req.method,
            })
            res.status(401).json({ error: 'Unauthorized: Missing authentication header' })
            return
        }

        // Use timing-safe comparison to prevent timing attacks. Compare against every accepted
        // secret (count is fixed and non-sensitive) so a match on any current-or-fallback value passes.
        const providedBuffer = Buffer.from(providedSecret.trim())
        const matches = acceptedSecrets.some((candidate) => {
            const candidateBuffer = Buffer.from(candidate)
            return (
                candidateBuffer.length === providedBuffer.length &&
                crypto.timingSafeEqual(candidateBuffer, providedBuffer)
            )
        })

        if (!matches) {
            logger.warn('Internal API request with invalid secret', {
                path: req.path,
                method: req.method,
            })
            res.status(401).json({ error: 'Unauthorized: Invalid authentication' })
            return
        }

        next()
    }
}
