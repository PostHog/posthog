/** Prototype runner: serves the push registration endpoint on its own port so its responses can be
 * diffed against the Django view. Not wired into the plugin server.
 *
 * ENCRYPTION_SALT_KEYS=<same as Django> CAPTURE_INTERNAL_URL=http://127.0.0.1:3307/i/v0/e/ \
 *   DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog PUSH_SERVER_PORT=6750 \
 *   tsx src/messaging/push-subscriptions/standalone.ts
 */
import { createServer } from 'http'

import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { defaultConfig } from '~/common/config/config'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'

import { createPushSubscriptionsHandler } from './push-subscriptions-http'
import { PushSubscriptionsService } from './push-subscriptions.service'

function main(): void {
    const port = parseInt(process.env.PUSH_SERVER_PORT || '6750', 10)
    const postgres = new PostgresRouter(defaultConfig)
    const service = new PushSubscriptionsService(
        new TeamManager(postgres),
        postgres,
        new EncryptedFields(defaultConfig.ENCRYPTION_SALT_KEYS),
        new InternalCaptureService(defaultConfig),
        process.env.SECRET_KEY || 'insecure-secret-key'
    )

    const handler = createPushSubscriptionsHandler(service)
    const server = createServer((req, res) => {
        void handler(req, res).catch((error) => {
            logger.error('push subscription request failed', { error })
            res.writeHead(500, { 'Content-Type': 'application/json' }).end('{"error":"internal"}')
        })
    })
    // Loopback unless asked otherwise: this runs on a developer machine, not behind an ingress.
    const host = process.env.PUSH_SERVER_HOST || '127.0.0.1'
    server.listen(port, host, () => logger.info(`push subscriptions prototype listening on ${host}:${port}`))
}

main()
