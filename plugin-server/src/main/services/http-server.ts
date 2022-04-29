import { createServer, IncomingMessage, Server, ServerResponse } from 'http'

import { healthcheck } from '../../healthcheck'
import { status } from '../../utils/status'
import { stalenessCheck } from '../../utils/utils'
import { Hub, PluginsServerConfig } from './../../types'

export const HTTP_SERVER_PORT = 6738

export function createHttpServer(hub: Hub | undefined, serverConfig: PluginsServerConfig): Server {
    const server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
        if (req.url === '/_health' && req.method === 'GET') {
            const status = await healthcheck()
            const ok = status ? !stalenessCheck(hub, serverConfig.HEALTHCHECK_MAX_STALE_SECONDS).isServerStale : false
            if (ok) {
                const responseBody = {
                    status: 'ok',
                }
                res.statusCode = 200
                res.end(JSON.stringify(responseBody))
            } else {
                const responseBody = {
                    status: 'error',
                }
                res.statusCode = 503
                res.end(JSON.stringify(responseBody))
            }
        } else if (req.url === '/_ready' && req.method === 'GET') {
            // if the http server was setup correctly, we're ready to start ingesting events
            status.info('💚', 'Server readiness check')
            const responseBody = {
                status: 'ok',
            }
            res.statusCode = 200
            res.end(JSON.stringify(responseBody))
        }
    })

    server.listen(HTTP_SERVER_PORT, () => {
        status.info('🩺', `Status server listening on port ${HTTP_SERVER_PORT}`)
    })

    return server
}
