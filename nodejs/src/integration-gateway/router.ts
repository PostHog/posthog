import { randomUUID } from 'crypto'
import express from 'ultimate-express'

import { logger } from '~/common/utils/logger'

import { emitAudit } from './audit'
import { GatewayAuth } from './auth'
import { IntegrationService } from './integration.service'
import { recordFetch } from './metrics'
import { DecryptedIntegration } from './types'

export interface GatewayRouterDeps {
    service: IntegrationService
    auth: GatewayAuth
    maxBatchSize: number
}

interface FetchResponseBody {
    // integration id (string key) -> decrypted integration, or null when the id doesn't exist or
    // belongs to another team (indistinguishable on purpose).
    integrations: Record<string, DecryptedIntegration | null>
}

/**
 * Build the credential API router. `POST /api/v1/credentials/fetch` authenticates with a scoped
 * JWT (never the internal API secret) and returns every requested id, resolved or null.
 */
export function createGatewayRouter(deps: GatewayRouterDeps): express.Router {
    const router = express.Router()

    router.post('/api/v1/credentials/fetch', async (req: express.Request, res: express.Response): Promise<void> => {
        const caller = deps.auth.verify(req.headers['authorization'])
        if (!caller) {
            res.status(401).json({ error: 'unauthorized' })
            return
        }

        const ids = (req.body ?? {}).integration_ids
        if (!Array.isArray(ids) || !ids.every((id) => typeof id === 'number' && Number.isInteger(id))) {
            res.status(400).json({ error: 'integration_ids must be an array of integers' })
            return
        }
        if (ids.length > deps.maxBatchSize) {
            res.status(400).json({ error: `too many integration_ids (max ${deps.maxBatchSize})` })
            return
        }

        const requestId = randomUUID()
        let outcome
        try {
            outcome = await deps.service.getForTeam(caller.teamId, ids)
        } catch (error) {
            logger.error('🔑', '[integration_gateway] credential fetch failed', { requestId, error: String(error) })
            recordFetch(caller.caller, 'error')
            res.status(500).json({ error: 'internal error' })
            return
        }

        // Every requested id appears in the response, resolved or null.
        const integrations: FetchResponseBody['integrations'] = {}
        const resolvedIds: number[] = []
        for (const id of ids) {
            const resolved = outcome.resolved.get(id)
            if (resolved) {
                resolvedIds.push(id)
                integrations[String(id)] = resolved
            } else {
                integrations[String(id)] = null
            }
        }

        emitAudit({
            caller: caller.caller,
            teamId: caller.teamId,
            requested: ids,
            resolved: resolvedIds,
            cacheHits: outcome.cacheHits,
            dbLoaded: outcome.dbLoaded,
            requestId,
        })
        recordFetch(caller.caller, 'ok')

        res.status(200).json({ integrations })
    })

    return router
}
