import { NextFunction, Request, Response } from 'ultimate-express'

import { logger } from '~/utils/logger'

/**
 * Creates middleware that validates a Bearer token on /api/ routes.
 * When the token is empty, auth is disabled (for local dev / backwards compat).
 */
export function createApiAuthMiddleware(token: string) {
    return (req: Request, res: Response, next: NextFunction): void => {
        if (!token) {
            next()
            return
        }

        // Only enforce auth on /api/ routes
        if (!req.path.startsWith('/api/')) {
            next()
            return
        }

        const authHeader = req.headers['authorization']
        if (!authHeader || authHeader !== `Bearer ${token}`) {
            logger.warn('Unauthorized API request', { path: req.path })
            res.status(401).json({ error: 'Unauthorized' })
            return
        }

        next()
    }
}
