import crypto from 'crypto'
import { NextFunction, Request, Response } from 'ultimate-express'

import { isProdEnv } from '~/utils/env-utils'
import { logger } from '~/utils/logger'

/**
 * Internal API authentication middleware.
 *
 * NOTE: This provides defense-in-depth authentication for internal service-to-service
 * calls (e.g., Django -> Node.js CDP API). The primary protection comes from Contour
 * routing configuration at the infrastructure level, which restricts access to internal
 * endpoints. This middleware adds an additional layer of verification using a shared secret.
 */

export const INTERNAL_SERVICE_CALL_HEADER_NAME = 'X-Internal-Api-Secret'

// Paths that don't require authentication (public endpoints and health checks)
const PUBLIC_PATH_PREFIXES = ['/public/', '/_health', '/_ready', '/_metrics', '/metrics']

export interface InternalApiAuthOptions {
    secret: string
    excludedPathPrefixes?: string[]
}

export function createInternalApiAuthMiddleware(options: InternalApiAuthOptions) {
    const { secret, excludedPathPrefixes = [] } = options
    const allExcludedPrefixes = [...PUBLIC_PATH_PREFIXES, ...excludedPathPrefixes]

    // Empty-secret mode (open) is allowed for local dev and tests only. In
    // production it would silently bypass authentication on every non-excluded
    // route, so fail at boot instead.
    if (!secret && isProdEnv()) {
        throw new Error(
            'createInternalApiAuthMiddleware was constructed without a secret in a production environment. ' +
                'Set INTERNAL_API_SECRET so internal endpoints require authentication.'
        )
    }

    return (req: Request, res: Response, next: NextFunction): void => {
        // Skip auth if no secret is configured (for backwards compatibility and local dev)
        if (!secret) {
            next()
            return
        }

        // Skip auth for excluded paths
        if (allExcludedPrefixes.some((prefix) => req.path.startsWith(prefix))) {
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

        // Use timing-safe comparison to prevent timing attacks
        const secretBuffer = Buffer.from(secret)
        const providedBuffer = Buffer.from(providedSecret)

        if (secretBuffer.length !== providedBuffer.length || !crypto.timingSafeEqual(secretBuffer, providedBuffer)) {
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
