import { createServer, IncomingMessage, Server, ServerResponse } from 'http'

import { healthcheck } from '../../healthcheck'
import { PluginServerMode } from '../../types'
import { status } from '../../utils/status'
import { stalenessCheck } from '../../utils/utils'
import { Hub, PluginsServerConfig } from './../../types'

export const HTTP_SERVER_PORTS = {
    [PluginServerMode.Ingestion]: 6738,
    [PluginServerMode.Runner]: 8000,
}

export function createHttpServer(
    hub: Hub | undefined,
    serverConfig: PluginsServerConfig,
    pluginServerMode: PluginServerMode
): Server {
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

    const port = HTTP_SERVER_PORTS[pluginServerMode]

    server.listen(port, () => {
        status.info('🩺', `Status server listening on port ${port}`)
    })

    return server
}
