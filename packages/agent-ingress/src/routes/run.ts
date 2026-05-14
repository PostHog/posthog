import { logger } from '@posthog/agent-core'
import { Express, Request, Response } from 'ultimate-express'
import { z } from 'zod'

import { authorize, AuthRequest } from '../auth'
import { ServerDeps } from '../types'
import { extractHost } from './host'

const RunBodySchema = z.object({
    /** Optional explicit application id; falls back to host-based resolution. */
    applicationId: z.string().uuid().optional(),
    input: z.record(z.string(), z.unknown()).optional(),
    triggerType: z.string().default('http'),
    triggerPayload: z.record(z.string(), z.unknown()).optional(),
})

export function registerRun(app: Express, deps: ServerDeps): void {
    app.post('/run', async (req: Request, res: Response) => {
        const parsed = RunBodySchema.safeParse(req.body)
        if (!parsed.success) {
            return res.status(400).json({ error: 'invalid body', issues: parsed.error.issues })
        }
        const body = parsed.data

        let revision
        try {
            if (body.applicationId) {
                revision = await deps.resolver.resolveApplication(body.applicationId)
            } else {
                const host = extractHost(req, deps.domainSuffix)
                if (!host) {
                    return res.status(400).json({ error: `host does not match ${deps.domainSuffix}` })
                }
                revision = await deps.resolver.resolveDomain(host)
            }
        } catch (err) {
            logger.error('resolve failed in /run', { error: String(err) })
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
                state: body.input ? Buffer.from(JSON.stringify(body.input)) : null,
            })
            return res.status(202).json({ sessionId })
        } catch (err) {
            logger.error('enqueue failed in /run', { error: String(err) })
            return res.status(503).json({ error: 'enqueue failed' })
        }
    })
}
