import { logger } from '@posthog/agent-core'
import { Express, Request, Response } from 'ultimate-express'

import { authorize, AuthRequest } from '../auth'
import { ServerDeps } from '../types'
import { extractHost } from './host'

/**
 * Receive a provider webhook and turn it into a session. Auth is governed by the
 * resolved revision's `webhook_signature` mode (HMAC over raw body).
 */
export function registerWebhooks(app: Express, deps: ServerDeps): void {
    app.post('/webhooks/:provider', async (req: Request, res: Response) => {
        const provider = req.params.provider
        if (!provider) {
            return res.status(400).json({ error: 'provider required' })
        }

        const host = extractHost(req, deps.domainSuffix)
        if (!host) {
            return res.status(400).json({ error: `host does not match ${deps.domainSuffix}` })
        }
        let revision
        try {
            revision = await deps.resolver.resolveDomain(host)
        } catch (err) {
            logger.error('resolve failed in /webhooks', { error: String(err) })
            return res.status(502).json({ error: 'resolve failed' })
        }
        if (!revision) {
            return res.status(404).json({ error: 'application not found' })
        }
        if (revision.revisionState !== 'ready') {
            return res.status(409).json({ error: `revision not ready (state=${revision.revisionState})` })
        }

        const auth = authorize(req as AuthRequest, revision)
        if (!auth.ok) {
            return res.status(auth.status).json({ error: auth.message })
        }

        try {
            const sessionId = await deps.queue.createJob({
                teamId: revision.teamId,
                applicationId: revision.applicationId,
                revisionId: revision.revisionId,
                queueName: 'default',
                state: Buffer.from(JSON.stringify({ provider, body: req.body })),
            })
            return res.status(202).json({ sessionId })
        } catch (err) {
            logger.error('enqueue failed in /webhooks', { provider, error: String(err) })
            return res.status(503).json({ error: 'enqueue failed' })
        }
    })
}
