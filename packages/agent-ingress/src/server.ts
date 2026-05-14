import { collectDefaults, logger, metricsContentType, metricsText } from '@posthog/agent-core'
import express, { Express } from 'ultimate-express'

import { registerHealth } from './routes/health'
import { registerListen } from './routes/listen'
import { registerRun } from './routes/run'
import { registerSend } from './routes/send'
import { registerStatus } from './routes/status'
import { registerWebhooks } from './routes/webhooks'
import { ServerDeps } from './types'

export type { ServerDeps } from './types'

export function buildServer(deps: ServerDeps): Express {
    collectDefaults()

    const app = express()

    app.use(
        express.json({
            limit: '512kb',
            // Stash the raw body so webhook signature checks have access to the exact bytes.
            verify: (req, _res, buf) => {
                ;(req as { rawBody?: Buffer }).rawBody = buf
            },
        })
    )

    app.use((req, _res, next) => {
        logger.debug('ingress request', { method: req.method, path: req.path })
        next()
    })

    registerHealth(app)
    registerStatus(app)
    registerRun(app, deps)
    registerListen(app, deps)
    registerSend(app, deps)
    registerWebhooks(app, deps)

    app.get('/metrics', async (_req, res) => {
        res.set('content-type', metricsContentType())
        res.send(await metricsText())
    })

    return app
}
