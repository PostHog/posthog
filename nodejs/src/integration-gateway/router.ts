import { randomUUID } from 'crypto'
import express from 'ultimate-express'

import { logger } from '~/common/utils/logger'

import { emitAudit } from './audit'
import { IntegrationService } from './integration.service'
import { recordFetch } from './metrics'
import { DecryptedIntegration } from './types'

export interface GatewayRouterDeps {
    service: IntegrationService
    maxBatchSize: number
}

/** Best-effort observed source address for the audit trail (independent of the self-reported caller). */
function sourceAddress(req: express.Request): string {
    const forwarded = req.headers['x-forwarded-for']
    if (typeof forwarded === 'string' && forwarded.length > 0) {
        return forwarded.split(',')[0].trim()
    }
    return req.socket?.remoteAddress ?? 'unknown'
}

interface FetchResponseBody {
    // integration id (string key) -> decrypted integration, or null when the id doesn't exist or
    // belongs to another team (indistinguishable on purpose).
    integrations: Record<string, DecryptedIntegration | null>
}

/**
 * Build the credential API router. `POST /api/v1/credentials/fetch` returns every requested id,
 * resolved or null.
 *
 * There is no application-level authentication: access is bounded at the network layer by a Cilium
 * NetworkPolicy that only admits the allow-listed caller workloads. `team_id` and `caller` are
 * therefore plain request fields — self-reported, and trustworthy precisely because the network
 * policy guarantees the request came from a known caller. The observed source address is recorded
 * in the audit trail as an independent (non-self-reported) corroborating signal; verified in-band
 * caller identity (mTLS/SPIFFE) is a possible future hardening step.
 */
export function createGatewayRouter(deps: GatewayRouterDeps): express.Router {
    const router = express.Router()

    router.post('/api/v1/credentials/fetch', async (req: express.Request, res: express.Response): Promise<void> => {
        const body = req.body ?? {}

        const teamId = body.team_id
        if (typeof teamId !== 'number' || !Number.isInteger(teamId)) {
            res.status(400).json({ error: 'team_id must be an integer' })
            return
        }

        // Self-reported label for the audit trail; defaults to 'unknown' when the caller omits it.
        const caller = typeof body.caller === 'string' && body.caller.length > 0 ? body.caller : 'unknown'

        const ids = body.integration_ids
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
            outcome = await deps.service.getForTeam(teamId, ids)
        } catch (error) {
            logger.error('🔑', '[integration_gateway] credential fetch failed', { requestId, error: String(error) })
            recordFetch(caller, 'error')
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
            caller,
            sourceAddress: sourceAddress(req),
            teamId,
            requested: ids,
            resolved: resolvedIds,
            cacheHits: outcome.cacheHits,
            dbLoaded: outcome.dbLoaded,
            requestId,
        })
        recordFetch(caller, 'ok')

        res.status(200).json({ integrations })
    })

    return router
}
