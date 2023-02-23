import { createServer, IncomingMessage, Server, ServerResponse } from 'http'
import { IngestionConsumer } from 'main/ingestion-queues/kafka-queue'
import * as prometheus from 'prom-client'

import { status } from '../../utils/status'

export const HTTP_SERVER_PORT = 6738

prometheus.collectDefaultMetrics()

export function createHttpServer(analyticsEventsIngestionConsumer?: IngestionConsumer): Server {
    const server = createServer((req: IncomingMessage, res: ServerResponse) => {
        if (req.url === '/_health' && req.method === 'GET') {
            status.info('💚', 'Server liveness check succeeded')
            res.end(JSON.stringify({ status: 'ok' }))
        } else if (req.url === '/_ready' && req.method === 'GET') {
            // Check that, if the server should have a kafka queue,
            // the Kafka consumer is ready to consume messages
            if (!analyticsEventsIngestionConsumer || analyticsEventsIngestionConsumer.consumerReady) {
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
        } else if (req.url === '/_metrics' && req.method === 'GET') {
            // Return prometheus metrics for this process.
            //
            // NOTE: we do not currently support gathering metrics from forked
            // processes e.g. those recorded in Piscina Workers. This is because
            // it may well be better to simply remove Piscina workers.
            //
            // See
            // https://github.com/siimon/prom-client/blob/master/example/cluster.js
            // for an example of how to gather metrics from forked processes.

            prometheus.register
                .metrics()
                .then((metrics) => {
                    res.end(metrics)
                })
                .catch((err) => {
                    status.error('🩺', 'Error while collecting metrics', err)
                    res.statusCode = 500
                    res.end()
                })
        } else {
            res.statusCode = 404
            res.end()
        }
    })

    server.listen(HTTP_SERVER_PORT, () => {
        status.info('🩺', `Status server listening on port ${HTTP_SERVER_PORT}`)
    })

    return server
}
