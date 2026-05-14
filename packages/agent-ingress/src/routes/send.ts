import { logger } from '@posthog/agent-core'
import { Express, Request, Response } from 'ultimate-express'
import { z } from 'zod'

import { ServerDeps } from '../types'

const SendBodySchema = z.object({
    content: z.string().min(1),
})

/**
 * Publish a user-input message for a session. The runner is subscribed to the
 * session's input channel and picks it up at the next yield.
 */
export function registerSend(app: Express, deps: ServerDeps): void {
    app.post('/send/:id', async (req: Request, res: Response) => {
        const sessionId = req.params.id
        if (!sessionId) {
            return res.status(400).json({ error: 'session id required' })
        }
        const parsed = SendBodySchema.safeParse(req.body)
        if (!parsed.success) {
            return res.status(400).json({ error: 'invalid body', issues: parsed.error.issues })
        }

        try {
            await deps.bus.publishInput(sessionId, {
                type: 'user_message',
                at: new Date().toISOString(),
                content: parsed.data.content,
            })
            return res.status(202).json({ ok: true })
        } catch (err) {
            logger.error('send failed', { sessionId, error: String(err) })
            return res.status(503).json({ error: 'send failed' })
        }
    })
}
