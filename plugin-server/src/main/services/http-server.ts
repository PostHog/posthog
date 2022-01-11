import { createServer, IncomingMessage, ServerResponse } from 'http'

import { healthcheck } from '../../healthcheck'
import { Status } from '../../utils/status'
import { Hub } from './../../types'

const PORT = 5000

export function createHttpServer(hub: Hub): (logger: Status) => void {
    const server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
        if (req.url === '/health' && req.method === 'GET') {
            const status = await healthcheck()
            if (status) {
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
        }
    })

    const startServer = (logger: Status): void => {
        server.listen(PORT, () => {
            logger.info('🩺', `Status server listening on port ${PORT}`)
        })
    }

    return startServer
}
