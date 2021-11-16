import { createServer, IncomingMessage, ServerResponse } from 'http'

import { healthcheck } from './healthcheck'
import { Status } from './utils/status'

const port = 5000

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
            res.statusCode = 500
            res.end(JSON.stringify(responseBody))
        }
    }
})

export function startServer(logger: Status): void {
    server.listen(port, () => {
        logger.info('🩺', `Status server listening on port ${port}`)
    })
}
