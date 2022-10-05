import { createServer, IncomingMessage, Server, ServerResponse } from 'http'

import { status } from '../../utils/status'
import { ServerInstance } from '../pluginsServer'
import { Hub } from './../../types'

export const HTTP_SERVER_PORT = 6739

export function createHttpServer(hub: Hub, serverInstance: ServerInstance): Server {
    const server = createServer((req: IncomingMessage, res: ServerResponse) => {
        if (req.url === '/_health' && req.method === 'GET') {
            status.info('💚', 'Server liveness check succeeded')
            res.end(JSON.stringify({ status: 'ok' }))
        } else if (req.url === '/_ready' && req.method === 'GET') {
            // Check that, if the server should have a kafka queue,
            // the Kafka consumer is ready to consume messages
            if (!serverInstance.queue || serverInstance.queue.consumerReady) {
                status.info('💚', 'Server readiness check succeeded')
                const responseBody = {
                    status: 'ok',
                }
                res.statusCode = 200
                res.end(JSON.stringify(responseBody))
            } else {
                status.info('💔', 'Server readiness check failed')
                const responseBody = {
                    status: 'error',
                }
                res.statusCode = 503
                res.end(JSON.stringify(responseBody))
            }
        }
    })

    server.listen(HTTP_SERVER_PORT, () => {
        status.info('🩺', `Status server listening on port ${HTTP_SERVER_PORT}`)
    })

    return server
}
